# 需求文档：模拟交易SELL价规则（T+1限价单模式）

**文档版本**：v1.0  
**创建日期**：2026-04-01  
**关联文档**：
- [讨论记录_模拟交易买入价规则_2026-04-01.md](讨论记录_模拟交易买入价规则_2026-04-01.md)
- [方案_T+1限价单_模拟交易买入价确定_v1.md](方案_T+1限价单_模拟交易买入价确定_v1.md)

---

## 1. 背景与问题陈述

### 1.1 现状

模拟交易系统在2026-04-01之前存在逻辑不对称：

- **BUY信号**：已改为T+1限价单模式（条件单挂价，次日判断成交）
- **SELL信号**：仍为"即时成交"模式（信号触发后立即以收盘价卖出持仓）

### 1.2 问题

这种不对称导致：

1. **不公平性**：SELL信号享受了"即时成交"优势，而真实交易中用户无法在收盘价立即卖出
2. **对比失真**：模拟交易与真实交易的执行价格差异过大，失去对比意义
3. **策略纪律破坏**：信号系统应有的"延迟执行、条件触发"机制被绕过

### 1.3 目标

将SELL信号也纳入T+1限价单模式，确保：
- 模拟交易与真实交易的可比性
- 策略执行的一致性（所有信号都遵循"信号日生成条件单，T+1日根据实盘判断成交"）
- 系统设计的对称性

---

## 2. 核心设计原则

### 2.1 纪律优先原则

信号一旦生成，必须严格按照预定义规则执行，不人为干预、不临时调整。无论用户主观判断"明天可能涨还是跌"，系统都按既定规则挂条件单。

### 2.2 实盘复刻原则

模拟交易的成交逻辑必须能够在真实交易中复刻。即：用户看到模拟系统给出的条件单挂价后，可以在T+1日开盘前挂单，实盘结果应与模拟结果一致。

### 2.3 策略一致性原则

同类策略的买卖规则应当对称或逻辑自洽：
- 均值回归策略（cyclical/defensive）：买入等回调，卖出等反弹
- 趋势跟踪策略（large_tech/biotech）：买入防踏空，卖出防套牢

---

## 3. SELL信号触发条件（不变）

SELL信号的触发条件与原力模块保持一致，本需求文档不涉及修改：

| 策略类型 | 触发条件 | 说明 |
|----------|----------|------|
| cyclical | RSI > 70 或 价格触及布林上轨 | 周期股超买止盈 |
| defensive | 价格触及布林上轨 且 RSI > 55 | 防御股触顶卖出 |
| large_tech | EMA死叉 或 MACD由正转负 | 趋势股止损止盈 |
| biotech | RSI > 75 | 高波动股极值离场 |

---

## 4. T+1限价单规则详解

### 4.1 规则总览

| 策略类型 | 代表股票 | limit_price（挂价） | T+1成交判断条件 | 实际卖出价确定 |
|----------|----------|---------------------|-----------------|----------------|
| cyclical | 吉利(00175)、建滔(01888) | T日收盘价 | 最高价 ≥ T日收盘价 | 触发瞬间的市场价（≥收盘价） |
| defensive | 粤海(00270)、联合健康(UNH) | T日收盘价 | 同cyclical | 同cyclical |
| large_tech | 腾讯(00700)、阿里(09988) | T日收盘价 × 99% | 开盘价 ≥ limit_price 则按开盘成交；否则按T+1收盘价成交 | 开盘价或收盘价 |
| biotech | 百济(06160)、RKLB | T日收盘价 × 99% | 同large_tech | 开盘价或收盘价 |

### 4.2 cyclical策略详细规则

**策略逻辑**：均值回归策略，不追趋势。既然今天收盘触发SELL（通常是超买触顶），就挂今天收盘价，明天反弹到这个价就卖，不反弹就继续持有。

**挂价计算**：
```
limit_price = T日收盘价
```

**T+1成交判断**：
```python
if T+1最高价 >= limit_price:
    成交 = True
    实际卖出价 = 触发时的市场价格（条件单触发瞬间的价格，≥limit_price）
else:
    成交 = False
    信号状态 = "CANCELLED"（过期失效）
    持仓状态 = 保持不变（继续持有）
```

**完整示例（吉利汽车）**：

假设T日收盘：
- 收盘价：20.00 HKD
- RSI：74.9（触发SELL信号）
- 生成条件单：limit_price = 20.00

T+1日不同场景：

