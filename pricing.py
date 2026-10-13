# -*- coding: utf-8 -*-
"""
比价层 + 混合模式路由

职责：
1. 拉取门店菜单并建立「餐品名 → code/价格」的完整价格表（1 次批量调用）
2. 为本地推荐结果（按名字）匹配真实门店价格
3. 混合路由：有门店走比价版，无门店或失败则回退纯营养版

性能设计（基于实测）：
- calculate-price 支持批量，且返回 productName
  → 整店价格表只需 1 次调用（实测 89 个商品一次返回）
- 价格表按 storeCode 缓存到 data/price_cache.json，避免重复联网
"""
import json
import os
import time

import mcd_client as mc

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, "data", "price_cache.json")
CACHE_TTL = 3600  # 价格缓存有效期（秒）


class PriceTable:
    """某门店的餐品价格表：name -> {code, price, original, discount}"""

    def __init__(self, store_code, store_name="", rows=None, fetched_at=0):
        self.store_code = str(store_code)
        self.store_name = store_name
        self.rows = rows or {}      # name -> dict
        self.fetched_at = fetched_at

    @property
    def fresh(self):
        return (time.time() - self.fetched_at) < CACHE_TTL

    def price_of(self, name):
        return self.rows.get(name)

    def to_dict(self):
        return {"store_code": self.store_code, "store_name": self.store_name,
                "fetched_at": self.fetched_at, "rows": self.rows}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("store_code", ""), d.get("store_name", ""),
                   d.get("rows", {}), d.get("fetched_at", 0))


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def build_price_table(store_code, store_name="", use_cache=True, token=None):
    """
    构建门店价格表。
    流程：query_meals 拿全部 code → 一次 calculate-price 批量换回 name+价格
    返回 PriceTable。失败抛 MCPError，由上层决定回退。
    """
    cache = _load_cache()
    if use_cache and str(store_code) in cache:
        pt = PriceTable.from_dict(cache[str(store_code)])
        if pt.fresh:
            return pt

    # 1) 菜单：拿全部 code
    menu = mc.query_meals(store_code, token=token)
    codes = []
    for cat in (menu.get("categories") or []):
        for m in (cat.get("meals") or []):
            c = m.get("code")
            if c:
                codes.append(str(c))
    codes = list(dict.fromkeys(codes))
    if not codes:
        raise mc.MCPError("门店 %s 菜单为空" % store_code)

    # 2) 批量比价：一次拿回 name + 价格
    items = [{"productCode": c, "quantity": 1} for c in codes]
    result = mc.calculate_price(store_code, items, strict=False, token=token)

    rows = {}
    for p in result.get("product_list") or []:
        name = p.get("productName")
        if not name:
            continue
        sub = int(p.get("subtotal", 0) or 0)
        orig = int(p.get("originalSubtotal", 0) or 0)
        rows[name] = {
            "code": str(p.get("productCode")),
            "price_fen": sub,
            "price": sub / 100.0,
            "original_fen": orig,
            "original": orig / 100.0,
            "discount_fen": max(0, orig - sub),
            "discount": max(0, orig - sub) / 100.0,
        }

    pt = PriceTable(store_code, store_name, rows, time.time())
    cache[str(store_code)] = pt.to_dict()
    _save_cache(cache)
    return pt


def enrich_with_price(plan_result, price_table, fuzzy=True):
    """
    给推荐结果补价格。
    plan_result: planner.recommend() 的返回
    返回新的结果 dict，每项套餐增加 total_price / matched / unmatched。
    """
    out = json.loads(json.dumps(plan_result, ensure_ascii=False))
    for res in out.get("results", []):
        total = 0.0
        matched, unmatched = [], []
        for it in res["items"]:
            hit = _fuzzy_lookup(it["name"], price_table) if fuzzy \
                else price_table.price_of(it["name"])
            if hit:
                it["price"] = hit["price"]
                it["price_code"] = hit["code"]
                total += hit["price"]
                matched.append(it["name"])
            else:
                it["price"] = None
                unmatched.append(it["name"])
        res["total_price"] = round(total, 2)
        res["matched"] = matched
        res["unmatched"] = unmatched
        res["price_complete"] = (len(unmatched) == 0)
    out["store"] = {"storeCode": price_table.store_code,
                    "storeName": price_table.store_name}
    out["priced"] = True
    return out


