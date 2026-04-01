"""
卖出计划模型
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Integer, String, Numeric, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class SellPlan(Base):
    """卖出计划（止盈/止损/调仓）"""

    __tablename__ = "sell_plans"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    buy_plan_id = Column(Integer, ForeignKey("trade_plans.id"), nullable=True, index=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True, index=True)

    # 基础信息
    symbol = Column(String(20), nullable=False, index=True)
    market = Column(String(10), nullable=False)

    # 卖出参数
    planned_shares = Column(Integer, nullable=False)
    planned_price = Column(Numeric(15, 4))  # 计划卖出价
    original_target_price = Column(Numeric(15, 4))  # 原买入目标价（参考）

    # 卖出触发逻辑
    sell_trigger_method = Column(String(20), nullable=False)  # 固定比例止盈/ATR倍数/压力位/移动平均线/固定比例止损
    sell_trigger_param = Column(Numeric(10, 4), nullable=False)

    # 卖出类型
    sell_type = Column(String(20), default="止盈", nullable=False)  # 止盈/止损/调仓/其他

    # 盈利计算（自动）
    estimated_profit = Column(Numeric(15, 2))  # 预计盈利金额
    estimated_profit_pct = Column(Numeric(5, 2))  # 预计盈利比例
    target_achievement_pct = Column(Numeric(5, 2))  # 原目标达成度

    # 决策依据
    sell_reason = Column(Text, nullable=False)
    note = Column(Text)

    # 状态管理
    status = Column(String(20), default="计划中", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    executed_at = Column(DateTime)
    executed_price = Column(Numeric(15, 4))  # 实际卖出价
    actual_profit = Column(Numeric(15, 2))  # 实际盈利

    # 关联
    buy_plan = relationship("TradePlan", back_populates="sell_plans")
    position = relationship("Position", back_populates="sell_plans")

    def __repr__(self) -> str:
        return f"<SellPlan(id={self.id}, symbol={self.symbol}, status={self.status})>"

    @property
    def to_dict(self) -> dict:
        """转换为字典，用于API返回"""
        return {
            "id": self.id,
            "buy_plan_id": self.buy_plan_id,
            "position_id": self.position_id,
            "symbol": self.symbol,
            "market": self.market,
            "planned_shares": int(self.planned_shares),
            "planned_price": float(self.planned_price) if self.planned_price else None,
            "original_target_price": float(self.original_target_price) if self.original_target_price else None,
            "sell_trigger_method": self.sell_trigger_method,
            "sell_trigger_param": float(self.sell_trigger_param),
            "sell_type": self.sell_type,
            "estimated_profit": float(self.estimated_profit) if self.estimated_profit else None,
            "estimated_profit_pct": float(self.estimated_profit_pct) if self.estimated_profit_pct else None,
            "target_achievement_pct": float(self.target_achievement_pct) if self.target_achievement_pct else None,
            "sell_reason": self.sell_reason,
            "note": self.note,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "executed_price": float(self.executed_price) if self.executed_price else None,
            "actual_profit": float(self.actual_profit) if self.actual_profit else None,
        }
