"""
Alpha Vantage 数据源
优先级：美股备用（当 Yahoo 失败时），港股最后备选
"""
import logging
from decimal import Decimal
from typing import List

from alpha_vantage.timeseries import TimeSeries

from app.data_sources.base import BaseDataSource, PriceData, NewsData, DataSourceError

logger = logging.getLogger(__name__)


class AlphaVantageSource(BaseDataSource):
    """Alpha Vantage 数据源"""

    def __init__(self, api_key: str = None, retry_count: int = 2, retry_delay: float = 2.0):
        super().__init__(retry_count, retry_delay)
        self.api_key = api_key or "demo"
        self.ts = TimeSeries(key=self.api_key, output_format='pandas')

    def _convert_symbol(self, symbol: str, market: str = None) -> str:
        """
        转换为 Alpha Vantage 格式
        美股直接返回，港股加 .HK
        """
        if ":" in symbol:
            market, code = symbol.split(":", 1)
        else:
            code = symbol
            market = market or "US"

        if market == "HK":
            return f"{code}.HK"
        elif market == "A":
            if code.startswith("6"):
                return f"{code}.SH"
            else:
                return f"{code}.SZ"
        else:
            return code

    def get_price(self, symbol: str, market: str = None) -> PriceData:
        """获取股价"""
        try:
            av_symbol = self._convert_symbol(symbol, market)
            logger.info(f"Alpha Vantage: 查询 {symbol} -> {av_symbol}")

            data, meta_data = self.ts.get_quote_endpoint(symbol=av_symbol)

            if data.empty:
                raise DataSourceError(f"Alpha Vantage 无数据: {av_symbol}")

            row = data.iloc[0]

            if ":" in symbol:
                market_code = symbol.split(":")[0]
            else:
                market_code = market or "US"

            return PriceData(
                symbol=symbol,
                market=market_code,
                current_price=Decimal(str(row.get("05. price", 0))),
                open_price=Decimal(str(row.get("02. open", 0))),
                high_price=Decimal(str(row.get("03. high", 0))),
                low_price=Decimal(str(row.get("04. low", 0))),
                volume=int(float(row.get("06. volume", 0))),
                source="alpha_vantage",
            )

        except Exception as e:
            logger.warning(f"Alpha Vantage 获取 {symbol} 失败: {e}")
            raise DataSourceError(f"Alpha Vantage 错误: {e}")

    def get_news(self, symbol: str) -> List[NewsData]:
        """Alpha Vantage 不提供新闻"""
        return []
