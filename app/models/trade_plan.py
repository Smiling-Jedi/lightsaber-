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
    sell_plans = relationship("SellPlan", back_populates="buy_plan")

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
