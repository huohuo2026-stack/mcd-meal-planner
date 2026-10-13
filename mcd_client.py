# -*- coding: utf-8 -*-
"""
麦当劳 MCP 客户端 —— 纯 stdlib 实现

职责：
1. 与 https://mcp.mcd.cn 做 JSON-RPC 2.0 over Streamable HTTP 通信
2. 封装四类工具：门店查询 / 菜单 / 餐品详情 / 比价 / 营养
3. Token 从环境变量 MCD_TOKEN 读取，不落明文

设计原则：
- 只用标准库（urllib），零第三方依赖，可在任意 Win10/11 + Python 3.8+ 运行
- 任何失败都抛明确异常，由上层决定回退策略

⚠ 已实测的接口陷阱（勿改）：
  1. calculate-price 的 items 元素必须用键 **productCode**，用 code 会
     success=true 但价格全为 0 —— 静默错误，必须断言校验。
  2. 价格单位是**分**（2600 = ¥26.00），需除以 100 展示。
  3. query-meals / calculate-price 的 beCode 在「到店自取(beType=1)」
     场景下不要传，传了报错。
  4. query-nearby-stores 搜门店需 city + keyword 同时给（只给 city 报
     600058「城市名或者关键词不能为空」）。
"""
import json
import os
import re
import ssl
import urllib.error
import urllib.request

MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")
TIMEOUT = 40


class MCPError(Exception):
    """MCP 调用异常，携带可读原因。"""


# ---------------------------------------------------------------- 基础通信

def get_token():
    """从环境变量读取 Token。不使用硬编码，避免明文泄露。"""
    tok = os.environ.get("MCD_TOKEN", "").strip()
    if not tok:
        raise MCPError(
            "未找到 MCD_TOKEN 环境变量。\n"
            "请在 PowerShell 中执行：\n"
            '  [Environment]::SetEnvironmentVariable("MCD_TOKEN","你的Token","User")\n'
            "然后重开终端，或在本进程内先设置该变量。"
        )
    return tok


