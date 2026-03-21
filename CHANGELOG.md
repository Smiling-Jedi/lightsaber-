# CHANGELOG

回滚指南：`git checkout <tag>` 或 `git reset --hard <commit>`

---

## v1.2.0 · 2026-03-22 · `8d8784d`

**模拟交易 vs 实盘对比模块**
- 个股详情页 K 线图：日K + MA5/10/20/30/60/200 + 实盘/模拟双套交易打点（同日不重叠）
- 持仓对比卡：实盘 vs 模拟持仓盈亏/市值/均价并排
- 交易统计：胜率/EV/盈亏比/最大连亏，实盘/模拟分栏对比
- 统一时间轴：实盘+模拟合并，色块区分「只有实盘」/「只有模拟」
- 模拟持仓自动跟单：Kelly 仓位入场 + 三种出场（止损/止盈/超时）
- 演示模式完整覆盖：K线/持仓/成交/统计均有合成 fixture 数据

**detail 页 UI 重构**
- 与 positions.html 统一风格：深紫 header band / `#eceaf8` 背景 / 光剑 Logo
- 演示模式黄色提示条
- 涨跌色值统一为 `#d93025` / `#188038`

**新增文件**
- `app/models/sim_position.py` — 模拟持仓表
- `app/services/futu_kline_service.py` — 富途K线 + CSV缓存 + MA
- `app/services/futu_deal_sync_service.py` — 富途历史成交同步
- `app/services/trade_timeline_service.py` — 统一时间轴
- `scripts/migrate_add_simulated.py` / `scripts/init_sim_positions.py`

**Bug 修复（15条）**
- 止损方向用 `abs()` 防呆、模拟SELL入场价None保护、幂等查询区分模拟/真实
- futu_deal 无前缀symbol告警、单条失败savepoint隔离
- K线展示窗口动态6个月、stats颜色方向标志、pct字段与pct_label分离等

---

## v1.0.0 · 2026-03-21 · `890167c`

**演示模式**
- 页面切换开关：演示模式无需密码，切回真实模式需输入密码
- Cookie 持久化（1年），刷新不丢失
- Fixture 数据：港股5只（腾讯/阿里/小米/美团/百济）+ 美股5只（META/MSFT/TSLA/AMZN/NVDA）
- 演示模式下跳过富途同步、跳过 LLM 今日小结调用，直接用 fixture 预设内容
- 操作按钮（更新行情/更新资讯/同步富途）在演示模式下隐藏

**持仓页 UI v16**
- 三列布局：股票信息 / 原力信号+指标表 / 盈利目标
- 蓝紫配色（v15 方案），光剑 Logo
- 红涨绿跌（A股习惯），仓位权重排序
- 汇总区：总资产/今日盈亏/持仓总盈亏 + 港美仓位分布

**原力信号**
- 分类指标体系：large_tech（EMA金叉）/ cyclical（RSI超卖）/ defensive（布林均值）/ biotech（RSI极值）
- 今日小结：claude-haiku 生成，当日相同信号缓存复用
- 回测参考展示：胜率 / EV / Kelly

---

## v1.1.0 · 2026-03-21

**新闻模块**
- yfinance 港美股统一拉取（修复港股 symbol 格式 bug）
- LLM（claude-haiku）批量翻译英文标题 + 重要度打分（HIGH/MEDIUM/LOW）
- 每张持仓卡展示 TOP 5 重要资讯（JS 异步加载），72小时内，按重要度排序
- 定时自动拉取：港股 16:15 HKT / 美股 05:30 HKT（APScheduler）
- 演示模式下显示 fixture 静态新闻，不发 LLM 请求

---

## pre-v1.0.0 历史记录

| commit | 内容 |
|--------|------|
| `48b0b3f` | 原力模块 v1.2：换线区域重设计，今日小结首版 |
| `906db28` | 初始提交：持仓管理、价格更新、富途同步、基础 UI |
