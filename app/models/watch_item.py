"""
关注事项模型
Jedi手动维护的股票关注事项（财报/事件/政策等）
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Date, Index

from app.core.database import Base


class WatchItem(Base):
    """关注事项"""

    __tablename__ = "watch_items"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票代码
    stock_symbol = Column(String(20), nullable=False, index=True, comment="股票代码")

    # 事项内容
    content = Column(String(500), nullable=False, comment="事项内容")

    # 预计日期
    expected_date = Column(Date, nullable=True, comment="预计日期")

    # 重要性
    importance = Column(
        String(10), nullable=True, default="medium",
        comment="重要性: high/medium/low"
    )

    # 状态
    status = Column(
        String(20), nullable=True, default="pending",
        comment="状态: pending/occurred/handled"
    )

    created_at = Column(
        DateTime, default=datetime.now, nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now,
        nullable=False, comment="更新时间"
    )

    # 索引：按股票+状态查询待关注事项
    __table_args__ = (
        Index("ix_watch_items_symbol_status", "stock_symbol", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<WatchItem(symbol='{self.stock_symbol}', "
            f"content='{self.content[:30]}...', "
            f"status='{self.status}')>"
        )

    @property
    def is_upcoming(self) -> bool:
        """是否在未来30天内"""
        if not self.expected_date:
            return True
        from datetime import timedelta
        return self.expected_date <= datetime.now().date() + timedelta(days=30)

    @property
    def is_today(self) -> bool:
        """是否是今天"""
        if not self.expected_date:
            return False
        return self.expected_date == datetime.now().date()
