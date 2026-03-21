"""
新闻缓存模型
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class News(Base):
    """新闻缓存"""

    __tablename__ = "news"
    __allow_unmapped__ = True

    # 主键ID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联股票
    stock_symbol = Column(String(20), ForeignKey("stocks.symbol"), nullable=False, index=True)

    # 新闻标题
    title = Column(String(500), nullable=False, comment="新闻标题")

    # 新闻摘要（截断或AI生成）
    summary = Column(String(500), nullable=True, comment="新闻摘要")

    # 原文链接
    url = Column(String(1000), nullable=False, comment="原文链接")

    # 来源（新浪财经/东方财富等）
    source = Column(String(100), nullable=False, comment="新闻来源")

    # 发布时间
    published_at = Column(DateTime, nullable=True, comment="发布时间")

    # 获取时间
    fetched_at = Column(DateTime, default=datetime.now, nullable=False, comment="获取时间")

    # 关联股票
    stock: "Stock" = relationship("Stock", back_populates="news")

    def __repr__(self) -> str:
        return f"<News(id={self.id}, stock='{self.stock_symbol}', title='{self.title[:30]}...')>"

    @property
    def is_stale(self) -> bool:
        """判断新闻是否过期（超过24小时）"""
        from datetime import timedelta
        return datetime.now() - self.fetched_at > timedelta(hours=24)
