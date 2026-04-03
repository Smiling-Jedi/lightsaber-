"""
聚合数据源 - 用于价格更新（市场公开数据）

⚠️ 重要区分：
- 持仓同步（账户数据）：港股/美股走富途OpenD，A股必须用户手动录入
- 价格更新（市场数据）：用本聚合源，按优先级自动选择

实时股价优先级（2026-04-03更新）:
- A股: iFinD > Tushare > Yahoo > EastMoney
- 港股: iFinD > 富途OpenD > Tushare > Yahoo
- 美股: 富途OpenD > iFinD > Yahoo

详细配置：docs/数据源优先级配置.md

基本面/历史数据: 用 app.data_sources.ifind_source 直接查iFinD
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
        market = symbol.split(":")[0] if ":" in symbol else "US"
        return PriceData(
            symbol=symbol,
            market=market,
            current_price=d["current_price"],
            open_price=d.get("open_price", 0),
            high_price=d.get("high_price", 0),
            low_price=d.get("low_price", 0),
            volume=d.get("volume", 0),
            source="futu",
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

        # 数据源优先级配置（港美股OpenD优先；A股Tushare优先，OpenD不支持A股）
        self.priority = {
            "HK": [self.futu, self.tushare, self.yahoo, self.eastmoney, self.alpha],
            "US": [self.futu, self.tushare, self.yahoo, self.alpha],
            "A": [self.tushare, self.yahoo, self.eastmoney, self.alpha],
        }

    def _get_market(self, symbol: str) -> str:
        """从 symbol 中提取市场代码"""
        if ":" in symbol:
            return symbol.split(":")[0]
        return "US"  # 默认美股

    def _is_hk_stock_connect(self, symbol: str) -> bool:
        """识别港股通股票（A股账户持有的港股）

        港股通代码特征：5位数字，如 09988(阿里)、01810(小米)
        与A股代码区分：A股是6位（600xxx/000xxx/300xxx）
        """
        if not symbol.startswith("A:"):
            return False
        code = symbol.split(":")[1]
        # 港股通代码：5位数字（09988, 01810等）
        # A股代码：6位数字
        return len(code) == 5 and code.isdigit()

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

        # 港股通（A股账户里的港股）用富途优先查港股价格
        if self._is_hk_stock_connect(symbol):
            # 将 A:09988 转为 HK:09988 用富途查询
            hk_symbol = symbol.replace("A:", "HK:")
            sources = [self.futu, self.tushare, self.yahoo, self.eastmoney, self.alpha]
            logger.info(f"识别为港股通: {symbol} -> {hk_symbol}, 使用富途优先")

        errors = []

        for source in sources:
            source_name = source.__class__.__name__
            try:
                logger.info(f"尝试从 {source_name} 获取 {symbol}...")
                # 港股通查询时，富途需要用 HK:09988 格式
                query_symbol = hk_symbol if (self._is_hk_stock_connect(symbol) and source_name == "FutuAdapterSource") else symbol
                price_data = source.get_price(query_symbol)
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
