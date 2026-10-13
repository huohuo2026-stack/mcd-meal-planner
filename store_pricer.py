# -*- coding: utf-8 -*-
"""
门店点餐比价引擎（比价版主线）

产品定位：回答「在真实门店，同一份东西怎么点最划算」。
与营养版（planner.py）完全独立，互不依赖，各自讲各自的故事。

核心能力：
  1. 门店商品清单（含单品/组合/套餐三档）
  2. 预算内组合推荐（按真实价格，不涉及营养）
  3. 单品 vs 组合 vs 套餐 价差分析
  4. 同款不同档对比（同一主食的单点/组合/套餐差价）

设计说明：
  - 数据源：门店菜单价格表（pricing.PriceTable）
  - 分类靠名字规则（菜单不含分类字段，但含清晰的命名规律）
  - 价格单位统一为元
"""
import re

# 商品档位判定
def tier_of(name):
    """判定商品档位：单品 / 组合 / 套餐"""
    if name.endswith("三件套") or name.endswith("二件套"):
        return "套餐"
    if name.endswith("套餐"):
        return "套餐"
    if name.endswith("组合"):
        return "组合"
    return "单品"


# 商品角色判定（用于结构化组合）
DRINK_KW = ["可乐", "雪碧", "美式", "拿铁", "奶铁", "卡布", "摩卡", "牛奶", "豆浆",
            "红茶", "柠红茶", "苹果汁", "橙橙", "柠柠", "怡泉", "纯悦", "咖啡",
            "鲜萃", "浓缩", "燕麦奶", "雪冰", "黑巧", "阿芙佳朵"]
DESSERT_KW = ["冰淇淋", "圆筒", "新地", "麦旋风", "派", "阿芙佳朵"]
SIDE_KW = ["薯条", "薯饼", "油条", "玉米杯", "香肠", "麦乐鸡", "鸡翅", "脆汁鸡",
           "趣鸡球", "沙拉", "苹果片"]
MAIN_KW = ["麦满分", "堡", "卷", "麦香鸡", "麦香鱼", "巨无霸", "三明治", "帕尼尼",
           "早安营养卷", "厚松饼", "板烧"]


def role_of(name):
    """判定商品角色：主食 / 小食 / 饮品 / 甜点"""
    # 组合/套餐类不参与角色判定（它们是整体商品）
    for kw in DESSERT_KW:
        if kw in name:
            return "甜点"
    for kw in DRINK_KW:
        if kw in name:
            return "饮品"
    for kw in MAIN_KW:
        if kw in name:
            return "主食"
    for kw in SIDE_KW:
        if kw in name:
            return "小食"
    # 兜底：含"套"的视为完整餐（归主食，可独立成餐）
    if "套" in name:
        return "主食"
    return "其他"


