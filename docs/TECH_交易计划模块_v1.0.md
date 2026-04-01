# 交易计划模块技术实现文档 v1.0

> **文档类型**: 技术实现文档  
> **目标读者**: 后端/前端研发、测试  
> **关联文档**: PRD_交易计划模块_v1.0.md  
> **日期**: 2026-04-01

---

## 1. 技术栈确认

| 层级 | 技术 | 版本 |
|------|------|------|
| 后端 | FastAPI | ^0.104 |
| 数据库 | SQLite | 3.x |
| ORM | SQLAlchemy | ^2.0 |
| 前端 | Jinja2 + Bootstrap 5 | - |
| 迁移 | Alembic | 已集成 |

---

## 2. 数据库实现

### 2.1 新建模型文件

**文件**: `app/models/trade_plan.py`

```python
"""
交易计划模型
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Integer, String, Numeric, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class TradePlan(Base):
    """交易计划（买入前填写）"""
    
    __tablename__ = "trade_plans"
    __allow_unmapped__ = True
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True, index=True)
    
    # 基础信息
    symbol = Column(String(20), nullable=False, index=True)
    market = Column(String(10), nullable=False)
    strategy_type = Column(String(20), nullable=False)  # 底仓/波段
    
    # 交易参数
    planned_shares = Column(Integer, nullable=False)
    planned_price = Column(Numeric(15, 4), nullable=False)
    target_price = Column(Numeric(15, 4), nullable=False)
    
    # 止损设置
    stop_loss_method = Column(String(20), nullable=False)  # 固定比例/ATR倍数/支撑位/移动平均线
    stop_loss_param = Column(Numeric(10, 4), nullable=False)
    stop_loss_price = Column(Numeric(15, 4), nullable=False)
    
    # 风险评估（自动计算）
    risk_amount = Column(Numeric(15, 2))
    risk_reward_ratio = Column(Numeric(5, 2))
    
    # 决策依据
    buy_reason = Column(Text, nullable=False)
    note = Column(Text)
    
    # 状态管理
    status = Column(String(20), default="计划中", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    executed_at = Column(DateTime)
    reviewed_at = Column(DateTime)
    review_note = Column(Text)
    review_result = Column(String(20))  # 止盈/止损/调仓/其他
    planned_vs_actual = Column(Text)    # 计划与执行偏差
    lesson_learned = Column(Text)       # 经验教训
    
    # 关联
    trade = relationship("Trade", back_populates="trade_plan")
    
    def __repr__(self) -> str:
        return f"<TradePlan(id={self.id}, symbol={self.symbol}, status={self.status})>"
    
    @property
    def to_dict(self) -> dict:
        """转换为字典，用于API返回"""
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "market": self.market,
            "strategy_type": self.strategy_type,
            "planned_shares": int(self.planned_shares),
            "planned_price": float(self.planned_price),
            "target_price": float(self.target_price),
            "stop_loss_method": self.stop_loss_method,
            "stop_loss_param": float(self.stop_loss_param),
            "stop_loss_price": float(self.stop_loss_price),
            "risk_amount": float(self.risk_amount) if self.risk_amount else None,
            "risk_reward_ratio": float(self.risk_reward_ratio) if self.risk_reward_ratio else None,
            "buy_reason": self.buy_reason,
            "note": self.note,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_note": self.review_note,
            "review_result": self.review_result,
            "planned_vs_actual": self.planned_vs_actual,
            "lesson_learned": self.lesson_learned,
        }
```

### 2.2 更新 Trade 模型

**文件**: `app/models/trade.py`

在 Trade 类中添加关联：

```python
class Trade(Base):
    # ... 原有字段 ...
    
    # 新增关联
    trade_plan = relationship("TradePlan", back_populates="trade", uselist=False)
```

### 2.3 Alembic 迁移脚本

**文件**: `alembic/versions/xxx_add_trade_plans_table.py`

