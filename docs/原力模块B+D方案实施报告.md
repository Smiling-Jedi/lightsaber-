# 原力模块 B+D 渐进方案实施报告

**日期**: 2026-03-24
**实施内容**: 5项功能全部完成

---

## 一、实施清单

| 功能 | 状态 | 关键文件 | 说明 |
|------|------|----------|------|
| 1. ATR动态止损 | ✅ | `signal_service.py:186-192` | 2×ATR(14日)计算止损位，与固定止损取更保守者 |
| 2. 分批建仓 | ✅ | `signal_log_service.py:183-310` | 第一批50%+第二批50%(回调3%或3天后触发) |
| 3. 多模型仓位 | ✅ | `signal_service.py:818-860` | 支持KELLY_HALF/FIXED_RISK/VOLATILITY_ADJUSTED |
| 4. EV排序 | ✅ | `signal_service.py:276-316` | BUY信号优先，权重:EV40%+Kelly30%+信心20%+市场10% |
| 5. 扩展接口 | ✅ | `signal_service.py:82-110` | TradeInstruction数据结构，预留表达式条件字段 |

---

## 二、核心代码变更

### 2.1 ATR动态止损
```python
atr14 = snap.get("atr14", 0)
close_price = snap.get("close", 0)
if atr14 > 0 and close_price > 0:
    atr_stop_pct = -round(atr14 * 2 / close_price * 100, 1)
    stop_pct = min(stop_pct, atr_stop_pct)  # 取更保守的止损
```

### 2.2 分批建仓逻辑
```python
# 第一批：信号日买入50%
first_batch_shares = max(int(total_shares * 0.5), 1)
batch_status = "FIRST_FILLED"

# 第二批触发条件：回调>=3% 或 已过3天 或 价格>=第一批价格
should_fill = (pullback_pct >= 3) or (days_elapsed >= 3) or (entry_price >= first_price)
```

### 2.3 多模型仓位计算
- **KELLY_HALF**: `base_fund × kelly_pct` (默认)
- **FIXED_RISK**: `10000 / (2×ATR)` 股数
- **VOLATILITY_ADJUSTED**: `kelly_pct × (0.05 / ATR%)` 波动率调整

### 2.4 EV排序权重
```
priority_score = EV × 0.4 + Kelly × 0.3 + confidence_score × 0.2 + market_score × 0.1
```

---

## 三、数据库变更

新增字段 (`sim_positions`表):
- `batch_status`: IDLE / FIRST_FILLED / COMPLETED
- `first_batch_shares`: 第一批股数
- `first_batch_price`: 第一批价格
- `first_batch_date`: 第一批日期
- `second_batch_pending`: 待买入第二批股数

---

## 四、配置示例

`config/signal_params.json` 新增字段:
```json
"US:NVDA": {
  "sizing_model": "VOLATILITY_ADJUSTED",
  ...
},
"US:RKLB": {
  "sizing_model": "FIXED_RISK",
  ...
}
```

---

## 五、下一步

方案已完整实现，可开始测试激进方案（表达式条件）。
