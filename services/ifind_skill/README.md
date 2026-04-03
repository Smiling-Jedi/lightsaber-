# 同花顺 iFinD MCP 数据服务

光剑系统已集成同花顺 iFinD 金融数据服务。

## 快速开始

```python
from services.ifind_skill import call

# 查询股票财务数据
result = call("stock", "get_stock_financials", {"query": "阳光电源2025年ROE"})

# 智能选股
result = call("stock", "search_stocks", {"query": "汽车零部件行业市值大于1000亿"})

# 查询宏观经济数据
result = call("edb", "get_edb_data", {"query": "光伏电池产量202301-202506"})

# 查询新闻
result = call("news", "search_news", {
    "query": "人工智能行业动态",
    "time_start": "2025-01-01",
    "time_end": "2026-01-01",
    "size": 5
})
```

## 服务类型

| 服务 | 说明 | 常用工具 |
|------|------|---------|
| `stock` | 股票数据 | `search_stocks`, `get_stock_financials`, `get_stock_performance` |
| `fund` | 基金数据 | `search_funds`, `get_fund_profile`, `get_fund_portfolio` |
| `edb` | 宏观经济/行业 | `search_edb`, `get_edb_data` |
| `news` | 新闻公告 | `search_news`, `search_notice`, `search_trending_news` |

## 返回值格式

```python
{
    "ok": True,              # 是否成功
    "status_code": 200,      # HTTP状态码
    "data": {...},           # 成功时返回数据
    "error": {...},          # 失败时返回错误
    "raw": {...}             # 原始响应
}
```

## 完整文档

详见 `SKILL.md` 文件。