def _normalize_name(name):
    """
    名字归一化，用于提升两套体系的匹配率。
    处理实测发现的差异：
      - 品牌前缀：'麦咖啡™冰美式中杯' -> '冰美式中杯'
      - 套餐后缀：'原味板烧鸡腿麦满分套餐' -> '原味板烧鸡腿麦满分'
      - 组合后缀：'…组合' -> '…'
      - 全角/半角、空格、™ 等符号
    """
    s = name or ""
    for junk in ["麦咖啡™", "麦咖啡", "™", "·", " "]:
        s = s.replace(junk, "")
    for suffix in ["套餐", "组合", "三件套", "二件套"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _build_norm_index(price_table):
    """构建归一化名 -> 价格行 的索引（懒加载，缓存到对象上）。"""
    idx = getattr(price_table, "_norm_index", None)
    if idx is not None:
        return idx
    idx = {}
    for name, row in price_table.rows.items():
        key = _normalize_name(name)
        # 同名冲突时保留价格较低者（通常是单品，更保守）
        if key not in idx or row["price_fen"] < idx[key]["price_fen"]:
            idx[key] = row
    price_table._norm_index = idx
    return idx


def _fuzzy_lookup(name, price_table, threshold=0.72):
    """
    三级匹配：精确 -> 归一化 -> 模糊相似度。
    用于弥合本地营养库（全国标准品）与门店菜单（实际在售品）的命名差异。
    """
    # 1) 精确
    hit = price_table.rows.get(name)
    if hit:
        return hit
    # 2) 归一化
    idx = _build_norm_index(price_table)
    hit = idx.get(_normalize_name(name))
    if hit:
        return hit
    # 3) 模糊
    import difflib
    keys = list(idx.keys())
    if not keys:
        return None
    cand = difflib.get_close_matches(_normalize_name(name), keys, n=1,
                                     cutoff=threshold)
    if cand:
        return idx[cand[0]]
    return None


def recommend_with_price(planner, budget, profile_name, top_n,
                         city=None, keyword=None, store_code=None,
                         use_cache=True, token=None, **kw):
    """
    混合模式主入口。

    路由规则：
      - 若提供 city+keyword（或 store_code）→ 尝试比价版
      - 比价任一步失败 → 回退纯营养版，并记录 fallback 原因
      - 未提供门店信息 → 直接走纯营养版

    返回 plan_result，附加字段：
      priced: bool
      store: {storeCode, storeName} 或 None
      fallback: 回退原因（若发生）
    """
    base = planner.recommend(budget=budget, profile_name=profile_name,
                             top_n=top_n, **kw)
    base["priced"] = False
    base["store"] = None
    base["fallback"] = None

    if not (store_code or (city and keyword)):
        return base  # 纯营养模式

    try:
        sc, sname = store_code, ""
        if not sc:
            stores = mc.query_stores(city, keyword, token=token)
            if not stores:
                raise mc.MCPError("未找到门店：%s %s" % (city, keyword))
            sc, sname = stores[0]["storeCode"], stores[0]["storeName"]
        pt = build_price_table(sc, sname, use_cache=use_cache, token=token)
        priced = enrich_with_price(base, pt)
        priced["fallback"] = None
        return priced
    except Exception as e:  # noqa: BLE001 —— 比价失败必须回退，不能让用户无解
        base["fallback"] = str(e)
        return base


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    from planner import MealPlanner
    p = MealPlanner()
    r = recommend_with_price(p, 500, "均衡", 3,
                             city="深圳市", keyword="华强北")
    print("比价模式:", r["priced"], "| 门店:", r["store"])
    print("回退原因:", r["fallback"])
    for i, res in enumerate(r["results"], 1):
        print("\n方案%d 总价 ¥%.2f (完整=%s)" % (i, res.get("total_price", 0),
                                                res.get("price_complete")))
        for it in res["items"]:
            pr = ("¥%.2f" % it["price"]) if it.get("price") is not None else "—"
            print("   %-22s %4d kcal %8s" % (it["name"], it["kcal"], pr))
