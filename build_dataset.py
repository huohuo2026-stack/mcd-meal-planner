# -*- coding: utf-8 -*-
"""
构建本地营养数据集。

从 MCP 拉取 160 条营养数据 -> 清洗 -> 输出 data/nutrition.json
同时生成分类标注（饮品/主食/小食/甜点/配餐），供推荐引擎做结构约束。

用法：
    python build_dataset.py            # 联网拉取
    python build_dataset.py --offline  # 从 probe/nutrition_raw.json 离线重建
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUT_FILE = os.path.join(DATA_DIR, "nutrition.json")

# 分类关键词表 —— 用于给 160 个单品打结构标签
# 顺序即优先级：越靠前的规则先匹配。饮品/甜点优先于主食，避免"麦旋风"被误判。
CATEGORY_RULES = [
    # ---- 饮品：咖啡 / 奶类 / 冰品饮品 / 汽水 / 茶 / 果汁 ----
    ("饮品", ["可乐", "雪碧", "芬达", "怡泉", "苏打", "雪冰", "奶铁", "燕麦奶", "牛奶",
             "豆浆", "奶昔", "玛奇朵", "美式", "拿铁", "摩卡", "卡布", "浓缩", "鲜萃",
             "咖啡", "红茶", "伯爵", "柠檬茶", "橙汁", "果汁", "美汁源", "纯悦",
             "矿泉水", "柠檬水", "热朱古力", "朱古力饮", "茶", "橙橙", "爆珠",
             "奶冻", "阳光橙", "乐", "水", "黑巧"]),
    # ---- 甜点：冰淇淋 / 派 / 蛋糕类 ----
    ("甜点", ["冰淇淋", "新地", "麦旋风", "圆筒", "麦旋酷", "派", "蛋卷", "圣代",
             "拉明顿", "布朗尼", "马卡龙", "蛋糕", "可颂", "甜甜圈"]),
    # ---- 早餐：麦满分 / 粥 / 油条 / 热香饼 ----
    ("早餐", ["麦满分", "热香饼", "薯饼", "粥", "油条", "早餐", "图林根"]),
    # ---- 小食：薯条 / 鸡块 / 鸡翅 / 沙拉 / 配菜 ----
    ("小食", ["薯条", "麦乐鸡", "鸡翅", "鸡块", "趣鸡球", "脆汁鸡", "沙拉", "玉米杯",
             "苹果", "洋葱圈", "摇摇", "鸡排", "鸡腿", "鸡柳", "鸡米花", "支撑",
             "V翅", "香肠", "脆笋"]),
    # ---- 主食：汉堡 / 卷 / 饭 ----
    ("主食", ["麦香鸡", "麦香鱼", "巨无霸", "汉堡", "堡", "卷", "饭", "面", "三明治",
             "帕尼尼", "披萨", "托盘", "双翅", "牛气", "果然多肉", "薯鱼", "蜜汁快乐"]),
]


def to_int(v, default=0):
    """安全转 int，处理 ''、'null'、None。"""
    if v is None:
        return default
    s = str(v).strip()
    if s == "" or s.lower() == "null":
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def classify(name):
    """给餐品打结构标签。返回 category 字符串。"""
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw in name:
                return cat
    return "其他"


def normalize(row):
    """把紧凑格式的字符串字段转成规整记录。"""
    name = (row.get("productName") or "").strip()
    desc = (row.get("nutritionDescription") or "").strip()
    if desc.lower() == "null":
        desc = ""
    return {
        "name": name,
        "desc": desc,
        "kcal": to_int(row.get("energyKcal")),
        "kj": to_int(row.get("energyKj")),
        "protein": to_int(row.get("protein")),      # 克
        "fat": to_int(row.get("fat")),              # 克
        "carb": to_int(row.get("carbohydrate")),    # 克
        "sodium": to_int(row.get("sodium")),        # 毫克
        "calcium": to_int(row.get("calcium")),      # 毫克
        "category": classify(name),
    }


def parse_toon(raw):
    lines = raw.split("\n")
    m = re.match(r"\s*\[(\d+)\]\{(.+?)\}\s*:?", lines[0])
    if not m:
        raise SystemExit("紧凑格式头部无法解析: %s" % lines[0][:200])
    cols = [c.strip() for c in m.group(2).split(",")]
    rows = []
    for ln in lines[1:]:
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(",")
        if len(parts) < len(cols):
            continue
        rows.append(dict(zip(cols, parts[:len(cols)])))
    return rows


def load_offline():
    """从 probe/nutrition_raw.json 离线重建（不联网）。"""
    raw_file = os.path.join(HERE, "..", "probe", "nutrition_raw.json")
    with open(raw_file, encoding="utf-8") as f:
        d = json.load(f)
    txt = d["result"]["content"][0]["text"]
    mm = re.search(r'\{\s*"success".*\}', txt, re.S)
    obj = json.loads(mm.group(0))
    return parse_toon(obj["data"]), obj.get("datetime", "")


def load_online():
    from mcd_client import fetch_nutrition
    rows, meta = fetch_nutrition()
    return rows, meta.get("datetime", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="从已存 probe 数据离线重建")
    args = ap.parse_args()

    if args.offline:
        raw_rows, dt = load_offline()
        src = "offline(probe/nutrition_raw.json)"
    else:
        raw_rows, dt = load_online()
        src = "online(mcp.mcd.cn)"

    items = [normalize(r) for r in raw_rows if (r.get("productName") or "").strip()]

    # 统计
    from collections import Counter
    cats = Counter(i["category"] for i in items)
    kcal = [i["kcal"] for i in items]

    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        "source": src,
        "fetched_at": dt,
        "count": len(items),
        "schema": ["name", "desc", "kcal", "kj", "protein", "fat", "carb",
                   "sodium", "calcium", "category"],
        "items": items,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("数据来源:", src)
    print("接口时间:", dt)
    print("写入:", OUT_FILE)
    print("条数:", len(items))
    print("分类分布:", dict(cats))
    print("热量 min/max:", min(kcal), "/", max(kcal))
    print("\n前 5 条样例:")
    for i in items[:5]:
        print("  %-14s %4d kcal [%s] 蛋白%d 脂肪%d 碳水%d" %
              (i["name"], i["kcal"], i["category"], i["protein"], i["fat"], i["carb"]))


if __name__ == "__main__":
    main()
