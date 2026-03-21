"""
持仓记录模型
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class Position(Base):
    """持仓记录（一只股票在一个市场的持仓）"""

    __tablename__ = "positions"
    __allow_unmapped__ = True

    # 主键ID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联股票
    stock_symbol = Column(String(20), ForeignKey("stocks.symbol"), nullable=False, index=True)

    # 总持仓股数（底仓 + 波段仓）
    total_shares = Column(Integer, nullable=False, default=0, comment="总持仓股数")

    # 底仓股数（长期持有）
    base_shares = Column(Integer, nullable=False, default=0, comment="底仓股数")

    # 底仓成本价
    base_cost = Column(Numeric(15, 4), nullable=True, comment="底仓成本价")

    # 加权平均成本（包含波段仓）
    avg_cost = Column(Numeric(15, 4), nullable=True, comment="加权平均成本")

    # 波段仓平均成本（手动维护，富途同步不覆盖）
    swing_cost = Column(Numeric(15, 4), nullable=True, comment="波段仓平均成本")

    # 交易成本（佣金+税费）
    trading_cost = Column(Numeric(15, 4), default=Decimal("0"), comment="交易成本")

    # 市场总资金（用于计算仓位占比）
    market_total_fund = Column(Numeric(20, 4), nullable=False, comment="该市场总资金")

    # 币种（缓存，方便查询）
    currency = Column(String(10), nullable=False, comment="币种")

    # 备注
    notes = Column(String(500), nullable=True, comment="备注")

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # 更新时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 关联股票
    stock: "Stock" = relationship("Stock", back_populates="positions")

    # 关联交易记录（波段批次）
    trades: List["Trade"] = relationship("Trade", back_populates="position", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Position(id={self.id}, stock='{self.stock_symbol}', shares={self.total_shares})>"

    @property
    def swing_shares(self) -> int:
        """波段仓股数 = 总股数 - 底仓"""
        return self.total_shares - self.base_shares

    @property
    def invested_cost(self) -> Decimal:
        """投入成本（不含交易成本）"""
        if self.avg_cost:
            return Decimal(self.total_shares) * self.avg_cost
        return Decimal("0")

    @property
    def total_invested(self) -> Decimal:
        """总投入（含交易成本）"""
        return self.invested_cost + (self.trading_cost or Decimal("0"))

    def calculate_market_value(self, current_price: Decimal) -> Decimal:
        """计算当前市值"""
        return Decimal(self.total_shares) * current_price

    def calculate_profit(self, current_price: Decimal) -> Decimal:
        """计算盈亏金额"""
        return self.calculate_market_value(current_price) - self.invested_cost

    def calculate_profit_pct(self, current_price: Decimal) -> float:
        """计算盈亏百分比"""
        if self.invested_cost > 0:
            return float(self.calculate_profit(current_price) / self.invested_cost * 100)
        return 0.0

    def calculate_position_weight(self, current_price: Decimal) -> float:
        """计算在该市场的仓位占比"""
        if self.market_total_fund and self.market_total_fund > 0:
            market_value = self.calculate_market_value(current_price)
            return float(market_value / self.market_total_fund * 100)
        return 0.0

    def update_avg_cost(self) -> None:
        """根据交易记录重新计算加权平均成本"""
        if not self.trades:
            return

        total_cost = Decimal("0")
        total_shares = 0

        for trade in self.trades:
            if trade.trade_type == "BUY":
                total_cost += trade.total_cost
                total_shares += trade.shares

        if total_shares > 0:
            self.avg_cost = total_cost / total_shares
            self.total_shares = total_shares

    def get_active_swing_trades(self) -> List["Trade"]:
        """获取未平仓的波段交易"""
        return [t for t in self.trades if t.is_swing and t.remaining_shares > 0]

    def get_swing_avg_cost(self) -> Optional[Decimal]:
        """计算波段仓的平均成本"""
        swing_trades = self.get_active_swing_trades()
        if not swing_trades:
            return None

        total_cost = sum(t.total_cost for t in swing_trades)
        total_shares = sum(t.remaining_shares for t in swing_trades)

        if total_shares > 0:
            return total_cost / total_shares
        return None
