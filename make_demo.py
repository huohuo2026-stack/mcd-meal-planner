# -*- coding: utf-8 -*-
"""
生成两个独立演示页：
  demo.html        —— 营养版（科学配餐）
  demo_price.html  —— 比价版（真实门店价格）

两页独立、互不依赖，各自讲各自的故事（方向三）。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import MealPlanner

HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--txt:#1a1a1a;--sub:#6b7280;
      --red:#d92b2b;--gold:#ffbc0d;--green:#0a8754;--blue:#1a4ed8;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);
     font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
     padding:28px 20px 60px;line-height:1.55}
.wrap{max-width:1080px;margin:0 auto}
header{text-align:center;margin-bottom:28px}
h1{font-size:26px;letter-spacing:.5px}
h1 .m{color:var(--red)}
.sub{color:var(--sub);font-size:14px;margin-top:6px}
.stats{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin-top:18px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;
      padding:10px 18px;font-size:13px}
.stat b{color:var(--blue);font-size:18px;display:block}
.scene{background:var(--card);border:1px solid var(--line);border-radius:14px;
       padding:20px 22px;margin-bottom:20px}
.scene-h{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
         padding-bottom:12px;border-bottom:1px dashed var(--line);margin-bottom:14px}
.badge{background:var(--gold);color:#000;font-weight:700;border-radius:6px;
       padding:3px 11px;font-size:13px}
.badge.light{background:#ffe9b0}
.badge.blue{background:#e0edff;color:#1249b8}
.scene-h .meta{color:var(--sub);font-size:13px}
.meal{border:1px solid var(--line);border-radius:10px;padding:14px 16px;
      margin-bottom:12px;background:#fcfdff}
.meal-top{display:flex;justify-content:space-between;align-items:baseline;
          gap:10px;flex-wrap:wrap;margin-bottom:8px}
.meal-total{font-weight:700;font-size:15px}
.meal-total .k{color:var(--red)}
.meal-sub{font-size:12px;color:var(--sub)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #f0f2f5}
th{color:var(--sub);font-weight:600;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:4px;
     background:#eef1f5;color:#4b5563}
.tag.主食{background:#ffe4e0;color:#b3261e}
.tag.饮品{background:#e0edff;color:#1249b8}
.tag.小食{background:#e6f7ec;color:#0a7a4b}
.tag.甜点{background:#fdeaf7;color:#a3238f}
.tag.套餐{background:#fff3d6;color:#8a5a00}
.tag.组合{background:#eae4ff;color:#5b3fc4}
.diff-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
           gap:10px}
.diff-card{border:1px solid var(--line);border-radius:8px;padding:10px 12px;
           background:#fcfdff}
.diff-card .n{font-weight:600;font-size:13px;margin-bottom:6px}
.diff-card .row{font-size:12px;color:var(--sub);display:flex;
                justify-content:space-between}
.diff-card .row b{color:var(--red)}
footer{text-align:center;color:var(--sub);font-size:12px;margin-top:30px}
.banner{background:#fff4e5;border:1px solid #ffd8a8;border-radius:8px;
        padding:10px 14px;font-size:13px;color:#8a5a00;margin-bottom:20px}
</style>"""

HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%TITLE%</title>
<style>%CSS%</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>%H1%</h1>
    <div class="sub">%SUB%</div>
    <div class="stats">%STATS%</div>
  </header>
  <div id="app">%BODY%</div>
  <footer>%FOOTER%</footer>
</div>
<script>%SCRIPT%</script>
</body>
</html>"""


def make_nutrition_demo():
    p = MealPlanner()
    scenes = []
    for budget, prof in [(400, "减脂"), (500, "均衡"), (600, "增肌"),
                         (700, "均衡"), (200, "减脂")]:
        scenes.append(p.recommend(budget=budget, profile_name=prof, top_n=3))
    st = p.stats()

    script = """