```python
"""add trade_plans table

Revision ID: xxx
Revises: yyy
Create Date: 2026-04-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'xxx'
down_revision = 'yyy'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trade_plans',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=True),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('market', sa.String(10), nullable=False),
        sa.Column('strategy_type', sa.String(20), nullable=False),
        sa.Column('planned_shares', sa.Integer(), nullable=False),
        sa.Column('planned_price', sa.Numeric(15, 4), nullable=False),
        sa.Column('target_price', sa.Numeric(15, 4), nullable=False),
        sa.Column('stop_loss_method', sa.String(20), nullable=False),
        sa.Column('stop_loss_param', sa.Numeric(10, 4), nullable=False),
        sa.Column('stop_loss_price', sa.Numeric(15, 4), nullable=False),
        sa.Column('risk_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('risk_reward_ratio', sa.Numeric(5, 2), nullable=True),
        sa.Column('buy_reason', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='计划中'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('review_result', sa.String(20), nullable=True),
        sa.Column('planned_vs_actual', sa.Text(), nullable=True),
        sa.Column('lesson_learned', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    
    op.create_index('ix_trade_plans_symbol', 'trade_plans', ['symbol'])
    op.create_index('ix_trade_plans_status', 'trade_plans', ['status'])
    op.create_index('ix_trade_plans_created', 'trade_plans', ['created_at'])
    op.create_index('ix_trade_plans_trade_id', 'trade_plans', ['trade_id'])
    
    op.create_foreign_key(
        'fk_trade_plans_trade',
        'trade_plans', 'trades',
        ['trade_id'], ['id']
    )


def downgrade():
    op.drop_table('trade_plans')
```

**执行命令**:
```bash
cd /Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber
alembic revision --autogenerate -m "add trade_plans table"
alembic upgrade head
```

---

## 3. 后端实现

### 3.1 目录结构

```
app/
├── models/
│   ├── __init__.py           # 导出 TradePlan
│   ├── trade.py              # 更新添加 relationship
│   └── trade_plan.py         # 新增
├── services/
│   ├── __init__.py
│   └── trade_plan_service.py # 核心业务逻辑
├── routers/
│   ├── __init__.py
│   └── trade_plan_router.py  # API路由
└── templates/
    ├── trade_plan_list.html  # 列表页
    ├── trade_plan_form.html  # 新建/编辑页
    └── trade_plan_detail.html # 详情页
```

### 3.2 Service 层

**文件**: `app/services/trade_plan_service.py`

