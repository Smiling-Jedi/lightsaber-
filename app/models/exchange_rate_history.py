"""
汇率历史模型
记录每日汇率，用于历史资产重算
"""
from datetime import datetime, date
from sqlalchemy import Column, Integer, Date, DateTime, Numeric, String, UniqueConstraint
from app.core.database import Base


class ExchangeRateHistory(Base):
    """汇率历史记录"""

    __tablename__ = 'exchange_rate_history'
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 日期
    date = Column(Date, nullable=False, index=True, unique=True)

    # 汇率（1单位外币 = ?人民币）
    hkd_rate = Column(Numeric(10, 6), nullable=False, comment='1 HKD = ? CNY')
    usd_rate = Column(Numeric(10, 6), nullable=False, comment='1 USD = ? CNY')

    # 数据来源
    source = Column(String(50), default='API', nullable=False, comment='API-自动获取/MANUAL-手动设置')

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        UniqueConstraint('date', name='uix_rate_date'),
    )

    def __repr__(self):
        return f"<ExchangeRateHistory(date={self.date}, HKD={self.hkd_rate}, USD={self.usd_rate})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "hkd_rate": float(self.hkd_rate) if self.hkd_rate else None,
            "usd_rate": float(self.usd_rate) if self.usd_rate else None,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def get_rate_for_date(cls, db, query_date: date):
        """获取指定日期的汇率，如果不存在返回最近日期的汇率"""
        rate = db.query(cls).filter(cls.date <= query_date).order_by(cls.date.desc()).first()
        return rate
