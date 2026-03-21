"""
模拟持仓模型

存储模拟交易的持仓快照，独立于真实持仓。
初始化时从真实持仓复制一次，之后随模拟信号自动更新。
"""
from datetime import datetime, date

from sqlalchemy import Column, Integer, String, Float, Date, DateTime

from app.core.database import Base


class SimPosition(Base):
    """模拟持仓（与真实持仓独立存储）"""

    __tablename__ = "sim_positions"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票信息
    symbol   = Column(String(20), nullable=False, unique=True, index=True)
    name     = Column(String(100), nullable=True)
    category = Column(String(20), nullable=True)   # large_tech / cyclical / defensive / biotech
    currency = Column(String(10), nullable=False, default="HKD")

    # 对比起始时间（快照时间，两侧展示相同时间点）
    snapshot_date = Column(Date, nullable=False, default=date.today)

    # 快照时的原始数据（永不更新，作为起跑线参考）
    initial_shares   = Column(Integer, nullable=False, default=0)
    initial_avg_cost = Column(Float, nullable=True)

    # 当前模拟持仓（随信号自动更新）
    shares      = Column(Integer, nullable=False, default=0)
    avg_cost    = Column(Float, nullable=True)
    last_price  = Column(Float, nullable=True)
    market_value = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    def __repr__(self) -> str:
        return f"<SimPosition(symbol='{self.symbol}', shares={self.shares})>"

    def to_dict(self) -> dict:
        return {
            "symbol":        self.symbol,
            "name":          self.name,
            "category":      self.category,
            "currency":      self.currency,
            "snapshot_date": self.snapshot_date.isoformat() if self.snapshot_date else None,
            "shares":        self.shares,
            "avg_cost":      self.avg_cost,
            "last_price":    self.last_price,
            "market_value":  self.market_value,
            "initial_shares":   self.initial_shares,
            "initial_avg_cost": self.initial_avg_cost,
        }