```python
"""
交易计划服务
"""
import logging
from decimal import Decimal
from typing import Optional, List, Dict
from datetime import date

from sqlalchemy.orm import Session

from app.models.trade_plan import TradePlan
from app.models.trade import Trade
from app.models.position import Position
from app.models.stock import Stock
from app.services.indicator_service import IndicatorService
from app.services.position_service import PositionService
from app.services.price_service import PriceService

logger = logging.getLogger(__name__)


class TradePlanService:
    """交易计划业务服务"""
    
    # 止损方式配置
    STOP_LOSS_METHODS = {
        "固定比例": {"param_label": "%", "param_type": "percent", "default": 7.0},
        "ATR倍数": {"param_label": "倍", "param_type": "atr", "default": 2.0},
        "支撑位": {"param_label": "价格", "param_type": "price", "default": None},
        "移动平均线": {"param_label": "天数", "param_type": "ma", "default": 20},
    }
    
    # 策略默认配置
    STRATEGY_DEFAULTS = {
        "底仓": {"stop_loss_method": "固定比例", "stop_loss_param": 20.0},
        "波段": {"stop_loss_method": "ATR倍数", "stop_loss_param": 2.0},
    }
    
    def __init__(self, db: Session):
        self.db = db
        self.indicator_svc = IndicatorService()
        self.position_svc = PositionService(db)
        self.price_svc = PriceService(db)
    
    # ─────────────────────────────────────────────────────
    # CRUD 操作
    # ─────────────────────────────────────────────────────
    
    def get_plan(self, plan_id: int) -> Optional[TradePlan]:
        """获取单个计划"""
        return self.db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    
    def list_plans(self, limit: int = 100, offset: int = 0) -> List[TradePlan]:
        """获取计划列表"""
        return (
            self.db.query(TradePlan)
            .order_by(TradePlan.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    
    def create_plan(self, data: dict) -> TradePlan:
        """创建新计划"""
        # 计算止损价
        stop_loss_price = self._calculate_stop_loss_price(
            symbol=data["symbol"],
            planned_price=Decimal(str(data["planned_price"])),
            method=data["stop_loss_method"],
            param=Decimal(str(data["stop_loss_param"])),
        )
        
        # 计算风险指标
        planned_price = Decimal(str(data["planned_price"]))
        planned_shares = int(data["planned_shares"])
        risk_amount = (planned_price - stop_loss_price) * planned_shares
        
        target_price = Decimal(str(data["target_price"]))
        profit = target_price - planned_price
        loss = planned_price - stop_loss_price
        risk_reward_ratio = round(profit / loss, 2) if loss > 0 else Decimal("0")
        
        plan = TradePlan(
            symbol=data["symbol"],
            market=self._extract_market(data["symbol"]),
            strategy_type=data["strategy_type"],
            planned_shares=planned_shares,
            planned_price=planned_price,
            target_price=target_price,
            stop_loss_method=data["stop_loss_method"],
            stop_loss_param=Decimal(str(data["stop_loss_param"])),
            stop_loss_price=stop_loss_price,
            risk_amount=risk_amount,
            risk_reward_ratio=risk_reward_ratio,
            buy_reason=data["buy_reason"],
            note=data.get("note"),
            status="计划中",
        )
        
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan
    
    def update_plan(self, plan_id: int, data: dict) -> Optional[TradePlan]:
        """更新计划（仅计划中状态）"""
        plan = self.get_plan(plan_id)
        if not plan or plan.status != "计划中":
            return None
        
        # 如果修改了关键字段，重新计算
        need_recalculate = any(k in data for k in [
            "planned_price", "target_price", "planned_shares",
            "stop_loss_method", "stop_loss_param"
        ])
        
        if need_recalculate:
            stop_loss_price = self._calculate_stop_loss_price(
                symbol=data.get("symbol", plan.symbol),
                planned_price=Decimal(str(data.get("planned_price", plan.planned_price))),
                method=data.get("stop_loss_method", plan.stop_loss_method),
                param=Decimal(str(data.get("stop_loss_param", plan.stop_loss_param))),
            )
            
            planned_price = Decimal(str(data.get("planned_price", plan.planned_price)))
            planned_shares = int(data.get("planned_shares", plan.planned_shares))
            risk_amount = (planned_price - stop_loss_price) * planned_shares
            
            target_price = Decimal(str(data.get("target_price", plan.target_price)))
            profit = target_price - planned_price
            loss = planned_price - stop_loss_price
            risk_reward_ratio = round(profit / loss, 2) if loss > 0 else Decimal("0")
            
            plan.stop_loss_price = stop_loss_price
            plan.risk_amount = risk_amount
            plan.risk_reward_ratio = risk_reward_ratio
        
        # 更新其他字段
        for key in ["symbol", "strategy_type", "planned_shares", "planned_price",
                    "target_price", "stop_loss_method", "stop_loss_param",
                    "buy_reason", "note"]:
            if key in data:
                setattr(plan, key, data[key])
        
        self.db.commit()
        self.db.refresh(plan)
        return plan
    
    def delete_plan(self, plan_id: int) -> bool:
        """删除计划（仅计划中状态）"""
        plan = self.get_plan(plan_id)
        if not plan or plan.status != "计划中":
            return False
        
        self.db.delete(plan)
        self.db.commit()
        return True
    
    def mark_executed(self, plan_id: int, trade_id: int) -> Optional[TradePlan]:
        """标记计划已执行"""
        plan = self.get_plan(plan_id)
        if not plan:
            return None
        
        plan.trade_id = trade_id
        plan.status = "已执行"
        plan.executed_at = datetime.now()
        
        self.db.commit()
        self.db.refresh(plan)
        return plan
    
    def add_review(self, plan_id: int, data: dict) -> Optional[TradePlan]:
        """添加复盘"""
        plan = self.get_plan(plan_id)
        if not plan or plan.status != "已执行":
            return None
        
        plan.review_result = data.get("review_result")
        plan.review_note = data.get("review_note")
        plan.planned_vs_actual = data.get("planned_vs_actual")
        plan.lesson_learned = data.get("lesson_learned")
        plan.reviewed_at = datetime.now()
        plan.status = "已复盘"
        
        self.db.commit()
        self.db.refresh(plan)
        return plan
    
    # ─────────────────────────────────────────────────────
    # 评估逻辑
    # ─────────────────────────────────────────────────────
    
    def evaluate_plan(self, data: dict) -> Dict:
        """
        评估交易计划
        返回评估结果，不保存到数据库
        """
        # 计算基础指标
        planned_price = Decimal(str(data["planned_price"]))
        target_price = Decimal(str(data["target_price"]))
        planned_shares = int(data["planned_shares"])
        
        stop_loss_price = self._calculate_stop_loss_price(
            symbol=data["symbol"],
            planned_price=planned_price,
            method=data["stop_loss_method"],
            param=Decimal(str(data["stop_loss_param"])),
        )
        
        risk_amount = (planned_price - stop_loss_price) * planned_shares
        profit = target_price - planned_price
        loss = planned_price - stop_loss_price
        risk_reward_ratio = round(profit / loss, 2) if loss > 0 else Decimal("0")
        
        # 获取上下文数据
        portfolio = self.position_svc.get_portfolio_summary()
        total_assets = Decimal(str(portfolio.get("total_value", 0)))
        
        position = self.position_svc.get_position_by_symbol(data["symbol"])
        current_shares = position.total_shares if position else 0
        
        # 计算持仓后占比
        stock = self.db.query(Stock).filter(Stock.symbol == data["symbol"]).first()
        current_price = Decimal(str(stock.current_price)) if stock and stock.current_price else planned_price
        total_shares_after = current_shares + planned_shares
        position_value = total_shares_after * current_price
        position_pct = (position_value / total_assets * 100) if total_assets > 0 else Decimal("0")
        
        # 执行评估检查
        checks = []
        suggestions = []
        
        # 1. 储备金检查
        reserve_check = self._check_reserve(data, risk_amount)
        checks.append(reserve_check)
        if reserve_check["status"] == "fail":
            suggestions.append("暂缓买入，优先减仓补足储备金缺口60万")
        
        # 2. 仓位红线检查
        position_check = self._check_position_limits(data["symbol"], position_pct, portfolio)
        checks.append(position_check)
        
        # 3. 风险金额检查
        risk_check = self._check_risk_amount(risk_amount, total_assets)
        checks.append(risk_check)
        
        # 4. 盈亏比检查
        rr_check = self._check_risk_reward(risk_reward_ratio)
        checks.append(rr_check)
        if rr_check["status"] == "warning":
            suggestions.append("盈亏比一般，需确保胜率足够高")
        
        # 5. 策略匹配检查
        strategy_check = self._check_strategy_match(data)
        checks.append(strategy_check)
        
        # 综合结论
        has_fail = any(c["status"] == "fail" for c in checks)
        has_warning = any(c["status"] == "warning" for c in checks)
        
        if has_fail:
            overall = "不建议"
            overall_code = "red"
        elif has_warning:
            overall = "谨慎执行"
            overall_code = "yellow"
        else:
            overall = "建议执行"
            overall_code = "green"
        
        return {
            "plan": {
                "symbol": data["symbol"],
                "stop_loss_price": float(stop_loss_price),
                "risk_amount": float(risk_amount),
                "risk_reward_ratio": float(risk_reward_ratio),
                "position_pct": float(position_pct),
            },
            "evaluation": {
                "overall": overall,
                "overall_code": overall_code,
                "checks": checks,
                "suggestions": suggestions,
            }
        }
    
    # ─────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────
    
    def _extract_market(self, symbol: str) -> str:
        """从symbol提取市场"""
        return symbol.split(":")[0] if ":" in symbol else "A"
    
    def _calculate_stop_loss_price(self, symbol: str, planned_price: Decimal, 
                                    method: str, param: Decimal) -> Decimal:
        """计算止损价"""
        if method == "固定比例":
            return planned_price * (1 - param / 100)
        
        elif method == "ATR倍数":
            # 获取ATR14
            df = self.indicator_svc.get_history_with_indicators(symbol, days=60)
            if df.empty or "atr14" not in df.columns:
                # ATR缺失，fallback到固定比例7%
                logger.warning(f"{symbol} ATR数据缺失，使用固定比例7%")
                return planned_price * Decimal("0.93")
            
            atr14 = Decimal(str(df["atr14"].iloc[-1]))
            return planned_price - (param * atr14)
        
        elif method == "支撑位":
            return param
        
        elif method == "移动平均线":
            ma_days = int(param)
            df = self.indicator_svc.get_history_with_indicators(symbol, days=60)
            if df.empty or f"ema{ma_days}" not in df.columns:
                # 数据缺失，fallback到固定比例7%
                return planned_price * Decimal("0.93")
            
            ma_value = Decimal(str(df[f"ema{ma_days}"].iloc[-1]))
            return ma_value
        
        return planned_price * Decimal("0.93")  # 默认7%
    
    def _check_reserve(self, data: dict, risk_amount: Decimal) -> Dict:
        """储备金检查"""
        # 获取当前现金（简化处理，实际从cash_balances获取）
        cash_balances = self.db.query(CashBalance).all()
        total_cash = sum(Decimal(str(cb.amount)) for cb in cash_balances)
        
        # 储备金缺口60万
        RESERVE_TARGET = Decimal("3000000")
        reserve_gap = RESERVE_TARGET - total_cash
        
        if reserve_gap > 0 and data.get("strategy_type") == "买入":
            return {
                "item": "储备金检查",
                "status": "fail",
                "message": f"储备金缺口{float(reserve_gap)/10000:.0f}万，当前买入会消耗现金"
            }
        
        return {
            "item": "储备金检查",
            "status": "pass",
            "message": "储备金检查通过"
        }
    
    def _check_position_limits(self, symbol: str, position_pct: Decimal, portfolio: dict) -> Dict:
        """仓位红线检查"""
        messages = []
        status = "pass"
        
        # 单票集中度
        if position_pct > 25:
            status = "fail"
            messages.append(f"单票占比{float(position_pct):.1f}%超过25%红线")
        elif position_pct > 20:
            status = "warning" if status != "fail" else status
            messages.append(f"单票占比{float(position_pct):.1f}%接近上限")
        
        # TOP3集中度（简化计算）
        # 实际实现需要从portfolio获取TOP3占比
        
        if not messages:
            messages.append(f"买入后占比{float(position_pct):.1f}%，未超红线")
        
        return {
            "item": "仓位红线",
            "status": status,
            "message": "；".join(messages)
        }
    
    def _check_risk_amount(self, risk_amount: Decimal, total_assets: Decimal) -> Dict:
        """风险金额检查"""
        if total_assets <= 0:
            return {
                "item": "风险金额",
                "status": "warning",
                "message": "无法获取总资产数据"
            }
        
        risk_pct = risk_amount / total_assets * 100
        
        if risk_pct > 1:
            return {
                "item": "风险金额",
                "status": "warning",
                "message": f"单笔风险{float(risk_pct):.2f}%，建议<1%"
            }
        
        return {
            "item": "风险金额",
            "status": "pass",
            "message": f"单笔风险{float(risk_pct):.2f}%，可控"
        }
    
    def _check_risk_reward(self, rr_ratio: Decimal) -> Dict:
        """盈亏比检查"""
        if rr_ratio < 1:
            return {
                "item": "盈亏比",
                "status": "fail",
                "message": f"1:{float(rr_ratio):.1f}，风险大于收益，不建议"
            }
        elif rr_ratio < 2:
            return {
                "item": "盈亏比",
                "status": "warning",
                "message": f"1:{float(rr_ratio):.1f}，一般，需确保胜率>50%"
            }
        else:
            return {
                "item": "盈亏比",
                "status": "pass",
                "message": f"1:{float(rr_ratio):.1f}，良好"
            }
    
    def _check_strategy_match(self, data: dict) -> Dict:
        """策略匹配检查"""
        strategy = data.get("strategy_type")
        buy_reason = data.get("buy_reason", "")
        
        if strategy == "底仓":
            # 检查是否有基本面关键词
            keywords = ["业绩", "护城河", "竞争力", "行业地位", "现金流", "ROE"]
            has_fundamental = any(kw in buy_reason for kw in keywords)
            
            if not has_fundamental:
                return {
                    "item": "策略匹配",
                    "status": "warning",
                    "message": "底仓建议补充基本面逻辑（业绩/护城河等）"
                }
        
        elif strategy == "波段":
            # 检查是否有技术面关键词
            keywords = ["RSI", "MACD", "均线", "突破", "支撑", "超卖", "金叉"]
            has_technical = any(kw in buy_reason for kw in keywords)
            
            if not has_technical:
                return {
                    "item": "策略匹配",
                    "status": "warning",
                    "message": "波段建议补充技术面信号（RSI/MACD等）"
                }
        
        return {
            "item": "策略匹配",
            "status": "pass",
            "message": "策略匹配良好"
        }
```

