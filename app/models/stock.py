"""
股票基础信息模型
"""
from datetime import datetime
from typing import List

from sqlalchemy import Column, String, DateTime, Numeric, Integer, and_
from sqlalchemy.orm import relationship

from app.core.database import Base


class Stock(Base):
    """股票基础信息"""

    __tablename__ = "stocks"
    __allow_unmapped__ = True

    # 股票代码（唯一标识，格式：市场:代码，如 HK:00700）
    symbol = Column(String(20), primary_key=True, index=True, comment="股票代码")

    # 股票名称
    name = Column(String(100), nullable=False, comment="股票名称")

    # 市场（HK/ US/ A）
    market = Column(String(10), nullable=False, index=True, comment="市场")

    # 货币（HKD/ USD/ CNY）
    currency = Column(String(10), nullable=False, comment="货币")

    # 行业板块
    sector = Column(String(50), nullable=True, comment="行业板块")

    # 当前价格（缓存，收盘后更新）
    current_price = Column(Numeric(15, 4), nullable=True, comment="当前价格")

    # 今日开盘价
    open_price = Column(Numeric(15, 4), nullable=True, comment="开盘价")

    # 昨日收盘价（用于计算今日盈亏）
    prev_close_price = Column(Numeric(15, 4), nullable=True, comment="昨日收盘价")

    # 今日最高价
    high_price = Column(Numeric(15, 4), nullable=True, comment="最高价")

    # 今日最低价
    low_price = Column(Numeric(15, 4), nullable=True, comment="最低价")

    # 今日成交量
    volume = Column(Integer, nullable=True, comment="成交量")

    # 价格更新时间
    price_updated_at = Column(DateTime, nullable=True, comment="价格更新时间")

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # 关联持仓记录（包含已清仓）
    positions: List["Position"] = relationship("Position", back_populates="stock", cascade="all, delete-orphan")

    # 只返回有效持仓（total_shares > 0）
    active_positions: List["Position"] = relationship(
        "Position",
        back_populates="stock",
        primaryjoin="and_(Stock.symbol == Position.stock_symbol, Position.total_shares > 0)",
        viewonly=True
    )

    # 关联新闻
    news: List["News"] = relationship("News", back_populates="stock", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Stock(symbol='{self.symbol}', name='{self.name}', market='{self.market}')>"

    @property
    def price_change_pct(self) -> float:
        """计算涨跌幅百分比（基于昨日收盘价）"""
        if self.current_price and self.prev_close_price and self.prev_close_price > 0:
            return float((self.current_price - self.prev_close_price) / self.prev_close_price * 100)
        return 0.0

    @property
    def is_price_stale(self) -> bool:
        """判断价格是否过期（超过15分钟）"""
        if not self.price_updated_at:
            return True
        from datetime import timedelta
        return datetime.now() - self.price_updated_at > timedelta(minutes=15)
