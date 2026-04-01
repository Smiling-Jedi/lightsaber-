"""
交易记录模型（波段批次管理）
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Integer, String, Numeric, DateTime, Date, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.core.database import Base


class Trade(Base):
    """交易记录（每一笔买入/卖出）"""

    __tablename__ = "trades"
    __allow_unmapped__ = True

    # 主键ID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联持仓
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False, index=True)

    # 交易类型：BUY / SELL
    trade_type = Column(String(10), nullable=False, comment="交易类型")

    # 交易股数
    shares = Column(Integer, nullable=False, comment="交易股数")

    # 交易价格
    price = Column(Numeric(15, 4), nullable=False, comment="交易价格")

    # 交易成本（佣金+税费）
    trading_cost = Column(Numeric(15, 4), default=Decimal("0"), comment="交易成本")

    # 总成本 = 股数 * 价格 + 交易成本
    total_cost = Column(Numeric(15, 4), nullable=False, comment="总成本")

    # 是否为波段交易
    is_swing = Column(Boolean, default=False, comment="是否为波段交易")

    # 波段仓目标卖出价（仅波段交易有效）
    target_sell_price = Column(Numeric(15, 4), nullable=True, comment="目标卖出价")

    # 止损价（可选）
    stop_loss_price = Column(Numeric(15, 4), nullable=True, comment="止损价")

    # 剩余股数（用于跟踪波段仓是否已卖出）
    remaining_shares = Column(Integer, nullable=True, comment="剩余股数")

    # 富途订单ID（用于幂等去重）
    futu_order_id = Column(String(50), nullable=True, unique=True, index=True)

    # 交易日期
    trade_date = Column(Date, nullable=False, default=date.today, comment="交易日期")

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # 关联持仓
    position: "Position" = relationship("Position", back_populates="trades")

    # 关联交易计划
    trade_plan = relationship("TradePlan", back_populates="trade", uselist=False)

    def __repr__(self) -> str:
        return f"<Trade(id={self.id}, type='{self.trade_type}', shares={self.shares}, price={self.price})>"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 自动计算总成本
        if self.total_cost is None and self.shares and self.price:
            cost = Decimal(self.shares) * self.price
            if self.trading_cost:
                cost += self.trading_cost
            self.total_cost = cost
        # 初始化剩余股数
        if self.remaining_shares is None and self.shares:
            self.remaining_shares = self.shares

    @property
    def avg_cost_with_fee(self) -> Decimal:
        """含费平均成本"""
        if self.shares > 0:
            return self.total_cost / self.shares
        return Decimal("0")

    @property
    def is_fully_sold(self) -> bool:
        """是否已全部卖出"""
        return self.remaining_shares is not None and self.remaining_shares == 0

    @property
    def profit_if_sold_at(self, sell_price: Decimal) -> Decimal:
        """如果在指定价格卖出的盈亏"""
        if self.trade_type != "BUY" or not self.remaining_shares:
            return Decimal("0")
        return (sell_price - self.avg_cost_with_fee) * self.remaining_shares

    def sell_shares(self, shares_to_sell: int) -> Decimal:
        """
        卖出部分股份

        Returns:
            实际卖出的股数
        """
        if shares_to_sell <= 0:
            return 0

        actual_sell = min(shares_to_sell, self.remaining_shares or 0)
        self.remaining_shares -= actual_sell
        return actual_sell

    def should_sell_at_price(self, current_price: Decimal) -> str:
        """
        判断当前价格是否应该卖出

        Returns:
            'TARGET_HIT' - 达到目标价
            'STOP_LOSS' - 触及止损
            'HOLD' - 继续持有
        """
        if self.trade_type != "BUY" or self.is_fully_sold:
            return "HOLD"

        # 检查是否达到目标价
        if self.target_sell_price and current_price >= self.target_sell_price:
            return "TARGET_HIT"

        # 检查是否触及止损
        if self.stop_loss_price and current_price <= self.stop_loss_price:
            return "STOP_LOSS"

        return "HOLD"