### 3.3 Router 层

**文件**: `app/routers/trade_plan_router.py`

```python
"""
交易计划路由
"""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.trade_plan_service import TradePlanService
from app.services.trade_timeline_service import TradeTimelineService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ─────────────────────────────────────────────────────
# 页面路由
# ─────────────────────────────────────────────────────

@router.get("/")
def trade_plan_list(request: Request, db: Session = Depends(get_db)):
    """交易计划列表页（时间线）"""
    service = TradePlanService(db)
    timeline_service = TradeTimelineService(db)
    
    # 获取所有交易记录（带计划状态）
    # 需要从 trades 表获取数据，并关联 trade_plans
    # 这里简化处理，实际应使用 timeline_service
    
    plans = service.list_plans(limit=100)
    
    return templates.TemplateResponse("trade_plan_list.html", {
        "request": request,
        "plans": plans,
        "active_page": "trades"
    })


@router.get("/new")
def trade_plan_new(request: Request, trade_id: int = None, mode: str = "新建", 
                   db: Session = Depends(get_db)):
    """新建交易计划页"""
    service = TradePlanService(db)
    
    # 如果有 trade_id，预填充数据（补录模式）
    default_data = {}
    if trade_id:
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if trade:
            default_data = {
                "symbol": trade.position.stock_symbol if trade.position else "",
                "planned_price": float(trade.price),
                "planned_shares": trade.shares,
            }
    
    return templates.TemplateResponse("trade_plan_form.html", {
        "request": request,
        "mode": mode,
        "default_data": default_data,
        "strategy_defaults": service.STRATEGY_DEFAULTS,
        "stop_loss_methods": service.STOP_LOSS_METHODS,
        "active_page": "trades"
    })


@router.get("/{plan_id}")
def trade_plan_detail(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """计划详情页"""
    service = TradePlanService(db)
    plan = service.get_plan(plan_id)
    
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    return templates.TemplateResponse("trade_plan_detail.html", {
        "request": request,
        "plan": plan,
        "active_page": "trades"
    })


@router.get("/{plan_id}/edit")
def trade_plan_edit(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """编辑计划页"""
    service = TradePlanService(db)
    plan = service.get_plan(plan_id)
    
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    if plan.status != "计划中":
        raise HTTPException(status_code=400, detail="仅计划中的交易可编辑")
    
    return templates.TemplateResponse("trade_plan_form.html", {
        "request": request,
        "mode": "编辑",
        "plan": plan,
        "strategy_defaults": service.STRATEGY_DEFAULTS,
        "stop_loss_methods": service.STOP_LOSS_METHODS,
        "active_page": "trades"
    })


# ─────────────────────────────────────────────────────
# API 路由
# ─────────────────────────────────────────────────────

@router.post("/api/evaluate")
def api_evaluate_plan(
    symbol: str = Form(...),
    strategy_type: str = Form(...),
    planned_price: float = Form(...),
    target_price: float = Form(...),
    planned_shares: int = Form(...),
    stop_loss_method: str = Form(...),
    stop_loss_param: float = Form(...),
    buy_reason: str = Form(...),
    note: str = Form(None),
    db: Session = Depends(get_db)
):
    """评估交易计划（不保存）"""
    service = TradePlanService(db)
    
    data = {
        "symbol": symbol,
        "strategy_type": strategy_type,
        "planned_price": planned_price,
        "target_price": target_price,
        "planned_shares": planned_shares,
        "stop_loss_method": stop_loss_method,
        "stop_loss_param": stop_loss_param,
        "buy_reason": buy_reason,
        "note": note,
    }
    
    result = service.evaluate_plan(data)
    return result


@router.post("/api")
def api_create_plan(
    symbol: str = Form(...),
    strategy_type: str = Form(...),
    planned_price: float = Form(...),
    target_price: float = Form(...),
    planned_shares: int = Form(...),
    stop_loss_method: str = Form(...),
    stop_loss_param: float = Form(...),
    buy_reason: str = Form(...),
    note: str = Form(None),
    db: Session = Depends(get_db)
):
    """创建交易计划"""
    service = TradePlanService(db)
    
    data = {
        "symbol": symbol,
        "strategy_type": strategy_type,
        "planned_price": planned_price,
        "target_price": target_price,
        "planned_shares": planned_shares,
        "stop_loss_method": stop_loss_method,
        "stop_loss_param": stop_loss_param,
        "buy_reason": buy_reason,
        "note": note,
    }
    
    plan = service.create_plan(data)
    return {"success": True, "plan_id": plan.id, "plan": plan.to_dict}


@router.get("/api/{plan_id}")
def api_get_plan(plan_id: int, db: Session = Depends(get_db)):
    """获取计划详情"""
    service = TradePlanService(db)
    plan = service.get_plan(plan_id)
    
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    return {"success": True, "plan": plan.to_dict}


@router.put("/api/{plan_id}")
def api_update_plan(
    plan_id: int,
    symbol: str = Form(None),
    strategy_type: str = Form(None),
    planned_price: float = Form(None),
    target_price: float = Form(None),
    planned_shares: int = Form(None),
    stop_loss_method: str = Form(None),
    stop_loss_param: float = Form(None),
    buy_reason: str = Form(None),
    note: str = Form(None),
    db: Session = Depends(get_db)
):
    """更新交易计划"""
    service = TradePlanService(db)
    
    data = {k: v for k, v in {
        "symbol": symbol,
        "strategy_type": strategy_type,
        "planned_price": planned_price,
        "target_price": target_price,
        "planned_shares": planned_shares,
        "stop_loss_method": stop_loss_method,
        "stop_loss_param": stop_loss_param,
        "buy_reason": buy_reason,
        "note": note,
    }.items() if v is not None}
    
    plan = service.update_plan(plan_id, data)
    if not plan:
        raise HTTPException(status_code=400, detail="计划不存在或状态不允许编辑")
    
    return {"success": True, "plan": plan.to_dict}


@router.delete("/api/{plan_id}")
def api_delete_plan(plan_id: int, db: Session = Depends(get_db)):
    """删除交易计划"""
    service = TradePlanService(db)
    success = service.delete_plan(plan_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="计划不存在或状态不允许删除")
    
    return {"success": True}


@router.post("/api/{plan_id}/mark-executed")
def api_mark_executed(plan_id: int, trade_id: int = Form(...), db: Session = Depends(get_db)):
    """标记计划已执行（关联trade）"""
    service = TradePlanService(db)
    plan = service.mark_executed(plan_id, trade_id)
    
    if not plan:
        raise HTTPException(status_code=400, detail="计划不存在")
    
    return {"success": True, "plan": plan.to_dict}


@router.post("/api/{plan_id}/review")
def api_add_review(
    plan_id: int,
    review_result: str = Form(...),
    review_note: str = Form(None),
    planned_vs_actual: str = Form(None),
    lesson_learned: str = Form(None),
    db: Session = Depends(get_db)
):
    """添加复盘"""
    service = TradePlanService(db)
    
    data = {
        "review_result": review_result,
        "review_note": review_note,
        "planned_vs_actual": planned_vs_actual,
        "lesson_learned": lesson_learned,
    }
    
    plan = service.add_review(plan_id, data)
    if not plan:
        raise HTTPException(status_code=400, detail="计划不存在或状态不允许复盘")
    
    return {"success": True, "plan": plan.to_dict}
```

