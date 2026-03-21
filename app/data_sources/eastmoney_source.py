"""
东方财富数据源（爬虫）
优先级：港股备用（当 Yahoo 和 Tushare 都失败时）
"""
import json
import logging
import re
from decimal import Decimal
from typing import List, Optional

import requests

from app.data_sources.base import BaseDataSource, PriceData, NewsData, DataSourceError

logger = logging.getLogger(__name__)


class EastMoneySource(BaseDataSource):
    """东方财富爬虫数据源"""

    def __init__(self, retry_count: int = 2, retry_delay: float = 1.0):
        super().__init__(retry_count, retry_delay)
        self.base_url = "https://push2.eastmoney.com/api/qt/stock/get"

    def _extract_code(self, symbol: str) -> tuple:
        """提取市场代码和股票代码"""
        if ":" in symbol:
            market, code = symbol.split(":", 1)
            return market, code
        return None, symbol

    def _get_secid(self, market: str, code: str) -> str:
        """
        转换为东方财富的 secid 格式
        0: 深市A股
        1: 沪市A股
        116: 港股
        105: 美股
        """
        if market == "HK":
            return f"116.{code}"
        elif market == "US":
            return f"105.{code}"
        elif market == "A":
            # A股判断上海/深圳
            if code.startswith("6"):
                return f"1.{code}"  # 上海
            else:
                return f"0.{code}"  # 深圳
        return f"0.{code}"

    def get_price(self, symbol: str, market: str = None) -> PriceData:
        """获取股价"""
        try:
            symbol_market, code = self._extract_code(symbol)
            market = market or symbol_market

            if not market:
                raise DataSourceError(f"无法确定市场: {symbol}")

            secid = self._get_secid(market, code)
            logger.info(f"EastMoney: 查询 {symbol} (secid={secid})")

            params = {
                "secid": secid,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58",
                "_": "1234567890"
            }

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }

            response = requests.get(
                self.base_url,
                params=params,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()

            data = response.json()

            if not data.get("data"):
                raise DataSourceError(f"东方财富无数据: {symbol}")

            stock_data = data["data"]

            # 东方财富字段说明：
            # f43: 当前价格(乘以0.01)
            # f44: 最高(乘以0.01)
            # f45: 最低(乘以0.01)
            # f46: 开盘(乘以0.01)
            # f47: 成交量
            # f48: 成交额

            current = Decimal(str(stock_data.get("f43", 0))) / Decimal("100")
            if current <= 0:
                raise DataSourceError(f"东方财富价格无效: {symbol}")

            return PriceData(
                symbol=symbol,
                market=market,
                current_price=current,
                open_price=Decimal(str(stock_data.get("f46", 0))) / Decimal("100"),
                high_price=Decimal(str(stock_data.get("f44", 0))) / Decimal("100"),
                low_price=Decimal(str(stock_data.get("f45", 0))) / Decimal("100"),
                volume=stock_data.get("f47", 0),
                source="eastmoney",
            )

        except Exception as e:
            logger.warning(f"东方财富获取 {symbol} 失败: {e}")
            raise DataSourceError(f"东方财富错误: {e}")

    def get_news(self, symbol: str) -> List[NewsData]:
        """东方财富不提供新闻，返回空列表"""
        return []