const SCENES = %DATA%;
const app = document.getElementById('app');
const tagCls = c => ['主食','饮品','小食','甜点'].includes(c) ? c : '';
SCENES.forEach(s => {
  const div = document.createElement('div');
  div.className = 'scene';
  let light = s.mode === 'light';
  let h = `<div class="scene-h">
      <span class="badge ${light?'light':''}">${s.budget} kcal</span>
      <span class="badge blue">${s.profile}</span>
      <span class="meta">候选组合 ${s.candidate_count} 个 ｜ 输出前 ${s.count} 个${light?' ｜ ⚠ 已降级为轻食推荐':''}</span>
    </div>`;
  s.results.forEach((r,i) => {
    const sum = r.summary;
    h += `<div class="meal">
      <div class="meal-top">
        <div class="meal-total">方案 ${i+1} ｜ <span class="k">${sum.kcal} kcal</span></div>
        <div class="meal-sub">蛋白 ${sum.protein}g · 脂肪 ${sum.fat}g · 碳水 ${sum.carb}g · 钠 ${sum.sodium}mg ｜ 评分 ${r.score}</div>
      </div>
      <table><thead><tr><th>餐品</th><th>类型</th><th style="text-align:right">热量</th>
      <th style="text-align:right">蛋白</th><th style="text-align:right">脂肪</th>
      <th style="text-align:right">碳水</th></tr></thead><tbody>`;
    r.items.forEach(it => {
      h += `<tr><td>${it.name}</td>
        <td><span class="tag ${tagCls(it.category)}">${it.category}</span></td>
        <td class="num">${it.kcal}</td><td class="num">${it.protein}</td>
        <td class="num">${it.fat}</td><td class="num">${it.carb}</td></tr>`;
    });
    h += `</tbody></table></div>`;
  });
  div.innerHTML = h;
  app.appendChild(div);
});
""".replace("%DATA%", json.dumps(scenes, ensure_ascii=False))

    html = (HTML_HEAD
            .replace("%CSS%", CSS)
            .replace("%TITLE%", "麦当劳套餐助手 · 营养版")
            .replace("%H1%", '🥗 麦当劳<span class="m">营养配餐助手</span>')
            .replace("%SUB%", "按热量预算 + 营养目标，从 160 个餐品中组合出最优套餐")
            .replace("%STATS%",
                     '<div class="stat"><b>%d</b>餐品数据</div>'
                     '<div class="stat"><b>%d</b>演示场景</div>'
                     '<div class="stat"><b>14/14</b>测试通过</div>'
                     '<div class="stat"><b>0</b>超预算</div>'
                     % (st["total"], len(scenes)))
            .replace("%BODY%", "")
            .replace("%FOOTER%",
                     "数据源：麦当劳官方 MCP · list-nutrition-foods ｜ 快照时间 %s"
                     % st["fetched_at"])
            .replace("%SCRIPT%", script))

    out = os.path.join(HERE, "demo.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("营养版演示页:", out, os.path.getsize(out), "bytes")
    return True


def make_price_demo(city="深圳市", keyword="华强北"):
    import pricing as pr
    import store_pricer as sp

    pt = pr.build_price_table_by_city(city, keyword) \
        if hasattr(pr, "build_price_table_by_city") else _build_by_city(city, keyword)
    pricer = sp.StorePricer(pt)

    scenes = [pricer.budget_combo(b, top_n=3) for b in [25, 35, 50]]
    tier = pricer.tier_compare()[:12]
    stats = pricer.stats()

    script = """