### 3.4 注册路由

**文件**: `app/main.py`

在原有导入和注册中添加：

```python
from app.routers import position_router, dashboard_router, api_router, investment_router, trade_plan_router

# ...

app.include_router(position_router.router, prefix="/positions", tags=["持仓管理"])
app.include_router(dashboard_router.router, prefix="/dashboard", tags=["仪表盘"])
app.include_router(api_router.router, prefix="/api", tags=["API接口"])
app.include_router(investment_router.router, prefix="/investment", tags=["投资中枢"])
app.include_router(trade_plan_router.router, prefix="/trades", tags=["交易计划"])  # 新增
```

**文件**: `app/models/__init__.py`

```python
from app.models.trade_plan import TradePlan

__all__ = [
    # ... 原有导出 ...
    "TradePlan",
]
```

---

## 4. 前端实现

### 4.1 模板文件清单

| 文件 | 说明 |
|------|------|
| `trade_plan_list.html` | 交易记录列表页（时间线） |
| `trade_plan_form.html` | 新建/编辑计划表单 |
| `trade_plan_detail.html` | 计划详情 + 评估结果 |

### 4.2 导航栏更新

**文件**: `app/templates/base.html`

在 navbar 中添加链接：

```html
<a class="nav-link {% if active_page == 'trades' %}active{% endif %} px-3" href="/trades/">交易记录</a>
```