| 场景 | T+1开盘价 | T+1最高价 | T+1最低价 | 成交结果 | 实际卖出价 | 说明 |
|------|-----------|-----------|-----------|----------|------------|------|
| 反弹上涨 | 19.80 | 20.50 | 19.50 | ✅ 成交 | 20.00~20.50之间某价 | 反弹触发条件单 |
| 低开高走 | 19.50 | 20.30 | 19.20 | ✅ 成交 | 20.00~20.30之间某价 | 盘中反弹触发 |
| 低开低走 | 19.50 | 19.80 | 18.90 | ❌ 未成交 | N/A | 全天未达20.00，信号过期 |
| 高开低走 | 20.30 | 20.50 | 19.00 | ✅ 成交 | 20.30（开盘即触发） | 高开直接满足条件 |

### 4.3 defensive策略详细规则

defensive策略与cyclical策略采用完全相同的规则，不单独区分：
- 挂价 = T日收盘价
- 成交判断 = 最高价 ≥ 收盘价

**为什么不区分"触及上轨"vs"突破上轨"**：
- 简化规则，提高可执行性
- "纪律优先"原则：无论今天如何触发，统一按收盘价挂卖单
- 防止主观判断"突破了就还能涨"干扰系统纪律

### 4.4 large_tech策略详细规则

**策略逻辑**：趋势跟踪股波动较大，若T+1日低开可能卖不掉。给1%缓冲（挂99%），确保成交优先。

**挂价计算**：
```
limit_price = round(T日收盘价 × 0.99, 2)
```

**T+1成交判断**（与cyclical不同）：
```python
if T+1开盘价 >= limit_price:
    成交 = True
    实际卖出价 = T+1开盘价
elif T+1盘中最高价 >= limit_price:
    成交 = True
    实际卖出价 = limit_price（或触发瞬间的价格）
else:
    成交 = True  # 注意：large_tech不同，确保成交
    实际卖出价 = T+1收盘价
```

**关键差异**：large_tech策略在T+1日**无论价格如何都会成交**，只是成交价不同：
- 开盘 ≥ 99% → 按开盘成交（理想情况）
- 开盘 < 99% → 按收盘成交（接受现实离场）

**完整示例（腾讯）**：

假设T日收盘：
- 收盘价：420.00 HKD
- EMA死叉触发SELL信号
- 生成条件单：limit_price = 420 × 0.99 = 415.80

T+1日不同场景：

| 场景 | T+1开盘价 | T+1最高价 | T+1收盘价 | 成交结果 | 实际卖出价 | 说明 |
|------|-----------|-----------|-----------|----------|------------|------|
| 强势开盘 | 418.00 | 425.00 | 422.00 | ✅ 成交 | 418.00 | 开盘≥415.80，按开盘成交 |
| 低开反弹 | 414.00 | 416.00 | 412.00 | ✅ 成交 | 415.80 | 盘中反弹触发 |
| 低开低走 | 414.00 | 415.00 | 410.00 | ✅ 成交 | 410.00 | 全天未触发，收盘强制成交 |
| 极端下跌 | 400.00 | 405.00 | 395.00 | ✅ 成交 | 395.00 | 收盘强制成交，接受损失 |

### 4.5 biotech策略详细规则

biotech策略与large_tech策略采用完全相同的规则：
- 挂价 = T日收盘价 × 99%
- 确保成交（开盘或收盘）

**为什么不给更大缓冲（如95%）**：
- 统一规则简化实现
- 1%缓冲已能覆盖大部分低开情况
- 过度缓冲可能偏离策略本意

---

## 5. 状态流转

### 5.1 SELL信号生命周期

```
T日收盘后
    ↓
生成信号 → 计算limit_price → 写入signal_log表
    ↓
状态: PENDING（待执行）
entered: False（未入场/未执行）
    ↓
T+1日开盘后
    ↓
价格刷新服务获取T+1日OHLC
    ↓
判断成交条件
    ↓
├─ 条件满足 ─→ 更新状态为 HIT_TARGET ─→ 计算收益 ─→ 平仓
│
└─ 条件不满足 ─→ 更新状态为 CANCELLED（cyclical/defensive）或 收盘强制成交（large_tech/biotech）
```

### 5.2 与BUY信号的状态对比

| 信号类型 | 初始状态 | T+1条件满足 | T+1条件不满足 |
|----------|----------|-------------|---------------|
| BUY | PENDING, entered=False | entered=True, status=PENDING（持仓中） | status=CANCELLED（过期） |
| SELL (cyclical/defensive) | PENDING, entered=False（待卖出） | entered=True, status=HIT_TARGET（已卖出） | status=CANCELLED（继续持有） |
| SELL (large_tech/biotech) | PENDING, entered=False（待卖出） | entered=True, status=HIT_TARGET（已卖出） | entered=True, status=HIT_TARGET（收盘强制卖出） |

---

## 6. 数据库字段

