# 同花顺 iFinD MCP 快速使用指南

## ⚠️ 重要前提：持仓同步 ≠ 价格更新

| 维度 | 说明 | 数据源 |
|------|------|--------|
| **持仓同步** | 你账户里实际持有的股票/现金 | 港股/美股/基金→富途OpenD；A股→你必须告诉我 |
| **价格更新** | 市场公开的股价/财报/基本面 | 同花顺iFinD（本指南） |

**iFinD只能查询市场公开数据，不能获取你的个人账户！**

---

## 在光剑系统中使用

### 方式1: 直接使用 iFinD 数据源（推荐）

```python
from app.data_sources.ifind_source import iFinDSource

ifind = iFinDSource()

# 获取股票摘要（财务+估值+行情）
result = ifind.get_stock_summary('300274.SZ', '阳光电源')

# 获取财务数据
result = ifind.get_financials('0700.HK', '腾讯控股', ['ROE', '净利润'], years=5)

# 获取估值
result = ifind.get_valuation('AAPL.O', '苹果')

# 获取历史行情
result = ifind.get_historical_price('0700.HK', '腾讯控股', period='5年')

# 获取股东结构
result = ifind.get_shareholders('0700.HK', '腾讯控股')

# 获取风险指标（Beta/夏普/VaR）
result = ifind.get_risk_indicators('AAPL.O', '苹果')

# 智能选股
result = ifind.search_stocks('汽车零部件行业市值大于1000亿')

# 宏观数据
result = ifind.get_macro_data('CPI 202401-202412')
```

### 方式2: 直接使用原始 call 函数

```python
from services.ifind_skill import call

# 查询股票数据
result = call("stock", "get_stock_financials", {
    "query": "阳光电源2025年ROE"
})

# 查询基金数据
result = call("fund", "search_funds", {
    "query": "南方基金的新能源ETF"
})

# 查询宏观数据
result = call("edb", "get_edb_data", {
    "query": "光伏电池产量202301-202506"
})

# 查询新闻
result = call("news", "search_news", {
    "query": "人工智能行业动态",
    "time_start": "2025-01-01",
    "time_end": "2026-01-01",
    "size": 5
})
```

## 返回格式

```python
{
    "success": True/False,
    "code": 1,  # iFinD返回码
    "message": "success",
    "data": {...},  # 实际数据
    "raw": "..."    # 原始响应
}
```

## 代码格式对照

| 市场 | 同花顺格式 | 示例 |
|------|-----------|------|
| A股 | `300274.SZ` | 阳光电源 |
| 港股 | `0700.HK` | 腾讯控股 |
| 美股 | `AAPL.O` | 苹果 |

## 可用工具列表

### 股票服务 (server_type="stock")
- `search_stocks` - 智能选股
- `get_stock_summary` - 股票摘要
- `get_stock_info` - 基本资料
- `get_stock_financials` - 财务数据
- `get_stock_performance` - 历史行情
- `get_stock_shareholders` - 股东结构
- `get_risk_indicators` - 风险指标
- `get_stock_events` - 重大事件
- `get_esg_data` - ESG评级

### 基金服务 (server_type="fund")
- `search_funds` - 基金搜索
- `get_fund_profile` - 基金资料
- `get_fund_market_performance` - 基金业绩
- `get_fund_ownership` - 份额结构
- `get_fund_portfolio` - 持仓明细
- `get_fund_financials` - 财务指标

### 宏观服务 (server_type="edb")
- `search_edb` - 指标搜索
- `get_edb_data` - 指标数据

### 新闻服务 (server_type="news")
- `search_news` - 新闻搜索
- `search_notice` - 公告搜索
- `search_trending_news` - 热点事件

## 故障排除

### 环境变量未设置
```bash
export IFIND_MCP_TOKEN="your_token_here"
```

### Token 获取方式
1. 打开同花顺 iFinD 终端
2. 工具 → 常用工具 → 数据 MCP
3. 开通并复制 Token

## 数据源优先级

详见: `docs/数据源优先级配置.md`

| 数据类型 | 优先级 |
|---------|--------|
| 账户持仓/现金 | 富途OpenD（唯一） |
| 实时股价 | iFinD > 富途 > Tushare/Yahoo |
| 历史行情/财报 | iFinD（首选） |
| 宏观数据 | iFinD EDB（首选） |