---

## 5. 与现有系统集成

### 5.1 与 Trades 表关联

**关联时机**: 当富途同步产生新交易记录时，或手动标记计划已执行时

**文件**: `app/services/futu_deal_sync_service.py`（已有）

在同步交易后添加关联逻辑：

```python
def _sync_deals(self):
    # ... 原有同步逻辑 ...
    
    # 新增：尝试关联已有的交易计划
    for new_trade in new_trades:
        plan = self.db.query(TradePlan).filter(
            TradePlan.symbol == new_trade.symbol,
            TradePlan.status == "计划中",
            TradePlan.created_at >= datetime.now() - timedelta(days=7)  # 7天内的计划
        ).first()
        
        if plan:
            plan.trade_id = new_trade.id
            plan.status = "已执行"
            plan.executed_at = datetime.now()
            self.db.commit()
```

### 5.2 与持仓列表整合

在持仓详情页 `/positions/{symbol}` 显示该股票的交易计划：

```python
# 在 position_router.py 的 position_detail 中添加
plans = db.query(TradePlan).filter(
    TradePlan.symbol == canonical,
    TradePlan.status == "计划中"
).all()

return templates.TemplateResponse("detail.html", {
    # ... 原有数据 ...
    "plans": plans,
})
```

---

## 6. 测试方案