def _post(payload, token, url=MCP_URL):
    """底层 JSON-RPC POST，返回解析后的 dict。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer " + token,
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        status = e.code
    except urllib.error.URLError as e:
        raise MCPError("网络不可达：%s（请检查网络或代理设置）" % e.reason)

    if status == 401:
        raise MCPError("Token 无效或已失效（401）：%s" % body[:200])
    if status == 429:
        raise MCPError("触发限流（429）：超过 600 次/分钟，请降低频率")
    if status == 403:
        raise MCPError("被拒绝（403）：%s" % body[:200])
    if status != 200:
        raise MCPError("HTTP %s：%s" % (status, body[:200]))

    text = body.strip()
    if text.startswith("event:") or text.startswith("data:"):
        parts = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        text = parts[-1] if parts else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise MCPError("响应非 JSON，原文前 200 字符：%s" % text[:200])


def initialize(token=None):
    """MCP 协议握手，返回 serverInfo。"""
    token = token or get_token()
    resp = _post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mcd-meal-planner", "version": "1.0"},
        },
    }, token)
    if "error" in resp:
        raise MCPError("initialize 失败：%s" % resp["error"])
    return resp.get("result", {}).get("serverInfo", {})


def list_tools(token=None):
    """列出服务端全部工具。"""
    token = token or get_token()
    resp = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, token)
    if "error" in resp:
        raise MCPError("tools/list 失败：%s" % resp["error"])
    return resp.get("result", {}).get("tools", [])


def call_tool(name, arguments, token=None):
    """调用指定工具，返回 result 中的内容。"""
    token = token or get_token()
    resp = _post({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }, token)
    if "error" in resp:
        raise MCPError("tools/call(%s) 失败：%s" % (name, resp["error"]))
    return resp.get("result", {})


# ---------------------------------------------------------------- 响应解析

def _extract_payload(result):
    """
    从工具返回的说明性文本中提取业务 JSON。
    服务端会在 JSON 前后附加 Markdown 说明与 ## 尾注，需精确截取。
    """
    content = result.get("content") or []
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    if not texts:
        raise MCPError("工具返回无 text 内容")
    blob = "\n".join(texts)

    # 优先匹配完整外层大括号（非贪婪 + 尾部边界）
    m = re.search(r'\{\s*"success".*?\}(?=\s*##|\s*$)', blob, re.S)
    if not m:
        m = re.search(r'\{\s*"success".*\}', blob, re.S)
    if not m:
        raise MCPError("未找到业务 JSON，原文前 300 字符：%s" % blob[:300])
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # 退一步：尝试截到最后一个 }
        raw = m.group(0)
        idx = raw.rfind("}")
        return json.loads(raw[:idx + 1])


# ---------------------------------------------------------------- 营养数据

def _parse_toon(raw):
    """
    解析麦当劳紧凑格式(toon)。
    形如：[160]{col1,col2,...}:\\n  值1,值2,...\\n ...
    """
    lines = raw.split("\n")
    m = re.match(r"\s*\[(\d+)\]\{(.+?)\}\s*:?", lines[0])
    if not m:
        raise MCPError("紧凑格式头部无法解析：%s" % lines[0][:200])
    declared = int(m.group(1))
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
    return rows, declared


def fetch_nutrition(token=None):
    """拉取全部餐品营养数据。返回 (rows, meta)。"""
    token = token or get_token()
    result = call_tool("list-nutrition-foods", {}, token=token)
    obj = _extract_payload(result)
    if not obj.get("success"):
        raise MCPError("接口 success=false：%s" % obj.get("message"))
    raw = obj.get("data", "")
    if not raw:
        raise MCPError("data 字段为空")
    rows, declared = _parse_toon(raw)
    meta = {"declared": declared, "parsed": len(rows),
            "datetime": obj.get("datetime", "")}
    return rows, meta


# ---------------------------------------------------------------- 门店 / 菜单

def query_stores(city, keyword, be_type=1, search_type=2, token=None):
    """
    查询门店（到店自取场景）。
    ⚠ city 与 keyword 必须同时提供，只给 city 会报 600058。
    返回 list[dict]，每项含 storeCode / storeName / address / distance。
    """
    token = token or get_token()
    args = {"beType": be_type, "searchType": search_type,
            "city": city, "keyword": keyword}
    result = call_tool("query-nearby-stores", args, token=token)
    obj = _extract_payload(result)
    if not obj.get("success"):
        raise MCPError("门店查询失败 [%s]：%s"
                       % (obj.get("code"), obj.get("message")))
    data = obj.get("data") or []
    if not isinstance(data, list):
        raise MCPError("门店数据格式异常：%s" % type(data).__name__)
    return data


def query_meals(store_code, order_type=1, be_type=1, be_code=None, token=None):
    """
    查询门店可售餐品列表。
    ⚠ 到店自取(beType=1) 不传 beCode。
    返回 dict: {'categories':[...], 'frequent':...}
    """
    token = token or get_token()
    args = {"storeCode": str(store_code),
            "orderType": order_type, "beType": be_type}
    if be_code and be_type != 1:
        args["beCode"] = be_code
    result = call_tool("query-meals", args, token=token)
    obj = _extract_payload(result)
    if not obj.get("success"):
        raise MCPError("菜单查询失败 [%s]：%s"
                       % (obj.get("code"), obj.get("message")))
    return obj.get("data") or {}


def query_meal_detail(store_code, code, order_type=1, be_type=1,
                      be_code=None, token=None):
    """查询餐品/套餐详情（含套餐轮次 rounds）。"""
    token = token or get_token()
    args = {"storeCode": str(store_code), "orderType": order_type,
            "beType": be_type, "code": str(code)}
    if be_code and be_type != 1:
        args["beCode"] = be_code
    result = call_tool("query-meal-detail", args, token=token)
    obj = _extract_payload(result)
    if not obj.get("success"):
        raise MCPError("餐品详情失败 [%s]：%s"
                       % (obj.get("code"), obj.get("message")))
    return obj.get("data") or {}


# ---------------------------------------------------------------- 比价

def calculate_price(store_code, items, order_type=1, be_type=1,
                    be_code=None, token=None, strict=True):
    """
    计算商品价格。

    参数 items: list[dict]，每项形如 {"productCode": "9900003458", "quantity": 1}
    ⚠ 键名必须是 productCode。传 code 会 success=true 但价格全 0（静默错误）。
      strict=True 时对此做断言，发现异常即抛错。

    返回 dict: {
        'price_fen': int, 'price': float(元),
        'original_fen': int, 'original': float,
        'discount_fen': int, 'discount': float,
        'product_list': [...]
    }
    """
    token = token or get_token()

    # 入参防御：把常见错误键名纠正/拦截
    norm = []
    for it in items:
        if "productCode" in it:
            norm.append({"productCode": str(it["productCode"]),
                         "quantity": int(it.get("quantity", 1))})
        elif "code" in it:
            # 用户误用 code：自动纠正为 productCode，并记录风险
            norm.append({"productCode": str(it["code"]),
                         "quantity": int(it.get("quantity", 1))})
        else:
            raise MCPError("items 元素缺少 productCode：%s" % it)

    args = {"storeCode": str(store_code), "orderType": order_type,
            "beType": be_type, "items": norm}
    if be_code and be_type != 1:
        args["beCode"] = be_code

    result = call_tool("calculate-price", args, token=token)
    obj = _extract_payload(result)
    if not obj.get("success"):
        raise MCPError("比价失败 [%s]：%s" % (obj.get("code"), obj.get("message")))
    d = obj.get("data") or {}

    price_fen = int(d.get("price", 0) or 0)
    original_fen = int(d.get("originalPrice", 0) or 0)

    # 静默错误防御：有商品却算出 0 元，说明入参不对
    if strict and norm and price_fen == 0 and original_fen == 0:
        raise MCPError(
            "比价返回 0 元但商品非空（疑似 productCode 无效或门店不可售）：%s"
            % json.dumps(norm, ensure_ascii=False))

    return {
        "price_fen": price_fen,
        "price": price_fen / 100.0,
        "original_fen": original_fen,
        "original": original_fen / 100.0,
        "discount_fen": int(d.get("discount", 0) or 0),
        "discount": int(d.get("discount", 0) or 0) / 100.0,
        "product_list": d.get("productList") or [],
        "raw": d,
    }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    info = initialize()
    print("服务器:", info)
    rows, meta = fetch_nutrition()
    print("营养数据:", meta)
    stores = query_stores("深圳市", "华强北")
    print("门店数:", len(stores), "| 首个:", stores[0]["storeName"] if stores else "-")
