"""
现金余额模型
"""
from datetime import datetime
from sqlalchemy import Column, String, Numeric, DateTime
from app.core.database import Base


class CashBalance(Base):
    """各市场现金余额"""

    __tablename__ = "cash_balances"
    __allow_unmapped__ = True

    # 市场作为主键（HK / US / A / FUND）
    market = Column(String(10), primary_key=True, comment="市场")

    # 币种
    currency = Column(String(10), nullable=False, comment="币种")

    # 现金余额
    amount = Column(Numeric(20, 4), nullable=False, default=0, comment="现金余额")

    # 更新时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    def __repr__(self):
        return f"<CashBalance(market='{self.market}', amount={self.amount} {self.currency})>"