### 6.1 signal_log表（已有字段）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| symbol | string | 股票代码 |
| action | enum | BUY/SELL/WATCH/HOLD |
| entry_price | float | T日收盘价（作为参考） |
| limit_price | float | 条件单挂价（新增） |
| entered | boolean | 是否已执行（T+1成交后置为True） |
| entered_price | float | 实际成交价格 |
| status | enum | PENDING/HIT_TARGET/HIT_STOP/EXPIRED/CANCELLED |

### 6.2 新增字段需求

本需求文档不涉及新增数据库字段，复用BUY信号已添加的 `limit_price` 字段。

---

## 7. 接口与实现

### 7.1 SignalService._calculate_limit_price（修改）

现有方法只计算BUY的limit_price，需扩展支持SELL：

```python
def _calculate_limit_price(self, close_price: float, category: str, 
                           indicators: dict, action: str) -> float:
    """
    计算条件单挂价
    
    Args:
        close_price: T日收盘价
        category: 策略类型
        indicators: 指标字典
        action: BUY 或 SELL
    """
    if action == "BUY":
        # 现有BUY逻辑
        ...
    elif action == "SELL":
        # 新增SELL逻辑
        if category in ["cyclical", "defensive"]:
            return round(close_price, 2)
        elif category in ["large_tech", "biotech"]:
            return round(close_price * 0.99, 2)
```

### 7.2 SignalLogService.save_signal_simulated（修改）

现有逻辑：
```python
if result.action == "SELL":
    self._sim_sell(result.symbol, log)  # 立即成交
```

修改为：
```python
if result.action == "SELL":
    # SELL信号也改为PENDING，等待T+1成交检查
    logger.info(f"模拟SELL信号待执行: {result.symbol}，条件单挂价={limit_price}")
```

### 7.3 每日价格刷新脚本（新增逻辑）

在现有的T+1 BUY成交检查逻辑旁，增加SELL成交检查：

```python
# 检查待执行的SELL信号
pending_sells = db.query(SignalLog).filter(
    SignalLog.is_simulated == True,
    SignalLog.action == "SELL",
    SignalLog.entered == False,
    SignalLog.status == "PENDING"
).all()

for log in pending_sells:
    ohlc = get_t1_ohlc(log.symbol)  # 获取T+1日OHLC
    if should_execute_sell(log, ohlc):  # 根据策略类型判断
        execute_sell(log, ohlc)
```

---

## 8. 边界情况处理

### 8.1 T+1日停牌

- **处理方式**：信号过期（status=CANCELLED），持仓保持不变
- **原因**：无法判断合理成交价

### 8.2 T+1日大幅跳空低开（large_tech/biotech）

- **场景**：limit_price=400，T+1开盘直接390（低开2.5%）
- **处理方式**：按规则执行，以收盘价成交（即使亏损）
- **原因**：趋势股策略纪律，及时止损

### 8.3 信号重复生成

- **场景**：T日已有SELL信号且为PENDING，T日收盘后又触发SELL
- **处理方式**：幂等检查，同股同日同action不重复生成

### 8.4 无持仓时触发SELL

- **场景**：模拟持仓为0，但信号触发
- **处理方式**：signal_log状态设为CANCELLED，备注"模拟持仓为空"

---

## 9. 实现状态

### 9.1 已完成的任务（2026-04-01）

- [x] SignalService._calculate_limit_price 扩展支持SELL
  - 文件：`app/services/signal_service.py` 第1009行
  - 改动：增加 `action` 参数，支持BUY/SELL不同规则
  
- [x] SignalLogService.save_signal_simulated 修改SELL为PENDING模式
  - 文件：`app/services/signal_log_service.py` 第142行
  - 改动：SELL不再立即执行 `_sim_sell`，改为PENDING状态
  
- [x] 新增 SignalLogService.auto_check_t1_orders 方法
  - 文件：`app/services/signal_log_service.py` 第448行
  - 功能：处理T+1 BUY和SELL条件单成交判断
  
- [x] 每日价格刷新脚本增加T+1条件单检查
  - 文件：`scripts/refresh_prices.py` 第76行
  - 改动：在止损止盈检查前，先执行T+1条件单检查

### 9.2 待完成任务

- [ ] 单元测试：覆盖四类策略的SELL场景
- [ ] 单元测试：边界情况（停牌、跳空、无持仓等）

---

## 10. 相关提交

| 文件路径 | 改动说明 |
|----------|----------|
| `app/services/signal_service.py` | `_calculate_limit_price` 增加action参数，支持SELL规则 |
| `app/services/signal_log_service.py` | `save_signal_simulated` SELL改为PENDING；新增 `auto_check_t1_orders` 方法 |
| `scripts/refresh_prices.py` | 新增T+1条件单检查步骤 |

---

## 11. 版本历史

| 版本 | 日期 | 修改内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-04-01 | 初始版本，确定四类策略SELL规则 | Jedi、Claude |