### 6.1 单元测试

**文件**: `tests/test_trade_plan_service.py`

```python
import pytest
from decimal import Decimal
from app.services.trade_plan_service import TradePlanService


def test_calculate_stop_loss_price_fixed():
    """测试固定比例止损计算"""
    service = TradePlanService(None)
    price = service._calculate_stop_loss_price(
        symbol="A:300274",
        planned_price=Decimal("155.00"),
        method="固定比例",
        param=Decimal("7.0")
    )
    assert price == Decimal("144.15")  # 155 * 0.93


def test_calculate_risk_reward_ratio():
    """测试盈亏比计算"""
    # 买入价155，止损价144.15，目标价195
    profit = Decimal("195") - Decimal("155")  # 40
    loss = Decimal("155") - Decimal("144.15")  # 10.85
    rr = round(profit / loss, 2)
    assert rr == Decimal("3.69")


def test_evaluate_plan_high_risk():
    """测试高风险评估"""
    # 模拟评估数据
    data = {
        "symbol": "A:300274",
        "strategy_type": "波段",
        "planned_price": 155.00,
        "target_price": 160.00,  # 目标太近，盈亏比低
        "planned_shares": 10000,  # 股数太多
        "stop_loss_method": "固定比例",
        "stop_loss_param": 7.0,
        "buy_reason": "测试",
    }
    # 验证评估结果包含警告
```

