# -*- coding: utf-8 -*-
"""
套餐组合推荐引擎（方案甲：纯单品自由组合）

输入：热量预算 / 减脂-增肌-均衡目标 / 是否要饮品甜点
输出：TOP-N 个套餐组合，每个含明细与营养汇总

算法设计（三层）：
  1. 候选池构建：按角色（主食/小食/饮品/甜点）分组，剔除 0 kcal 干扰项
  2. 组合枚举：主食 1-2 + 小食 0-2 + 饮品 0-1 + 甜点 0-1，笛卡尔积裁剪
  3. 多目标评分：热量贴合度 + 营养素均衡度 + 角色完整度，加权排序

设计取舍说明：
- 用「枚举 + 评分」而非「随机搜索」：160 个单品组合空间可控，
  枚举能保证结果稳定可复现，方便评审验证。
- 评分权重可调（PROFILES），用于区分减脂/增肌/均衡三档目标。
"""
import json
import os
import random
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data", "nutrition.json")

# ---------- 目标画像 ----------
# 说明：这些权重必须"足以改变排序"，否则不同目标会产出相同方案（历史缺陷）。
# 实测调参依据：热量贴合度基准权重 3.0、结构分 1.0；
# 目标项若权重过小（原先 protein_w/pw*2 最大仅 4.0）会被基准项压制。
# 现调整为：目标项总权重 6~9，确保能主导排序。
PROFILES = {
    #          蛋白权重  脂肪惩罚  碳水权重  热量容忍  脂肪硬上限(供能比)
    "均衡": {"protein_w": 1.0, "fat_penalty": 1.2, "carb_w": 0.6,
             "kcal_tol": 0.12, "fat_cap": None},
    "减脂": {"protein_w": 2.2, "fat_penalty": 3.0, "carb_w": 0.3,
             "kcal_tol": 0.10, "fat_cap": 0.32},
    "增肌": {"protein_w": 3.5, "fat_penalty": 0.4, "carb_w": 1.2,
             "kcal_tol": 0.15, "fat_cap": None},
    "轻食": {"protein_w": 1.6, "fat_penalty": 2.4, "carb_w": 0.4,
             "kcal_tol": 0.08, "fat_cap": 0.30},
}

# 角色优先级：构建组合时的结构约束
ROLE_MAIN = "主食"
ROLE_SIDE = "小食"
ROLE_DRINK = "饮品"
ROLE_DESSERT = "甜点"
ROLE_BREAKFAST = "早餐"


