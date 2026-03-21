# CHANGELOG

回滚指南：`git checkout <tag>` 或 `git reset --hard <commit>`

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
- 每张持仓卡展示 TOP 3 重要资讯（JS 异步加载）
- 定时自动拉取：港股 16:15 HKT / 美股 05:30 HKT（APScheduler）
- 演示模式下显示 fixture 静态新闻，不发 LLM 请求

---

## pre-v1.0.0 历史记录

| commit | 内容 |
|--------|------|
| `48b0b3f` | 原力模块 v1.2：换线区域重设计，今日小结首版 |
| `906db28` | 初始提交：持仓管理、价格更新、富途同步、基础 UI |
