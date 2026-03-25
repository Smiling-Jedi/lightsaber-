# CHANGELOG

回滚指南：`git checkout <tag>` 或 `git reset --hard <commit>`

---

## v1.4.0 · 2026-03-25 · 首页重构 + 信号缓存优化

**首页布局重构**
- 简化头部：三列市场摘要卡片（港股/美股/A股），显示总资金、股票仓位%、现金仓位%
- Tab页市场详情：每个市场顶部显示该市场汇总（股票持仓、现金余额、总资金、持股数、盈亏）
- 信号优先排序：有交易信号的股票优先展示（BUY > SELL > WATCH > HOLD），同信号类型按仓位占比排序
- 修复现金仓位计算：纳入基金账户（HK_FUND、USD_FUND）

**信号缓存优化**
- 批量缓存机制：`get_portfolio_cache()` / `set_portfolio_cache()` 批量读写
- 性能提升：冷缓存 119s → 13.4s（8.9倍），热缓存 4.5s → 85ms（50倍）
- 缓存策略：开盘中15分钟/收盘后2小时
- 文件缓存持久化：`data/signal_cache/*.pkl`

**技术改进**
- 提取 `_generate_signal_internal()` 核心方法，避免单件缓存重复代码
- 修复 `signal_cache_service.py` 循环导入问题（使用 `TYPE_CHECKING` + 前向引用）
- JavaScript 修复：`updateNews()` 函数缺失导致 tab 切换失效

---

## v1.3.2 · 2026-03-24 · Bug修复

**信号区显示修复**
- A股占位提示：未配置信号分类的股票显示「🔧 信号配置中」
- JS缓存问题：添加版本标记强制刷新，修复港美股信号不显示问题
- 字符串替换Bug：`.replace('_', ':')` 改为 `.replace(/_/g, ':')` 全局替换

**调试增强**
- 添加 `[Version]` `[Init]` `[Signals]` `[Placeholder]` 等日志
- API响应状态可视化：页面先显示「正在计算信号...」，返回后更新

---

## v1.3.1 · 2026-03-24 · 持仓体检报告系统

**分析服务增强**
- 新增 `generate_health_check_report()` 8大模块分析：
  - 组合概览（健康度评分/总资产/现金占比/集中度/预期收益）
  - 持仓结构（市场分布/板块分布）
  - 风险警告（集中度风险/波段被套检测）
  - TOP5持仓明细（含波段状态）
  - 行动计划（P0立即/P1条件触发/P2监控）
  - 纪律检查（止损/加仓/集中度违规检测）
- 健康度评分算法（0-100分）：基于现金占比、集中度、预期收益加权扣分

**前端页面更新**
- `dashboard.html` 完全重写为持仓体检报告页面
- Chart.js 环形图展示健康度评分（按分数红/黄/绿自动变色）
- 红绿灯状态指示系统（健康/关注/警告三级）
- 响应式布局，支持移动端浏览

---

## v1.3.0 · 2026-03-24 · B+D方案（原力模块增强）

**信号层增强**
- ATR动态止损：2×ATR(14日)与固定止损取更保守者
- 多模型仓位：KELLY_HALF（半Kelly）/ FIXED_RISK（固定风险10k/2ATR）/ VOLATILITY_ADJUSTED（波动率调整）
- EV优先级排序：权重 EV×40% + Kelly×30% + 信心×20% + 市场×10%
- TradeInstruction数据结构：预留条件表达式字段（entry_condition, stop_condition等）

**分批建仓**
- 第一批50%信号日执行，第二批50%触发条件：回调≥3% 或 3天后 或 价格≥第一批价格
- SimPosition新增字段：batch_status / first_batch_shares / first_batch_price / first_batch_date / second_batch_pending
- 数据库迁移脚本：`alembic/versions/20260324_add_batch_position_fields.py`

**前端展示更新**
- positions.html 信号卡：显示止损类型（ATR/固定）、仓位模型标签、优先级得分
- detail.html 模拟持仓卡：显示分批建仓状态（第一批/已完成）及待建仓股数

---

## v1.2.1 · 2026-03-22 · `b1c1c3f`

**Bug 修复（深度检查）**
- Bug#002 `news_service.py`: `case()` 改为 SQLAlchemy 2.0 tuple 形式，修复 `get_top_news` 运行时报错
- Bug#003 `futu_sync_service.py`: 富途同步跳过负成本 `avg_cost` 覆盖，保护建滔/RKLB 手动写入的负值
- Bug#004 `api_router.py`: compare 接口负成本持仓 `pnl_pct` 改用市值为分母，与 `calculate_profit_pct` 一致
- Bug#005 `position_service.py`: 负成本持仓 `_generate_advice` 直接返回 HOLD，避免 profit_pct 虚高触发 SELL 建议

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
