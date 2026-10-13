# MCP 集成说明

本文说明「麦当劳套餐助手」实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

---

## 一、MCP Server 信息

| 项 | 值 |
|---|---|
| 服务名称 | 麦当劳中国 MCP Server |
| 端点 | `https://mcp.mcd.cn` |
| 协议 | JSON-RPC 2.0 over **Streamable HTTP** |
| 协议版本 | `2025-06-18` |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| 响应类型 | `Accept: application/json, text/event-stream` |
| 限流 | 600 次 / 分钟 |
| Token 获取 | `https://open.mcd.cn`（手机号验证后免费申请） |

**客户端实现**：`mcd_client.py`，纯 Python 标准库（`urllib` + `json` + `ssl`），**零第三方依赖**。

```python
MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Authorization": "Bearer " + token,
}
```

> ⚠️ Token 从环境变量 `MCD_TOKEN` 读取，**不硬编码、不落明文**（符合参赛声明的信息安全要求）。

### 协议握手

```python
initialize()  # JSON-RPC method: "initialize"，返回 serverInfo
list_tools()  # JSON-RPC method: "tools/list"，返回全部工具清单
call_tool(name, arguments)  # JSON-RPC method: "tools/call"
```

---

## 二、实际使用的 Tool

本项目使用麦当劳 MCP 的 **5 个工具**，覆盖「营养」与「价格」两条链路：

| # | Tool | 入参 | 用途 | 用于哪个模式 |
|---|---|---|---|---|
| 1 | `list-nutrition-foods` | 无 | 拉取全部餐品营养数据（160 项） | 营养版 |
| 2 | `query-nearby-stores` | `city` + `keyword` + `beType` + `searchType` | 检索门店，拿 `storeCode` | 比价版 |
| 3 | `query-meals` | `storeCode` + `orderType` + `beType` | 查询门店在售餐品列表 | 比价版 |
| 4 | `query-meal-detail` | `storeCode` + `code` + … | 查询餐品 / 套餐详情（含套餐轮次） | 比价版 |
| 5 | `calculate-price` | `storeCode` + `items[]` + … | 批量计算价格（含档位差价） | 比价版 |

### 各 Tool 的封装细节

```python
# 1. 营养数据 —— 返回紧凑格式(toon)文本，需专门解析
def fetch_nutrition(token=None):
    result = call_tool("list-nutrition-foods", {}, token=token)
    obj = _extract_payload(result)
    rows, declared = _parse_toon(obj["data"])
    return rows, meta

# 2. 门店检索 —— ⚠ city 与 keyword 必须同时给
def query_stores(city, keyword, be_type=1, search_type=2, token=None):
    args = {"beType": be_type, "searchType": search_type,
            "city": city, "keyword": keyword}
    ...

# 3. 菜单 —— ⚠ 到店自取(beType=1) 不传 beCode
def query_meals(store_code, order_type=1, be_type=1, be_code=None, token=None):
    args = {"storeCode": str(store_code), "orderType": order_type, "beType": be_type}
    if be_code and be_type != 1:
        args["beCode"] = be_code
    ...

# 5. 比价 —— ⚠ items 键名必须是 productCode
def calculate_price(store_code, items, ...):
    norm = [{"productCode": str(it.get("productCode") or it.get("code")),
             "quantity": int(it.get("quantity", 1))} for it in items]
    args = {"storeCode": str(store_code), "orderType": 1,
            "beType": 1, "items": norm}
    ...
```

---

## 三、调用流程

### 流程一 · 营养版（一次拉取，长期离线可用）

```
initialize (握手)
    │
    ▼
list-nutrition-foods  ──►  返回紧凑格式(toon)文本，含 160 条餐品
    │
    ▼
_parse_toon()  ──►  解析为结构化记录
    │                   {name, kcal, protein, fat, carb, sodium, calcium, category}
    ▼
存入 data/nutrition.json  ──►  构建时内嵌进 app.html
    │
    ▼
本地推荐引擎（planner.py / JS）  ──►  枚举 + 多目标评分  ──►  输出方案
```

**关键点**：营养数据**只需拉取一次**，之后完全离线。这让作品在**无 Token、无网络**环境下也能完整演示（评委第一关）。

### 流程二 · 比价版（门店 → 菜单 → 一次批量比价）

