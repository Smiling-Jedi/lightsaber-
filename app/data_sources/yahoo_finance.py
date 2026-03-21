"""
Yahoo Finance 数据源（使用 yfinance）
优先级：港股首选，美股首选
"""
import logging
from decimal import Decimal
from typing import List

import yfinance as yf

from app.data_sources.base import BaseDataSource, PriceData, NewsData, DataSourceError

logger = logging.getLogger(__name__)


class YahooFinanceSource(BaseDataSource):
    """Yahoo Finance 数据源"""

    def __init__(self, retry_count: int = 2, retry_delay: float = 1.0):
        super().__init__(retry_count, retry_delay)

    def _convert_symbol(self, symbol: str, market: str = None) -> str:
        """
        转换为 Yahoo Finance 格式
        HK:00700 -> 0700.HK
        US:TSLA -> TSLA
        A:600519 -> 600519.SS
        """
        if ":" in symbol:
            market, code = symbol.split(":", 1)
        else:
            code = symbol
            market = market or "US"

        if market == "HK":
            # 港股：转为4位数格式 00700 -> 0700.HK
            return f"{str(int(code)).zfill(4)}.HK"
        elif market == "A":
            # A股：上海 .SS，深圳 .SZ
            if code.startswith("6"):
                return f"{code}.SS"
            else:
                return f"{code}.SZ"
        else:
            # 美股直接返回
            return code

    def get_price(self, symbol: str, market: str = None) -> PriceData:
        """
        获取股价

        Args:
            symbol: 股票代码（如 "HK:00700" 或 "US:TSLA"）
            market: 市场（可选，用于没有前缀的代码）

        Returns:
            PriceData
        """
        try:
            yahoo_symbol = self._convert_symbol(symbol, market)
            logger.info(f"Yahoo Finance: 查询 {symbol} -> {yahoo_symbol}")

            ticker = yf.Ticker(yahoo_symbol)
            # 获取近5天数据（避免周末/节假日无数据）
            hist = ticker.history(period="5d")

            if hist.empty:
                raise DataSourceError(f"Yahoo Finance 无数据: {yahoo_symbol}")

            # 获取最新数据
            latest = hist.iloc[-1]

            # 确定市场
            if ":" in symbol:
                market_code = symbol.split(":")[0]
            else:
                market_code = market or "US"

            return PriceData(
                symbol=symbol,
                market=market_code,
                current_price=Decimal(str(latest["Close"])),
                open_price=Decimal(str(latest["Open"])),
                high_price=Decimal(str(latest["High"])),
                low_price=Decimal(str(latest["Low"])),
                volume=int(latest["Volume"]),
                source="yahoo",
            )

        except Exception as e:
            logger.warning(f"Yahoo Finance 获取 {symbol} 失败: {e}")
            raise DataSourceError(f"Yahoo Finance 错误: {e}")

    def get_news(self, symbol: str) -> List[NewsData]:
        """Yahoo Finance 不提供新闻，返回空列表"""
        return []
