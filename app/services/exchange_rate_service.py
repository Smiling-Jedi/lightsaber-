"""
汇率服务 - 支持历史汇率查询
"""
import logging
from datetime import date, datetime
from typing import Optional
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.exchange_rate_history import ExchangeRateHistory
from app.data_sources.exchange_rate_source import ExchangeRateSource

logger = logging.getLogger(__name__)


class ExchangeRateService:
    """汇率服务，支持获取当前汇率和历史汇率"""

    def __init__(self, db: Session):
        self.db = db
        self._live_source = ExchangeRateSource(retry_count=1)

    def get_current_rate(self, currency: str) -> Decimal:
        """
        获取当前实时汇率

        Args:
            currency: 币种 (HKD/USD)

        Returns:
            汇率值 (1外币 = ?人民币)
        """
        if currency == "CNY":
            return Decimal("1")

        try:
            rate = self._live_source.get_rate_to_cny(currency)
            return Decimal(str(rate))
        except Exception as e:
            logger.warning(f"获取实时汇率失败 {currency}: {e}")
            # 使用默认汇率
            defaults = {"HKD": Decimal("0.92"), "USD": Decimal("7.2")}
            return defaults.get(currency, Decimal("1"))

    def get_rate_for_date(self, currency: str, query_date: date) -> Decimal:
        """
        获取指定日期的汇率
        如果当天没有记录，返回最近的历史汇率

        Args:
            currency: 币种 (HKD/USD)
            query_date: 查询日期

        Returns:
            汇率值
        """
        if currency == "CNY":
            return Decimal("1")

        # 查询历史汇率
        rate_record = self.db.query(ExchangeRateHistory).filter(
            ExchangeRateHistory.date <= query_date
        ).order_by(ExchangeRateHistory.date.desc()).first()

        if rate_record:
            if currency == "HKD":
                return rate_record.hkd_rate
            elif currency == "USD":
                return rate_record.usd_rate

        # 没有历史记录，返回当前汇率
        return self.get_current_rate(currency)

    def record_today_rate(self) -> ExchangeRateHistory:
        """
        记录今日汇率到历史表

        Returns:
            ExchangeRateHistory 对象
        """
        today = date.today()

        # 检查是否已存在
        existing = self.db.query(ExchangeRateHistory).filter(
            ExchangeRateHistory.date == today
        ).first()

        if existing:
            # 更新现有记录
            existing.hkd_rate = self.get_current_rate("HKD")
            existing.usd_rate = self.get_current_rate("USD")
            existing.created_at = datetime.now()
            logger.info(f"更新今日汇率: HKD={existing.hkd_rate}, USD={existing.usd_rate}")
            return existing

        # 创建新记录
        rate_record = ExchangeRateHistory(
            date=today,
            hkd_rate=self.get_current_rate("HKD"),
            usd_rate=self.get_current_rate("USD"),
            source="API",
            created_at=datetime.now()
        )
        self.db.add(rate_record)
        self.db.flush()

        logger.info(f"记录今日汇率: HKD={rate_record.hkd_rate}, USD={rate_record.usd_rate}")
        return rate_record

    def get_rate_history(self, days: int = 30) -> list:
        """
        获取最近汇率历史

        Args:
            days: 查询天数

        Returns:
            汇率历史列表
        """
        from datetime import timedelta
        start_date = date.today() - timedelta(days=days)

        return self.db.query(ExchangeRateHistory).filter(
            ExchangeRateHistory.date >= start_date
        ).order_by(ExchangeRateHistory.date.asc()).all()
