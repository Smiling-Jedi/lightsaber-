"""
聚合数据源 - 按优先级自动故障转移
港股: 富途OpenD > Yahoo > Tushare > EastMoney > Alpha Vantage
美股: 富途OpenD > Yahoo > Alpha Vantage
A股: Tushare > Yahoo > EastMoney > Alpha Vantage
"""
import logging
from typing import List

from app.data_sources.base import BaseDataSource, PriceData, NewsData, DataSourceError
from app.data_sources.yahoo_finance import YahooFinanceSource
from app.data_sources.tushare_source import TushareSource
from app.data_sources.eastmoney_source import EastMoneySource
from app.data_sources.alpha_vantage_source import AlphaVantageSource
from app.data_sources.futu_price_source import is_opend_available, get_snapshots
from config.settings import TUSHARE_TOKEN, ALPHA_VANTAGE_KEY

logger = logging.getLogger(__name__)


class FutuAdapterSource:
    """
    富途 OpenD 适配器，包装成与其他数据源一致的接口
    OpenD 不可用时抛出异常，由 AggregatedPriceSource 自动降级
    """

    # 内部代码格式 HK:00700 → 富途格式 HK.00700
    @staticmethod
    def _to_futu_code(symbol: str) -> str:
        return symbol.replace(":", ".", 1)

    @staticmethod
    def _to_internal_code(futu_code: str) -> str:
        return futu_code.replace(".", ":", 1)

    def get_price(self, symbol: str) -> PriceData:
        futu_code = self._to_futu_code(symbol)
        snapshots = get_snapshots([futu_code])  # 若 OpenD 不可用会抛 ConnectionError
        if futu_code not in snapshots:
            raise DataSourceError(f"富途未返回 {symbol} 的数据")
        d = snapshots[futu_code]
        return PriceData(
            symbol=symbol,
            current_price=d["current_price"],
            open_price=d.get("open_price", 0),
            high_price=d.get("high_price", 0),
            low_price=d.get("low_price", 0),
            volume=d.get("volume", 0),
            change_pct=d.get("change_pct", 0),
        )


class AggregatedPriceSource:
    """
    聚合价格数据源
    自动按优先级尝试多个数据源
    """

    def __init__(self, alpha_api_key: str = None):
        # 初始化各数据源
        self.futu = FutuAdapterSource()
        self.yahoo = YahooFinanceSource()
        self.tushare = TushareSource(token=TUSHARE_TOKEN)
        self.eastmoney = EastMoneySource()
        self.alpha = AlphaVantageSource(api_key=alpha_api_key or ALPHA_VANTAGE_KEY)

        # 数据源优先级配置（富途为港/美股最高优先，A股Tushare优先，富途次选）
        self.priority = {
            "HK": [self.futu, self.yahoo, self.tushare, self.eastmoney, self.alpha],
            "US": [self.futu, self.yahoo, self.alpha],
            "A": [self.tushare, self.futu, self.yahoo, self.eastmoney, self.alpha],
        }

    def _get_market(self, symbol: str) -> str:
        """从 symbol 中提取市场代码"""
        if ":" in symbol:
            return symbol.split(":")[0]
        return "US"  # 默认美股

    def get_price(self, symbol: str) -> PriceData:
        """
        获取股价，按优先级自动故障转移

        Args:
            symbol: 股票代码（如 "HK:00700", "US:TSLA"）

        Returns:
            PriceData

        Raises:
            DataSourceError: 所有数据源都失败
        """
        market = self._get_market(symbol)
        sources = self.priority.get(market, [self.yahoo, self.alpha])

        errors = []

        for source in sources:
            source_name = source.__class__.__name__
            try:
                logger.info(f"尝试从 {source_name} 获取 {symbol}...")
                price_data = source.get_price(symbol)
                logger.info(f"✅ {source_name} 成功获取 {symbol}: {price_data.current_price}")
                return price_data
            except Exception as e:
                error_msg = f"{source_name}: {e}"
                logger.warning(f"❌ {error_msg}")
                errors.append(error_msg)
                continue

        # 所有数据源都失败
        raise DataSourceError(
            f"所有数据源都失败 ({symbol}): " + "; ".join(errors)
        )

    def get_prices_batch(self, symbols: List[str]) -> dict:
        """
        批量获取股价

        Args:
            symbols: 股票代码列表

        Returns:
            dict: {symbol: PriceData 或 error}
        """
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_price(symbol)
            except Exception as e:
                results[symbol] = {"error": str(e)}
        return results
