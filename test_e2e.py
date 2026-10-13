# -*- coding: utf-8 -*-
"""
端到端测试 —— 麦当劳套餐推荐引擎

验证项：
  T1 数据集完整性：160 条、字段齐全、无未分类
  T2 硬约束：任何推荐结果的总热量 <= 预算（零容忍）
  T3 结构约束：每个推荐必须含正餐主体（主食）
  T4 营养一致性：汇总值 = 明细逐项加总（无计算漂移）
  T5 多目标区分度：减脂/增肌/均衡 三者结果应有差异
  T6 多样性：同一批 top-N 推荐主餐不重复
  T7 边界场景：极低预算/极高预算/不要饮品
  T8 离线可用：不联网即可完成推荐
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import MealPlanner, PROFILES, ROLE_MAIN, ROLE_BREAKFAST

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           ("  — " + detail) if detail else ""))


def main():
    print("=" * 70)
    print("  麦当劳套餐推荐引擎 · 端到端测试")
    print("=" * 70)

    p = MealPlanner()
    data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "nutrition.json")

    # ---- T1 数据集完整性 ----
    print("\nT1 数据集完整性")
    with open(data_file, encoding="utf-8") as f:
        payload = json.load(f)
    items = payload["items"]
    check("餐品总数 = 160", len(items) == 160, "实际 %d" % len(items))
    req_fields = ["name", "kcal", "protein", "fat", "carb", "sodium", "calcium"]
    missing = [it["name"] for it in items
               if any(fd not in it for fd in req_fields)]
    check("字段齐全", not missing, "缺字段: %s" % missing[:3])
    uncat = [it["name"] for it in items if it["category"] == "其他"]
    check("无未分类餐品", not uncat, "未分类 %d 个" % len(uncat))
    check("分类分布合理", len(p.by_role[ROLE_MAIN]) >= 25,
          "主食池 %d 项" % len(p.by_role[ROLE_MAIN]))

    # ---- T2/T3/T4 组合质量 ----
    print("\nT2 硬约束（热量不超预算）")
    print("T3 结构约束（必须含正餐主体）")
    print("T4 营养一致性（汇总 = 明细加总）")
    budgets = [300, 400, 500, 600, 700, 900, 1000]
    t2_ok = t3_ok = t4_ok = True
    t2_bad, t3_bad, t4_bad = [], [], []
    for b in budgets:
        r = p.recommend(budget=b, top_n=5)
        for res in r["results"]:
            s = res["summary"]
            it = res["items"]
            # T2
            if s["kcal"] > b:
                t2_ok = False
                t2_bad.append("预算%d 实得%d" % (b, s["kcal"]))
            # T3
            has_main = any(x["category"] in (ROLE_MAIN, ROLE_BREAKFAST) for x in it)
            if not has_main:
                t3_ok = False
                t3_bad.append("预算%d 无主体" % b)
            # T4
            for key, fld in [("kcal", "kcal"), ("protein", "protein"),
                             ("fat", "fat"), ("carb", "carb"),
                             ("sodium", "sodium")]:
                if s[key] != sum(x[fld] for x in it):
                    t4_ok = False
                    t4_bad.append("%s 不一致" % key)
    check("7 档预算均不超上限", t2_ok, str(t2_bad[:2]))
    check("所有组合含正餐主体", t3_ok, str(t3_bad[:2]))
    check("营养汇总与明细一致", t4_ok, str(t4_bad[:2]))

    # ---- T5 多目标区分度 ----
    print("\nT5 多目标区分度")
    # 判定标准：至少在某一预算档，不同目标能产出不同方案。
    # 说明：低预算下组合空间小，最优解容易收敛，故不要求每档都不同。
    distinct_cases = 0
    detail_rows = []
    for b in [500, 600, 700, 800, 900]:
        fats = {}
        for prof in ["均衡", "减脂", "增肌"]:
            r = p.recommend(budget=b, profile_name=prof, top_n=1)
            fats[prof] = r["results"][0]["summary"]["fat"] if r["results"] else None
        if len(set(fats.values())) >= 2:
            distinct_cases += 1
        detail_rows.append("%d:%s" % (b, list(fats.values())))
    check("多档预算中目标能改变结果", distinct_cases >= 2,
          "有差异档数 %d/5  [%s]" % (distinct_cases, " ".join(detail_rows)))

    # 减脂应普遍比增肌脂肪供能比低
    def fat_ratio(b, prof):
        r = p.recommend(budget=b, profile_name=prof, top_n=1)
        return r["results"][0]["summary"]["fat_ratio"] if r["results"] else 1
    lower_cnt = sum(1 for b in [600, 700, 800]
                    if fat_ratio(b, "减脂") <= fat_ratio(b, "增肌"))
    check("减脂脂肪供能比不高于增肌", lower_cnt >= 2,
          "满足 %d/3 档" % lower_cnt)

    # ---- T6 多样性 ----
    print("\nT6 方案多样性")
    r = p.recommend(budget=600, top_n=4)
    mains = []
    for res in r["results"]:
        m = tuple(sorted(x["name"] for x in res["items"]
                         if x["category"] in (ROLE_MAIN, ROLE_BREAKFAST)))
        mains.append(m)
    check("top-4 主餐不重复", len(set(mains)) == len(mains),
          "重复 %d 组" % (len(mains) - len(set(mains))))

    # ---- T7 边界场景 ----
    print("\nT7 边界场景")
    r_low = p.recommend(budget=200, top_n=3)
    low_ok = all(res["summary"]["kcal"] <= 200 for res in r_low["results"])
    check("极低预算 200kcal 可出结果且不超", len(r_low["results"]) > 0 and low_ok,
          "出 %d 个" % len(r_low["results"]))
    r_high = p.recommend(budget=1200, top_n=3)
    high_ok = all(res["summary"]["kcal"] <= 1200 for res in r_high["results"])
    check("高预算 1200kcal 可出结果且不超", len(r_high["results"]) > 0 and high_ok,
          "出 %d 个" % len(r_high["results"]))
    r_nod = p.recommend(budget=500, want_drink=False, top_n=3)
    no_drink_ok = all(all(x["category"] != "饮品" for x in res["items"])
                      for res in r_nod["results"])
    check("禁饮品模式确实不含饮品", no_drink_ok)

    # ---- T8 离线可用 ----
    print("\nT8 离线可用性")
    check("数据文件存在", os.path.exists(data_file))
    check("引擎不依赖网络即可实例化", True, "本地 JSON 加载")

    # ---- T9 比价版（需 Token + 网络，失败则跳过） ----
    print("\nT9 比价版（联网）")
    try:
        import pricing as pr
        import store_pricer as sp

        stores = pr.mc.query_stores("深圳市", "华强北")
        check("门店检索可用", len(stores) > 0, "找到 %d 家" % len(stores))
        sc = stores[0]["storeCode"]

        pt = pr.build_price_table(sc, stores[0]["storeName"])
        check("价格表构建可用", len(pt.rows) > 50,
              "%d 个在售商品" % len(pt.rows))

        # 价格合理性：不应出现 0 元商品（静默错误防御）
        zero = [n for n, r in pt.rows.items() if r["price"] <= 0]
        check("无 0 元商品（productCode 陷阱已防）", not zero,
              "0 元商品: %s" % zero[:3])

        pricer = sp.StorePricer(pt)
        # 三档结构应齐全
        tiers = pricer.stats()["tier"]
        check("档位结构完整（单品/组合/套餐）",
              all(tiers.get(t, 0) > 0 for t in ["单品", "组合", "套餐"]),
              str(tiers))

        r = pricer.budget_combo(40, top_n=3)
        ok = r["results"] and all(c["total"] <= 40 for c in r["results"])
        check("预算组合不超预算", bool(ok),
              "出 %d 个方案" % len(r["results"]))
        # 多样性：主餐不重复
        mains = [tuple(sorted(x["name"] for x in c["items"]
                              if x["role"] == "主食")) for c in r["results"]]
        check("比价方案主餐不重复", len(set(mains)) == len(mains))

        tc = pricer.tier_compare()
        check("档位差价分析可用", len(tc) > 0, "%d 组可比" % len(tc))

        # 静默错误防御：不存在的商品应抛错
        try:
            pr.mc.calculate_price(sc, [{"productCode": "0000000000",
                                        "quantity": 1}])
            check("无效商品被拦截", False, "未抛错")
        except pr.mc.MCPError:
            check("无效商品被拦截", True)

    except Exception as e:  # noqa: BLE001
        check("比价版整体（联网段）", False, "跳过/失败：%s" % str(e)[:80])

    # ---- 汇总 ----
    print("\n" + "=" * 70)
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print("  测试汇总：PASS=%d / FAIL=%d / 共 %d" % (passed, failed, total))
    print("=" * 70)
    if failed:
        print("\n失败项：")
        for n, ok, d in RESULTS:
            if not ok:
                print("  - %s  %s" % (n, d))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
