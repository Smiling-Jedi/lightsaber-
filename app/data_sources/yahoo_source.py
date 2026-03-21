"""
Yahoo Finance 数据源适配器（港股 / 美股）
"""
import logging
from decimal import Decimal
from typing import List, Optional

import requests

from app.data_sources.base import (
    BaseDataSource, PriceData, NewsData,
    ForbiddenError, DataSourceError
)

logger = logging.getLogger(__name__)


class YahooSource(BaseDataSource):
    """Yahoo Finance 数据源，用于港股和美股"""

    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(
        self,
        retry_count: int = 3,
        retry_delay: float = 1.0,
        proxy: Optional[str] = None,
    ):
        super().__init__(retry_count, retry_delay)
        self.proxy = proxy

    def _get(self, yahoo_symbol: str) -> dict:
        """发送 Yahoo Finance 请求"""
        url = f"{self.BASE_URL}/{yahoo_symbol}"
        proxies = {"https": self.proxy, "http": self.proxy} if self.proxy else None

        response = requests.get(url, proxies=proxies, timeout=10)

        if response.status_code == 403:
            raise ForbiddenError(
                "Yahoo Finance 拒绝访问（IP 被限制），请配置代理后重试。"
            )
        response.raise_for_status()
        return response.json()

    def get_price(self, symbol: str) -> PriceData:
        """
        获取港股或美股收盘价

        Args:
            symbol: 股票代码，如 "00700"（港股）或 "TSLA"（美股）

        Returns:
            PriceData
        """
        market = self._detect_market(symbol)
        yahoo_symbol = self._to_yahoo_symbol(symbol, market)

        def _fetch():
            data = self._get(yahoo_symbol)
            result = data.get("chart", {}).get("result", [])
            if not result:
                raise DataSourceError(f"Yahoo Finance 未返回数据: {symbol}")

            meta = result[0].get("meta", {})
            quote = result[0].get("indicators", {}).get("quote", [{}])[0]

            # 取最新收盘价（列表最后一项，过滤 None）
            closes = [c for c in (quote.get("close") or []) if c is not None]
            opens = [o for o in (quote.get("open") or []) if o is not None]
            highs = [h for h in (quote.get("high") or []) if h is not None]
            lows = [l for l in (quote.get("low") or []) if l is not None]
            volumes = [v for v in (quote.get("volume") or []) if v is not None]

            current = Decimal(str(meta.get("regularMarketPrice") or closes[-1]))

            return PriceData(
                symbol=symbol,
                market=market,
                current_price=current,
                open_price=Decimal(str(opens[-1])) if opens else None,
                high_price=Decimal(str(highs[-1])) if highs else None,
                low_price=Decimal(str(lows[-1])) if lows else None,
                volume=int(volumes[-1]) if volumes else None,
                source="yahoo",
            )

        return self.fetch_with_retry(_fetch)

    def get_news(self, symbol: str) -> List[NewsData]:
        """Yahoo Finance 新闻暂不使用，返回空列表"""
        return []

    @staticmethod
    def _detect_market(symbol: str) -> str:
        """根据股票代码判断市场"""
        # 港股：纯数字，长度4-5位
        if symbol.isdigit():
            return "HK"
        return "US"

    @staticmethod
    def _to_yahoo_symbol(symbol: str, market: str) -> str:
        """
        转换为 Yahoo Finance 股票代码格式

        Examples:
            "00700" (HK) → "0700.HK"
            "TSLA"  (US) → "TSLA"
        """
        if market == "HK":
            # 去掉前导零后加 .HK
            return f"{symbol.lstrip('0') or '0'}.HK"
        return symbol
