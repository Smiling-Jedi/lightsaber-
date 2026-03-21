"""
汇率数据源（收盘日汇率）
"""
import logging
from decimal import Decimal
from datetime import datetime
from typing import Dict, List

import requests

from app.data_sources.base import BaseDataSource, PriceData, NewsData, DataSourceError

logger = logging.getLogger(__name__)

# 默认汇率（兜底，避免网络失败时无法计算）
# HKD≈0.882：USD/HKD≈7.84（联系汇率），USD/CNY≈6.92 → HKD/CNY=6.92/7.84≈0.882
DEFAULT_RATES: Dict[str, Decimal] = {
    "HKD": Decimal("0.880"),  # 1 HKD → CNY（Frankfurter 2026-03-20）
    "USD": Decimal("6.894"),  # 1 USD → CNY（Frankfurter 2026-03-20）
    "CNY": Decimal("1.00"),   # 1 CNY → CNY
}


class ExchangeRateSource(BaseDataSource):
    """汇率数据源，获取收盘日汇率"""

    # 使用离岸人民币汇率（更贴近券商报价）
    FX_SYMBOLS = {
        "USD": "USDCNH=X",
        "HKD": "HKDCNH=X",
    }

    def __init__(self, retry_count: int = 3, retry_delay: float = 1.0):
        super().__init__(retry_count, retry_delay)
        self._cache: Dict[str, Decimal] = {}
        self._cache_date: datetime = None

    def get_price(self, symbol: str) -> PriceData:
        """汇率源不提供股价"""
        raise NotImplementedError("ExchangeRateSource 不提供股价数据")

    def get_news(self, symbol: str) -> List[NewsData]:
        """汇率源不提供新闻"""
        return []

    def get_rate_to_cny(self, currency: str) -> Decimal:
        """
        获取指定货币兑人民币的汇率

        Args:
            currency: 货币代码，如 "HKD" / "USD" / "CNY"

        Returns:
            Decimal，1单位外币 = X 人民币
        """
        if currency == "CNY":
            return Decimal("1.00")

        # 使用缓存（当日缓存）
        today = datetime.now().date()
        if self._cache and self._cache_date == today and currency in self._cache:
            return self._cache[currency]

        try:
            rates = self.fetch_with_retry(self._fetch_rates)
            self._cache = rates
            self._cache_date = today
            return rates.get(currency, DEFAULT_RATES.get(currency, Decimal("1.00")))
        except Exception as e:
            logger.warning(f"获取汇率失败，使用默认值: {e}")
            return DEFAULT_RATES.get(currency, Decimal("1.00"))

    def _fetch_rates(self) -> Dict[str, Decimal]:
        """从 Frankfurter API 获取汇率（免费，无需 key）"""
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "CNY", "to": "HKD,USD"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        # 返回格式: {"base": "CNY", "rates": {"HKD": X, "USD": Y}}
        # 我们需要反转: 1 HKD = ? CNY
        fx = data.get("rates", {})
        rates = {}
        if "HKD" in fx and fx["HKD"] > 0:
            rates["HKD"] = Decimal(str(round(1 / fx["HKD"], 5)))
        if "USD" in fx and fx["USD"] > 0:
            rates["USD"] = Decimal(str(round(1 / fx["USD"], 5)))
        if not rates:
            raise DataSourceError("Frankfurter 返回数据为空")
        logger.info(f"汇率更新: {rates}")
        return rates
