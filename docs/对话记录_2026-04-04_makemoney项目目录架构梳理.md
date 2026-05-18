# 对话记录 2026-04-04 · makemoney 项目目录架构梳理

## 背景
Jedi 发起本次对话，目标是梳理优化 makemoney 父项目下多个子项目的目录体系。

---

## 现状诊断

### makemoney 父项目结构问题
- 活跃子项目：lightsaber（主交易持仓）、etf-dashboard（ETF策略面板）
- 待废除：E2-R2
- 根目录散落大量 etf_rotation_*.py 回测脚本（10+个）
- 30+ IDE/AI工具配置目录污染根目录
- 策略脚本分散在三处：makemoney根目录、lightsaber/scripts/quant/、~/学习文档/量化/四只ETF回测/

### 架构评分（梳理前）
- 当前：**3.5/10**
- 方案C轻量重组可达：6/10
- 方案B完全分离可达：7/10
- 方案A Monorepo可达：8.5/10

---

## 关键决策记录

### etf-dashboard 定位
- 刻意与光剑系统解耦，是独立的轻量小应用
- 数据层使用 JSON 文件（非 SQLite），保持灵活性
- **保持原名 etf-dashboard/，不重命名**

### E2-R2
- 准备废除，移入 archive/

### 回测脚本归集策略
- 所有回测脚本统一归入 `etf-dashboard/backtest/`
- 来源一：makemoney 根目录 etf_*.py（10个）→ 移入
- 来源二：lightsaber/scripts/quant/ETF三因子轮动策略/（5个）→ 移入
- 来源三：~/学习文档/量化/四只ETF回测/（12个）→ 复制入，原目录保留
- 重名文件：保留最新版本（覆盖旧的）
- 只迁移 .py 和 .md，图片/数据文件留原地

### lightsaber 内部
- 内部结构问题不大，暂不优化
- 已识别的潜在优化点（待以后处理）：
  - 根目录 lightsaber.db（疑似废弃，data/ 下有正确位置的版本）
  - scripts/test_*.py 应归入 tests/integration/
  - services/ifind_skill/ 应移到 extensions/
  - ENDSCRIPT/PYEND/PYEOF 空文件可删除

---

## 执行结果

### 已完成
1. `E2-R2/` → `archive/E2-R2/`
2. 创建 `etf-dashboard/backtest/` 目录
3. 归集 28 个回测脚本/文档到 `etf-dashboard/backtest/`
4. makemoney 根目录已无散落 .py 脚本

### 最终结构
```
makemoney/
├── lightsaber/          # 核心交易持仓系统（内部不动）
├── etf-dashboard/
│   ├── data/            # JSON数据
│   ├── backtest/        # ← 新增，28个回测脚本/文档
│   └── *.html / update_v2.py
├── archive/
│   └── E2-R2/           # 已归档
├── docs/
├── tools/
└── CLAUDE.md
```

---

## 遗留待办
- [ ] lightsaber 根目录 `lightsaber.db` 确认是否废弃后删除
- [ ] lightsaber/scripts/test_*.py 归入 tests/integration/（低优先级）
- [ ] lightsaber/services/ifind_skill/ 移到 extensions/（低优先级）
