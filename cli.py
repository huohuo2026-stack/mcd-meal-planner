# -*- coding: utf-8 -*-
"""
麦当劳套餐助手 —— 命令行入口

【模式一】营养版（默认）：按热量预算 + 营养目标推荐
    python cli.py 500                       # 500 大卡预算，均衡目标
    python cli.py 500 --profile 减脂          # 减脂向
    python cli.py 700 --profile 增肌 --top 3  # 增肌向
    python cli.py 400 --no-drink             # 不要饮品
    python cli.py --stats                    # 数据集统计
    python cli.py --refresh                  # 联网刷新数据集

【模式二】比价版：按真实门店价格推荐
    python cli.py --store 深圳市 华强北 --budget 40
    python cli.py --store 深圳市 华强北 --budget 30 --tier   # 附档位差价分析
    python cli.py --store-code 1421180 --budget 40
"""
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

from planner import MealPlanner, PROFILES


def render(res, show_detail=True):
    """把一个推荐结果渲染成可读文本。"""
    lines = []
    s = res["summary"]
    head = "【套餐】%d kcal · 蛋白 %dg · 脂肪 %dg · 碳水 %dg · 钠 %dmg" % (
        s["kcal"], s["protein"], s["fat"], s["carb"], s["sodium"])
    lines.append(head)
    lines.append("  匹配度 %.0f/10  |  热量贴合 %.0f%%  |  结构分 %.2f" % (
        min(res["score"] * 1.2, 10.0), s["s_kcal"] * 100, s["struct"]))
    if show_detail:
        lines.append("  明细：")
        for it in res["items"]:
            lines.append("    - %-22s %4d kcal  [%s]" % (
                it["name"], it["kcal"], it["category"]))
    return "\n".join(lines)


def fmt_dashboard(r):
    """营养版渲染。"""
    lines = []
    lines.append("=" * 78)
    mode_tip = ""
    if r.get("mode") == "light":
        mode_tip = "  ⚠ 预算过低，无法容纳正餐主体（最轻主食 246 kcal），已降级为轻食单品推荐"
    lines.append("  预算 %d kcal  |  目标【%s】  |  候选组合 %d 个  |  取前 %d 个"
                 % (r["budget"], r["profile"], r["candidate_count"], r["count"]))
    if mode_tip:
        lines.append(mode_tip)
    lines.append("=" * 78)
    for i, res in enumerate(r["results"], 1):
        lines.append("")
        lines.append(render(res))
    lines.append("")
    lines.append("=" * 78)
    lines.append("  营养对照总表")
    lines.append("  %-4s %-8s %-8s %-8s %-8s %-8s" %
                 ("#", "热量", "蛋白", "脂肪", "碳水", "钠"))
    lines.append("  " + "-" * 52)
    for i, res in enumerate(r["results"], 1):
        s = res["summary"]
        lines.append("  %-4d %-8s %-8s %-8s %-8s %-8s" % (
            i, str(s["kcal"]) + " kcal", str(s["protein"]) + "g",
            str(s["fat"]) + "g", str(s["carb"]) + "g", str(s["sodium"]) + "mg"))
    lines.append("=" * 78)
    return "\n".join(lines)


def fmt_store(r, show_tier=False, pricer=None):
    """比价版渲染。"""
    lines = []
    lines.append("=" * 78)
    lines.append("  🏪 %s (%s)" % (r["store"], r["storeCode"]))
    lines.append("  预算 ¥%.2f  |  从门店真实在售商品中组合" % r["budget"])
    lines.append("=" * 78)
    for i, c in enumerate(r["results"], 1):
        lines.append("")
        lines.append("【方案%d】合计 ¥%.2f ｜ 余 ¥%.2f ｜ %d 件" %
                     (i, c["total"], c["remaining"], c["count"]))
        for it in c["items"]:
            lines.append("    - %-24s ¥%6.2f  [%s/%s]" %
                         (it["name"], it["price"], it["tier"], it["role"]))
    if show_tier and pricer:
        lines.append("")
        lines.append("=" * 78)
        lines.append("  📊 档位差价分析（同一主食：单点 → 组合 → 套餐）")
        lines.append("  %-24s %-10s %-10s" % ("主食", "组合差价", "套餐差价"))
        lines.append("  " + "-" * 52)
        for rec in pricer.tier_compare()[:10]:
            cd = rec.get("combo_diff")
            md = rec.get("meal_diff")
            lines.append("  %-24s %-10s %-10s" % (
                rec["base"][:24],
                ("+¥%.1f" % cd) if cd is not None else "—",
                ("+¥%.1f" % md) if md is not None else "—"))
    lines.append("=" * 78)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="麦当劳套餐助手 —— 营养版 / 比价版")
    ap.add_argument("budget", nargs="?", type=int, default=500,
                    help="营养版：热量预算(kcal)，默认 500")
    # 营养版参数
    ap.add_argument("--profile", default="均衡", choices=list(PROFILES.keys()),
                    help="营养目标画像，默认 均衡")
    ap.add_argument("--top", type=int, default=3, help="返回前 N 个，默认 3")
    ap.add_argument("--no-drink", action="store_true", help="不要饮品")
    ap.add_argument("--dessert", action="store_true", help="允许包含甜点")
    ap.add_argument("--stats", action="store_true", help="显示数据集统计")
    ap.add_argument("--refresh", action="store_true", help="联网刷新数据集")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    # 比价版参数
    ap.add_argument("--store", nargs=2, metavar=("CITY", "KEYWORD"),
                    help="比价版：城市 + 关键词，如 --store 深圳市 华强北")
    ap.add_argument("--store-code", help="比价版：直接指定门店编码")
    ap.add_argument("--price-budget", type=float, default=40.0,
                    help="比价版：价格预算(元)，默认 40")
    ap.add_argument("--tier", action="store_true", help="附档位差价分析")
    ap.add_argument("--no-cache", action="store_true", help="忽略价格缓存")
    args = ap.parse_args()

    # ============ 比价版 ============
    if args.store or args.store_code:
        import pricing as pr
        import store_pricer as sp

        try:
            if args.store_code:
                sc, sname = args.store_code, ""
            else:
                city, kw = args.store
                stores = pr.mc.query_stores(city, kw)
                if not stores:
                    print("未找到门店：%s %s" % (city, kw))
                    return 1
                sc, sname = stores[0]["storeCode"], stores[0]["storeName"]
                print("门店：%s (%s)" % (sname, sc))

            pt = pr.build_price_table(sc, sname, use_cache=not args.no_cache)
            pricer = sp.StorePricer(pt)
            r = pricer.budget_combo(args.price_budget, top_n=args.top)

            if args.json:
                import json
                print(json.dumps(r, ensure_ascii=False, indent=2))
            else:
                print(fmt_store(r, show_tier=args.tier, pricer=pricer))
            return 0
        except Exception as e:  # noqa: BLE001
            print("比价失败：%s" % e)
            print("提示：请确认网络、Token、门店关键词是否正确。")
            return 1

    # ============ 营养版 ============
    if args.refresh:
        import build_dataset
        sys.argv = ["build_dataset.py"]
        build_dataset.main()

    p = MealPlanner()

    if args.stats:
        st = p.stats()
        print("数据集统计")
        print("  餐品总数:", st["total"])
        print("  接口时间:", st["fetched_at"])
        print("  分类分布:", st["by_category"])
        return 0

    r = p.recommend(
        budget=args.budget,
        profile_name=args.profile,
        top_n=args.top,
        want_drink=not args.no_drink,
        want_dessert=args.dessert,
    )

    if args.json:
        import json
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(fmt_dashboard(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