```
initialize (握手)
    │
    ▼
query-nearby-stores(city, keyword)  ──►  storeCode
    │
    ▼
query-meals(storeCode)  ──►  该店在售商品清单（code + tags，**不含名称**）
    │
    ▼
calculate-price(storeCode, [全部 code])  ──►  一次批量换回「名称 + 价格」
    │
    ▼
存入 data/price_cache.json  ──►  构建时内嵌进 app.html
    │
    ▼
本地比价引擎（store_pricer.py / JS）  ──►  预算组合 + 档位差价  ──►  输出方案
```

**关键优化**：`calculate-price` 支持**批量**入参，实测一次传入 88 个商品可全部返回。
因此**整店价格表只需 1 次网络调用**，而非 88 次。

---

## 四、业务价值

原子接口单独拎出来都很"碎"，本项目的价值在于**把原子能力编排成用户愿意用的闭环**：

| 层面 | 说明 |
|---|---|
| **从"能查"到"能用"** | `list-nutrition-foods` 只给一张营养表；本项目用算法把它变成"可执行的配餐方案" |
| **从"价格"到"决策"** | `calculate-price` 只给数字；本项目算出"预算内最优组合"和"档位差价" |
| **离线化改造** | 一次拉取 + 内嵌单文件，把**联网前提**变成**零门槛演示**，显著降低体验成本 |
| **成本优化** | 批量比价把 N 次调用压成 1 次，配合 1 小时本地缓存，规避 600 次/分钟限流 |
| **健壮性** | 针对 6 类接口陷阱（含 2 项静默错误）做了显式防御，避免"不报错但结果错" |

---

## 五、健壮性设计：已实测的接口陷阱

排查过程中的关键发现，其中 **2 项属静默错误**（接口返回 `success=true` 但结果错误），
若不防御会直接产出错误结果：

| # | 陷阱 | 后果 | 防御实现 |
|---|---|---|---|
| 1 | `calculate-price` 的 items 元素键名必须是 **`productCode`** | 传 `code` 会 `success=true` 但价格全为 **0** | 入参自动纠正 + `strict` 模式 0 元断言抛错 |
| 2 | 价格单位是**分** | `2600` 实为 ¥26.00 | 统一 `/100` 换算 |
| 3 | `beCode` 在到店自取(`beType=1`)场景**不能传** | 传了报错 | 按 `beType` 条件传参 |
| 4 | `query-nearby-stores` 需 **city + keyword 同时给** | 只给 city 报 600058 | 参数校验 |
| 5 | `query-meals` **不返回餐品名** | 无法直接建名称映射 | 用批量比价换名称 |
| 6 | 两套数据体系**不重合** | 营养库与门店菜单同名率仅 ~49% | 两模式独立，不强行融合 |

### 响应解析：从 Markdown 包裹中提取业务 JSON

服务端会在业务 JSON 前后附加 Markdown 说明与 `##` 尾注，需精确截取：

```python
def _extract_payload(result):
    texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    blob = "\n".join(texts)
    # 优先匹配完整外层大括号（非贪婪 + 尾部边界）
    m = re.search(r'\{\s*"success".*?\}(?=\s*##|\s*$)', blob, re.S)
    ...
```

### 紧凑格式(toon)解析

`list-nutrition-foods` 返回的不是标准 JSON，而是紧凑格式：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,,1288,308,16,16,24,781,213
  ...
```

```python
def _parse_toon(raw):
    m = re.match(r"\s*\[(\d+)\]\{(.+?)\}\s*:?", raw.split("\n")[0])
    declared = int(m.group(1))          # 声明条数，用于校验
    cols = [c.strip() for c in m.group(2).split(",")]
    # 逐行 zip 成 dict
```

---

## 六、配置示例

仅使用环境变量占位符，不含真实凭证：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer ${MCD_MCP_TOKEN}"
      }
    }
  }
}
```

---

## 附：数据落地

| 文件 | 内容 | 来源工具 |
|---|---|---|
| `data/nutrition.json` | 160 条营养数据 | `list-nutrition-foods` |
| `data/price_cache.json` | 88 条门店价格 | `query-meals` + `calculate-price` |

两者均在构建时被 `build_app.py` 内嵌进 `app.html`，实现**单文件、离线可用**。
