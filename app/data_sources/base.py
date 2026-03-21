"""
数据源基类与数据结构定义
"""
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PriceData:
    """股价数据结构"""
    symbol: str
    market: str
    current_price: Decimal
    open_price: Optional[Decimal] = None
    high_price: Optional[Decimal] = None
    low_price: Optional[Decimal] = None
    volume: Optional[int] = None
    source: str = ""
    fetched_at: datetime = field(default_factory=datetime.now)

    @property
    def price_change_pct(self) -> float:
        """涨跌幅百分比"""
        if self.open_price and self.open_price > 0:
            return float((self.current_price - self.open_price) / self.open_price * 100)
        return 0.0


@dataclass
class NewsData:
    """新闻数据结构"""
    stock_symbol: str
    title: str
    url: str
    source: str
    summary: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime = field(default_factory=datetime.now)


class DataSourceError(Exception):
    """数据源基础异常"""
    pass


class InsufficientPointsError(DataSourceError):
    """积分不足（Tushare）"""
    pass


class ForbiddenError(DataSourceError):
    """IP 被限制（Yahoo Finance）"""
    pass


class MaxRetriesExceededError(DataSourceError):
    """重试次数耗尽"""
    pass


class BaseDataSource(ABC):
    """数据源基类，所有适配器必须继承此类"""

    def __init__(self, retry_count: int = 3, retry_delay: float = 1.0):
        self.retry_count = retry_count
        self.retry_delay = retry_delay

    def fetch_with_retry(self, fetch_func, *args, **kwargs):
        """
        带指数退避的重试机制

        Raises:
            ForbiddenError: 403 错误不重试，直接抛出
            InsufficientPointsError: 积分不足不重试，直接抛出
            MaxRetriesExceededError: 所有重试均失败
        """
        last_error = None

        for attempt in range(self.retry_count):
            try:
                return fetch_func(*args, **kwargs)
            except (ForbiddenError, InsufficientPointsError):
                # 这两种错误不需要重试
                raise
            except Exception as e:
                last_error = e
                if attempt < self.retry_count - 1:
                    wait = self.retry_delay * (2 ** attempt)  # 指数退避：1s → 2s → 4s
                    logger.warning(f"第 {attempt + 1} 次请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)

        raise MaxRetriesExceededError(f"重试 {self.retry_count} 次后仍失败: {last_error}")

    @abstractmethod
    def get_price(self, symbol: str) -> PriceData:
        """获取股价，子类必须实现"""
        pass

    @abstractmethod
    def get_news(self, symbol: str) -> List[NewsData]:
        """获取新闻，子类必须实现"""
        pass