class StorePricer:
    """基于门店价格表的点餐分析器。"""

    def __init__(self, price_table):
        self.pt = price_table
        self.items = []
        for name, row in price_table.rows.items():
            self.items.append({
                "name": name,
                "price": row["price"],
                "original": row["original"],
                "discount": row["discount"],
                "code": row["code"],
                "tier": tier_of(name),
                "role": role_of(name),
            })
        self.by_role = {}
        for it in self.items:
            self.by_role.setdefault(it["role"], []).append(it)

    # ---------- 报价 ----------
    def quote(self, names):
        """给定商品名列表，返回总价与明细。"""
        detail, total = [], 0.0
        for n in names:
            hit = self.pt.rows.get(n)
            if not hit:
                return None
            detail.append({"name": n, "price": hit["price"], "code": hit["code"]})
            total += hit["price"]
        return {"items": detail, "total": round(total, 2), "count": len(names)}

    # ---------- 档位对比 ----------
    def tier_compare(self):
        """
        找出同一主食在「单品/组合/套餐」三档的价格，计算差价。
        用于回答「加两块钱变组合，值不值」。
        """
        # 归一化主体名：去掉「组合/套餐/三件套」后缀 + 品牌前缀
        groups = {}
        for it in self.items:
            base = it["name"]
            for suffix in ["三件套", "二件套", "套餐", "组合"]:
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
                    break
            base = base.replace("麦咖啡™", "").strip()
            groups.setdefault(base, []).append(it)

        out = []
        for base, lst in groups.items():
            tiers = {x["tier"]: x for x in lst}
            if len(tiers) < 2:
                continue
            rec = {"base": base, "tiers": {}}
            for t, x in tiers.items():
                rec["tiers"][t] = {"name": x["name"], "price": x["price"]}
            # 计算升级差价
            single = tiers.get("单品")
            combo = tiers.get("组合")
            meal = tiers.get("套餐")
            if single and combo:
                rec["combo_diff"] = round(combo["price"] - single["price"], 2)
            if single and meal:
                rec["meal_diff"] = round(meal["price"] - single["price"], 2)
            out.append(rec)
        out.sort(key=lambda r: r.get("meal_diff", 99))
        return out

    # ---------- 预算内组合 ----------
    def budget_combo(self, budget, want_drink=True, want_dessert=False,
                     top_n=5):
        """
        给定预算，从门店真实商品中组合推荐（按价格，不涉及营养）。
        结构：主食 1 + 小食 0-1 + 饮品 0-1（可选甜点 0-1）
        """
        mains = [x for x in self.by_role.get("主食", []) if x["tier"] == "单品"
                 and x["price"] <= budget]
        sides = [x for x in self.by_role.get("小食", []) if x["tier"] == "单品"]
        drinks = ([x for x in self.by_role.get("饮品", []) if x["tier"] == "单品"]
                  if want_drink else [])
        desserts = ([x for x in self.by_role.get("甜点", []) if x["tier"] == "单品"]
                    if want_dessert else [])

        combos = []
        import itertools
        side_opts = [[]] + [[s] for s in sides]
        drink_opts = [[]] + [[d] for d in drinks]
        dessert_opts = ([[]] + [[x] for x in desserts]) if desserts else [[]]

        for m in mains:
            for so in side_opts:
                for do in drink_opts:
                    for dso in dessert_opts:
                        combo = [m] + so + do + dso
                        total = sum(x["price"] for x in combo)
                        if total <= budget:
                            combos.append((total, combo))

        # 按「用满预算」排序（花得越接近预算越划算），再按商品数降序
        combos.sort(key=lambda x: (-x[0], -len(x[1])))
        seen = set()
        used_mains = set()
        out = []
        # 第一轮：主餐不重复，保证方案有区分度
        for total, combo in combos:
            key = tuple(sorted(x["name"] for x in combo))
            if key in seen:
                continue
            main = tuple(sorted(x["name"] for x in combo if x["role"] == "主食"))
            if main in used_mains:
                continue
            seen.add(key)
            used_mains.add(main)
            out.append({
                "items": [{"name": x["name"], "price": x["price"],
                           "role": x["role"], "tier": x["tier"]} for x in combo],
                "total": round(total, 2),
                "count": len(combo),
                "remaining": round(budget - total, 2),
            })
            if len(out) >= top_n:
                break

        # 兜底：主餐可选数不足时放宽
        if len(out) < top_n:
            for total, combo in combos:
                key = tuple(sorted(x["name"] for x in combo))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "items": [{"name": x["name"], "price": x["price"],
                               "role": x["role"], "tier": x["tier"]} for x in combo],
                    "total": round(total, 2),
                    "count": len(combo),
                    "remaining": round(budget - total, 2),
                })
                if len(out) >= top_n:
                    break
        return {"budget": budget, "store": self.pt.store_name,
                "storeCode": self.pt.store_code, "results": out}

    def stats(self):
        from collections import Counter
        return {
            "store": self.pt.store_name,
            "storeCode": self.pt.store_code,
            "total": len(self.items),
            "tier": dict(Counter(x["tier"] for x in self.items)),
            "role": dict(Counter(x["role"] for x in self.items)),
        }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import pricing as pr
    pt = pr.build_price_table("1421180", "麦当劳深圳华强北茂业餐厅")
    sp = StorePricer(pt)
    print("门店统计:", sp.stats())
    print("\n=== 预算 40 元组合推荐 ===")
    r = sp.budget_combo(40, top_n=3)
    for i, c in enumerate(r["results"], 1):
        print("\n方案%d 合计 ¥%.2f (余 ¥%.2f)" % (i, c["total"], c["remaining"]))
        for it in c["items"]:
            print("   %-24s ¥%6.2f [%s/%s]" % (it["name"], it["price"],
                                              it["tier"], it["role"]))
    print("\n=== 档位差价分析 TOP5 ===")
    for rec in sp.tier_compare()[:5]:
        print("  %-22s 组合+%s 套餐+%s" % (rec["base"],
                                         rec.get("combo_diff", "-"),
                                         rec.get("meal_diff", "-")))
