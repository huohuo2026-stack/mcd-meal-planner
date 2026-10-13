# -*- coding: utf-8 -*-
"""
构建交互式应用：把真实数据注入模板 -> app.html

输入：
  app_template.html     模板（含 __NUTRI_DATA__ / __STORE_DATA__ 占位）
  data/nutrition.json   营养数据集
  data/price_cache.json 门店价格缓存
输出：
  app.html              单文件交互应用（双击即用，营养版离线可用）
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "app_template.html")
OUT = os.path.join(HERE, "app.html")
NUTRI = os.path.join(HERE, "data", "nutrition.json")
CACHE = os.path.join(HERE, "data", "price_cache.json")


def build():
    with open(TPL, encoding="utf-8") as f:
        html = f.read()
    with open(NUTRI, encoding="utf-8") as f:
        nutri = json.load(f)
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    # 精简营养字段，控制页面体积
    slim = [{
        "n": it["name"], "k": it["kcal"], "p": it["protein"],
        "f": it["fat"], "c": it["carb"], "s": it["sodium"], "g": it["category"],
    } for it in nutri["items"]]

    # 门店数据结构化
    stores = {}
    for code, v in cache.items():
        rows = {}
        for name, r in v.get("rows", {}).items():
            rows[name] = {"price": r["price"], "code": r["code"]}
        stores[code] = {"name": v.get("store_name", ""), "rows": rows}

    html = html.replace("__NUTRI_DATA__", json.dumps(slim, ensure_ascii=False))
    html = html.replace("__STORE_DATA__", json.dumps(stores, ensure_ascii=False))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUT) / 1024
    print("已生成:", OUT)
    print("营养数据: %d 项" % len(slim))
    print("门店数据: %d 家 / %d 条价格"
          % (len(stores), sum(len(s["rows"]) for s in stores.values())))
    print("文件大小: %.1f KB" % size_kb)
    return True


if __name__ == "__main__":
    build()