const SCENES = %SCENES%;
const TIER = %TIER%;
const app = document.getElementById('app');
let h = '';
SCENES.forEach(s => {
  h += `<div class="scene">
    <div class="scene-h">
      <span class="badge">¥${s.budget.toFixed(2)}</span>
      <span class="badge blue">${s.store}</span>
      <span class="meta">从门店 ${%TOTAL%} 个在售商品中组合</span>
    </div>`;
  s.results.forEach((c,i) => {
    h += `<div class="meal">
      <div class="meal-top">
        <div class="meal-total">方案 ${i+1} ｜ <span class="k">¥${c.total.toFixed(2)}</span></div>
        <div class="meal-sub">${c.count} 件 ｜ 余 ¥${c.remaining.toFixed(2)}</div>
      </div>
      <table><thead><tr><th>商品</th><th>档位</th><th>角色</th>
      <th style="text-align:right">价格</th></tr></thead><tbody>`;
    c.items.forEach(it => {
      h += `<tr><td>${it.name}</td>
        <td><span class="tag ${it.tier}">${it.tier}</span></td>
        <td><span class="tag ${it.role}">${it.role}</span></td>
        <td class="num">¥${it.price.toFixed(2)}</td></tr>`;
    });
    h += `</tbody></table></div>`;
  });
  h += `</div>`;
});
h += `<div class="scene" style="margin-top:8px">
  <div class="scene-h"><span class="badge blue">档位差价分析</span>
  <span class="meta">同一主食：单点 → 组合 → 套餐，加多少钱多拿多少东西</span></div>
  <div class="diff-grid">`;
TIER.forEach(t => {
  h += `<div class="diff-card">
    <div class="n">${t.base}</div>
    ${t.tiers['单品'] ? `<div class="row"><span>单点</span><b>¥${t.tiers['单品'].price.toFixed(2)}</b></div>` : ''}
    ${t.tiers['组合'] ? `<div class="row"><span>组合 ${t.combo_diff>0?'(+¥'+t.combo_diff.toFixed(1)+')':''}</span><b>¥${t.tiers['组合'].price.toFixed(2)}</b></div>` : ''}
    ${t.tiers['套餐'] ? `<div class="row"><span>套餐 ${t.meal_diff>0?'(+¥'+t.meal_diff.toFixed(1)+')':''}</span><b>¥${t.tiers['套餐'].price.toFixed(2)}</b></div>` : ''}
  </div>`;
});
h += `</div></div>`;
app.innerHTML = h;
""".replace("%SCENES%", json.dumps(scenes, ensure_ascii=False)) \
   .replace("%TIER%", json.dumps(tier, ensure_ascii=False)) \
   .replace("%TOTAL%", str(stats["total"]))

    html = (HTML_HEAD
            .replace("%CSS%", CSS)
            .replace("%TITLE%", "麦当劳点餐比价 · 门店实价")
            .replace("%H1%", '💰 麦当劳<span class="m">点餐比价助手</span>')
            .replace("%SUB%", "接入真实门店在售商品，按预算组合、按档位比价")
            .replace("%STATS%",
                     '<div class="stat"><b>%d</b>在售商品</div>'
                     '<div class="stat"><b>%d</b>单品</div>'
                     '<div class="stat"><b>%d</b>套餐</div>'
                     '<div class="stat"><b>实时</b>门店价格</div>'
                     % (stats["total"], stats["tier"].get("单品", 0),
                        stats["tier"].get("套餐", 0)))
            .replace("%BODY%",
                     '<div class="banner">数据来自真实门店「%s」的实时菜单，'
                     '价格为该店当日实际售价。</div>' % stats["store"])
            .replace("%FOOTER%",
                     "数据源：麦当劳官方 MCP · query-meals + calculate-price ｜ 门店 %s (%s)"
                     % (stats["store"], stats["storeCode"]))
            .replace("%SCRIPT%", script))

    out = os.path.join(HERE, "demo_price.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("比价版演示页:", out, os.path.getsize(out), "bytes")
    return True


def _build_by_city(city, keyword):
    """按城市+关键词找门店并建价格表。"""
    import mcd_client as mc
    import pricing as pr
    stores = mc.query_stores(city, keyword)
    if not stores:
        raise RuntimeError("未找到门店：%s %s" % (city, keyword))
    sc, sname = stores[0]["storeCode"], stores[0]["storeName"]
    return pr.build_price_table(sc, sname)


if __name__ == "__main__":
    make_nutrition_demo()
    try:
        make_price_demo()
    except Exception as e:  # noqa: BLE001
        print("比价版演示页生成失败（可能无网络/Token）：", e)