### 6.2 接口测试

```bash
# 测试评估接口
curl -X POST http://localhost:8080/trades/api/evaluate \
  -d "symbol=A:300274" \
  -d "strategy_type=波段" \
  -d "planned_price=155.00" \
  -d "target_price=195.00" \
  -d "planned_shares=300" \
  -d "stop_loss_method=固定比例" \
  -d "stop_loss_param=7.0" \
  -d "buy_reason=光伏上游价格企稳"

# 测试创建接口
curl -X POST http://localhost:8080/trades/api \
  -d "symbol=A:300274" \
  -d "strategy_type=波段" \
  -d "planned_price=155.00" \
  -d "target_price=195.00" \
  -d "planned_shares=300" \
  -d "stop_loss_method=固定比例" \
  -d "stop_loss_param=7.0" \
  -d "buy_reason=光伏上游价格企稳"
```

### 6.3 验收测试清单

- [ ] 数据库迁移成功，表结构正确
- [ ] 列表页正确显示交易记录
- [ ] 新建计划表单能正常提交
- [ ] 止损价、盈亏比自动计算正确
- [ ] 评估结果正确显示（储备金/仓位/风险/盈亏比/策略匹配）
- [ ] 计划详情页正确显示所有信息
- [ ] 补录计划功能正常
- [ ] 标记执行后状态正确变更
- [ ] 复盘功能正常
- [ ] 仅计划中状态可编辑删除

---

## 7. 部署步骤

```bash
# 1. 进入项目目录
cd /Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber

# 2. 激活虚拟环境
source venv/bin/activate

# 3. 执行数据库迁移
alembic revision --autogenerate -m "add trade_plans table"
alembic upgrade head

# 4. 重启服务
./stop.sh
./start.sh

# 5. 验证
open http://localhost:8080/trades/
```

---

## 8. 注意事项

### 8.1 ATR数据缺失处理
- 当ATR14数据缺失时，自动fallback到7%固定比例止损
- 前端应给出提示："该股票暂无ATR数据，已使用固定比例7%"

### 8.2 储备金计算
- 当前使用 `CashBalance` 表计算
- 储备金目标300万，缺口60万为当前已知约束

### 8.3 并发处理
- SQLite 不支持高并发写入
- 当前为单用户系统，无需额外处理

---

**文档结束**