class MealPlanner:
    def __init__(self, data_file=DATA_FILE):
        with open(data_file, encoding="utf-8") as f:
            payload = json.load(f)
        self.items = payload["items"]
        self.fetched_at = payload.get("fetched_at", "")
        self._group()

    def _group(self):
        """
        按角色分组。饮品/甜点单独成组。
        关键：主食候选池只放「正餐主体」——汉堡/麦满分/卷/饭等能撑起一顿的品项。
        德国香肠、脆汁鸡、鸡球这类虽被归入早餐/小食，但不能当一餐主体，
        否则会产出「香肠+饮料」这种不成餐的组合（实测踩过）。
        """
        self.by_role = {ROLE_MAIN: [], ROLE_SIDE: [], ROLE_DRINK: [],
                        ROLE_DESSERT: [], ROLE_BREAKFAST: []}
        self.zero_kcal = []
        # 正餐主体白名单关键词
        main_kw = ["麦满分", "汉堡", "堡", "卷", "饭", "面", "三明治", "帕尼尼",
                   "麦香鸡", "麦香鱼", "巨无霸", "披萨", "托盘", "牛气", "果然多肉",
                   "薯鱼", "双翅", "蜜汁快乐", "支撑"]
        # 明确排除：这些即使含主关键词也不是主体
        main_exclude = ["香肠", "脆汁鸡", "趣鸡球", "鸡翅", "V翅", "沙拉", "薯条"]

        for it in self.items:
            if it["kcal"] <= 0:
                self.zero_kcal.append(it)
                if it["category"] == ROLE_DRINK:
                    self.by_role[ROLE_DRINK].append(it)
                continue
            cat = it["category"]
            name = it["name"]
            if cat == ROLE_DRINK:
                self.by_role[ROLE_DRINK].append(it)
            elif cat == ROLE_DESSERT:
                self.by_role[ROLE_DESSERT].append(it)
            elif cat == ROLE_SIDE:
                self.by_role[ROLE_SIDE].append(it)
            else:
                # 早餐/主食/其他 → 判定是否为正餐主体
                is_main = any(k in name for k in main_kw) and \
                          not any(e in name for e in main_exclude)
                if is_main:
                    self.by_role[ROLE_MAIN].append(it)
                else:
                    self.by_role[ROLE_SIDE].append(it)

    # ---------- 组合构建 ----------
    def _build_candidates(self, budget, profile,
                          want_drink=True, want_dessert=False,
                          allow_breakfast=True):
        """
        枚举候选组合。返回 list[list[item]]。
        规则：
          - 必需 1 个主食（汉堡类 或 早餐麦满分类）
          - 小食 0-2 个
          - 饮品 0-1 个（want_drink 控制）
          - 甜点 0-1 个（want_dessert 控制）
          - 组合总热量 <= budget * (1 + tol) 且 >= budget * 0.55
        """
        mains = list(self.by_role[ROLE_MAIN])
        sides = self.by_role[ROLE_SIDE]
        drinks = self.by_role[ROLE_DRINK] if want_drink else []
        desserts = self.by_role[ROLE_DESSERT] if want_dessert else []

        tol = profile["kcal_tol"]
        # 硬上限：严格不超预算（用户设定预算是上限承诺，超 1 kcal 也不接受）
        hi = budget
        lo = budget * 0.55

        out = []
        # 主食用单品的组合：主食 1 个（避免双主食热量过载，除非预算很高）
        main_pool_single = [m for m in mains if m["kcal"] <= hi]
        for m in main_pool_single:
            base = [m]
            base_kcal = m["kcal"]
            # 小食 0/1/2
            side_opts = [[], ] + [[s] for s in sides] + \
                        [list(c) for c in combinations(sides, 2)]
            for so in side_opts:
                k1 = base_kcal + sum(x["kcal"] for x in so)
                if k1 > hi:
                    continue
                # 饮品
                drink_opts = [[]] if not drinks else ([[]] + [[d] for d in drinks])
                for do in drink_opts:
                    k2 = k1 + sum(x["kcal"] for x in do)
                    if k2 > hi:
                        continue
                    # 甜点
                    dessert_opts = [[]] if not desserts else ([[]] + [[x] for x in desserts])
                    for dso in dessert_opts:
                        k3 = k2 + sum(x["kcal"] for x in dso)
                        if k3 > hi or k3 < lo:
                            continue
                        out.append(base + so + do + dso)
        return out

    def _build_light(self, budget, profile, want_drink=True, want_dessert=False):
        """
        降级组合池：预算不足以容纳任何正餐主体时使用。
        做法：从小食 + 饮品 + 甜点（不强制主食）中组合，总量 <= 预算。
        """
        pool = list(self.by_role[ROLE_SIDE])
        if want_drink:
            pool += self.by_role[ROLE_DRINK]
        if want_dessert:
            pool += self.by_role[ROLE_DESSERT]
        pool = [x for x in pool if 0 < x["kcal"] <= budget]
        pool.sort(key=lambda x: x["kcal"])

        out = []
        # 单品
        for x in pool:
            out.append([x])
        # 双品组合
        for i, a in enumerate(pool):
            for b in pool[i + 1:]:
                if a["kcal"] + b["kcal"] <= budget:
                    out.append([a, b])
                else:
                    break
        # 三品组合（仅当预算允许）
        for i, a in enumerate(pool):
            for j in range(i + 1, len(pool)):
                b = pool[j]
                if a["kcal"] + b["kcal"] >= budget:
                    break
                for k in range(j + 1, len(pool)):
                    c = pool[k]
                    if a["kcal"] + b["kcal"] + c["kcal"] <= budget:
                        out.append([a, b, c])
                    else:
                        break
        return out

    # ---------- 评分 ----------
    def _score(self, combo, budget, profile):
        """返回 (总分, 明细dict)。分数越高越好。"""
        k = sum(x["kcal"] for x in combo)
        p = sum(x["protein"] for x in combo)
        f = sum(x["fat"] for x in combo)
        c = sum(x["carb"] for x in combo)
        na = sum(x["sodium"] for x in combo)

        # 1) 热量贴合度：越接近预算越好（相对误差）
        rel = abs(k - budget) / max(budget, 1)
        s_kcal = max(0.0, 1.0 - rel / max(profile["kcal_tol"], 0.01))

        # 2) 蛋白质密度：每 100 kcal 的蛋白克数，越高越好
        p_density = p / max(k / 100.0, 1.0)
        s_protein = min(p_density / 8.0, 1.0)  # 8g/100kcal 视为满分

        # 3) 脂肪控制：脂肪供能占比，越低越好（惩罚项）
        fat_energy = f * 9
        fat_ratio = fat_energy / max(k, 1)
        s_fat = max(0.0, 1.0 - max(0.0, fat_ratio - 0.35) / 0.35)

        # 4) 钠惩罚：过量钠扣分（>1500mg 开始扣）
        s_sodium = max(0.0, 1.0 - max(0.0, na - 1500) / 1500.0)

        # 5) 结构完整度：有主食+小食+饮品 加分
        roles = {x["category"] for x in combo}
        struct = 0.0
        if ROLE_MAIN in roles or ROLE_BREAKFAST in roles:
            struct += 0.4
        if ROLE_SIDE in roles:
            struct += 0.3
        if ROLE_DRINK in roles:
            struct += 0.3
        # 降级模式（无主食可装）时，不因缺主体而惩罚
        if self._light_mode:
            struct = max(struct, 0.6)

        W = profile
        total = (
            s_kcal * 3.0
            + s_protein * W["protein_w"] * 2.0
            + s_fat * W["fat_penalty"] * 1.5
            + s_sodium * 0.5
            + struct * 1.0
            + W["carb_w"] * 0.3
        )

        # 6) 脂肪硬上限：减脂/轻食需真正压制脂肪，超限直接重罚
        # 这是保证"目标真能改变结果"的关键约束（仅靠权重会因基准项过大而失效）
        cap = W.get("fat_cap")
        if cap is not None and fat_ratio > cap:
            total -= (fat_ratio - cap) * 25.0

        detail = {"kcal": k, "protein": p, "fat": f, "carb": c, "sodium": na,
                  "fat_ratio": round(fat_ratio, 3),
                  "s_kcal": round(s_kcal, 3), "s_protein": round(s_protein, 3),
                  "s_fat": round(s_fat, 3), "s_sodium": round(s_sodium, 3),
                  "struct": round(struct, 2)}
        return total, detail

    # ---------- 对外主接口 ----------
    def recommend(self, budget=500, profile_name="均衡", top_n=5,
                  want_drink=True, want_dessert=False, allow_breakfast=True,
                  max_combos=4000, seed=42):
        """
        推荐套餐。
        返回 dict: {'budget','profile','count','results':[{...}]}
        """
        if profile_name not in PROFILES:
            profile_name = "均衡"
        profile = PROFILES[profile_name]
        self._light_mode = False

        combos = self._build_candidates(
            budget, profile, want_drink, want_dessert, allow_breakfast)

        # 降级：预算过低以致装不下任何正餐主体（最轻主食 246 kcal）时，
        # 改为推荐「轻食单品组合」——从全量单品里挑最贴近预算的组合，
        # 并在结果中标记 mode='light'，避免直接返回空导致用户无解。
        if not combos:
            combos = self._build_light(budget, profile, want_drink, want_dessert)
            mode = "light"
            self._light_mode = True
        else:
            mode = "full"

        # 组合过多时随机采样，保证响应速度（可复现：固定 seed）
        if len(combos) > max_combos:
            rnd = random.Random(seed)
            combos = rnd.sample(combos, max_combos)

        scored = []
        for cmb in combos:
            score, detail = self._score(cmb, budget, profile)
            scored.append((score, cmb, detail))
        scored.sort(key=lambda x: x[0], reverse=True)

        # 去重：组合内餐品名集合相同视为重复
        # 多样性约束：相邻推荐的主餐（主食）不得重复，否则方案看起来大同小异
        results = []
        seen = set()
        used_mains = set()
        for score, cmb, detail in scored:
            key = tuple(sorted(x["name"] for x in cmb))
            if key in seen:
                continue
            main_names = tuple(sorted(x["name"] for x in cmb
                                      if x["category"] in (ROLE_MAIN, ROLE_BREAKFAST)))
            # 第一轮：主餐不重复
            if main_names in used_mains:
                continue
            seen.add(key)
            used_mains.add(main_names)
            results.append({
                "score": round(score, 3),
                "items": [{"name": x["name"], "kcal": x["kcal"],
                           "category": x["category"], "protein": x["protein"],
                           "fat": x["fat"], "carb": x["carb"], "sodium": x["sodium"]}
                          for x in cmb],
                "summary": detail,
            })
            if len(results) >= top_n:
                break

        # 兜底：若因多样性约束凑不满 top_n，放宽限制补足
        if len(results) < top_n:
            for score, cmb, detail in scored:
                key = tuple(sorted(x["name"] for x in cmb))
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "score": round(score, 3),
                    "items": [{"name": x["name"], "kcal": x["kcal"],
                               "category": x["category"], "protein": x["protein"],
                               "fat": x["fat"], "carb": x["carb"], "sodium": x["sodium"]}
                              for x in cmb],
                    "summary": detail,
                })
                if len(results) >= top_n:
                    break

        return {
            "budget": budget,
            "profile": profile_name,
            "mode": mode,          # full=含正餐主体 / light=轻食单品降级
            "candidate_count": len(combos),
            "count": len(results),
            "results": results,
        }

    def stats(self):
        from collections import Counter
        cats = Counter(i["category"] for i in self.items)
        return {
            "total": len(self.items),
            "fetched_at": self.fetched_at,
            "by_category": dict(cats),
        }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    p = MealPlanner()
    print("数据集:", p.stats())
    r = p.recommend(budget=500, profile_name="均衡", top_n=3)
    print("\n候选组合数:", r["candidate_count"])
    for i, res in enumerate(r["results"], 1):
        print("\n--- 推荐 %d (score=%.2f) ---" % (i, res["score"]))
        for it in res["items"]:
            print("   %-16s %4d kcal" % (it["name"], it["kcal"]))
        s = res["summary"]
        print("   合计 %d kcal | 蛋白%d 脂肪%d 碳水%d 钠%d"
              % (s["kcal"], s["protein"], s["fat"], s["carb"], s["sodium"]))
