"""
Tushare 数据源适配器（A 股）
"""
import logging
from decimal import Decimal
from typing import List

import requests

from app.data_sources.base import (
    BaseDataSource, PriceData, NewsData,
    InsufficientPointsError, DataSourceError
)

logger = logging.getLogger(__name__)

# Tushare 错误码
TUSHARE_INSUFFICIENT_POINTS = -2001


class TushareSource(BaseDataSource):
    """Tushare 数据源，用于 A 股行情数据"""

    def __init__(self, token: str, retry_count: int = 3, retry_delay: float = 1.0):
        super().__init__(retry_count, retry_delay)
        self.token = token
        self.base_url = "https://api.tushare.pro"

    def _post(self, api_name: str, params: dict) -> dict:
        """发送 Tushare API 请求"""
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params,
            "fields": "",
        }
        response = requests.post(self.base_url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == TUSHARE_INSUFFICIENT_POINTS:
            raise InsufficientPointsError(
                "Tushare 积分不足，请充值或配置备用数据源。"
                "充值地址：https://tushare.pro/user/index"
            )
        if data.get("code") != 0:
            raise DataSourceError(f"Tushare API 错误: code={data.get('code')}, msg={data.get('msg')}")

        return data

    def get_price(self, symbol: str) -> PriceData:
        """
        获取股价（A股/港股）

        Args:
            symbol: 股票代码，如 "HK:00700"、"A:600519"

        Returns:
            PriceData
        """
        if ":" in symbol:
            market, code = symbol.split(":", 1)
        else:
            market, code = "A", symbol

        if market == "HK":
            return self._get_hk_price(symbol, code)
        else:
            return self._get_a_price(symbol, code)

    def _get_a_price(self, symbol: str, code: str) -> PriceData:
        """获取 A 股价格（支持股票和ETF）- 使用实时行情"""
        # ETF基金代码：510xxx/159xxx/512xxx等
        is_etf = code.startswith(("15", "51", "56", "58", "16", "50"))

        if is_etf:
            return self._get_etf_price(symbol, code)

        # 普通股票 - 使用实时行情接口
        ts_code = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"

        def _fetch():
            # 优先使用实时行情接口
            try:
                import tushare as ts
                ts.set_token(self.token)
                # 使用 realtime_quote 获取实时行情
                df = ts.realtime_quote(ts_code=ts_code, src='sina')
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    return PriceData(
                        symbol=symbol,
                        market="A",
                        current_price=Decimal(str(row["PRICE"])),
                        open_price=Decimal(str(row["OPEN"])),
                        high_price=Decimal(str(row["HIGH"])),
                        low_price=Decimal(str(row["LOW"])),
                        volume=int(row.get("VOLUME", 0)),
                        source="tushare_realtime",
                    )
            except Exception as e:
                logger.warning(f"实时行情获取失败，回退到日线: {e}")

            # 回退到日线接口
            data = self._post("daily", {"ts_code": ts_code, "limit": 1})
            items = data.get("data", {}).get("items", [])
            if not items:
                raise DataSourceError(f"未找到股票数据: {symbol}")
            fields = data["data"]["fields"]
            row = dict(zip(fields, items[0]))
            return PriceData(
                symbol=symbol,
                market="A",
                current_price=Decimal(str(row["close"])),
                open_price=Decimal(str(row["open"])),
                high_price=Decimal(str(row["high"])),
                low_price=Decimal(str(row["low"])),
                volume=int(row.get("vol", 0)),
                source="tushare",
            )

        return self.fetch_with_retry(_fetch)

    def _get_etf_price(self, symbol: str, code: str) -> PriceData:
        """获取ETF基金价格（使用实时行情）"""
        # ETF代码后缀：上海.SH 深圳.SZ
        suffix = ".SH" if code.startswith(("51", "56", "58")) else ".SZ"
        ts_code = f"{code}{suffix}"

        def _fetch():
            # 优先使用实时行情接口
            try:
                import tushare as ts
                ts.set_token(self.token)
                df = ts.realtime_quote(ts_code=ts_code, src='sina')
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    return PriceData(
                        symbol=symbol,
                        market="A",
                        current_price=Decimal(str(row["PRICE"])),
                        open_price=Decimal(str(row["OPEN"])),
                        high_price=Decimal(str(row["HIGH"])),
                        low_price=Decimal(str(row["LOW"])),
                        volume=int(row.get("VOLUME", 0)),
                        source="tushare_realtime",
                    )
            except Exception as e:
                logger.warning(f"ETF实时行情获取失败，回退到日线: {e}")

            # 回退到fund_daily接口
            data = self._post("fund_daily", {"ts_code": ts_code, "limit": 1})
            items = data.get("data", {}).get("items", [])
            if not items:
                raise DataSourceError(f"未找到ETF数据: {symbol}")
            fields = data["data"]["fields"]
            row = dict(zip(fields, items[0]))
            return PriceData(
                symbol=symbol,
                market="A",
                current_price=Decimal(str(row["close"])),
                open_price=Decimal(str(row.get("open", row["close"]))),
                high_price=Decimal(str(row.get("high", row["close"]))),
                low_price=Decimal(str(row.get("low", row["close"]))),
                volume=int(row.get("vol", 0)) if row.get("vol") else 0,
                source="tushare",
            )

        return self.fetch_with_retry(_fetch)

    def _get_hk_price(self, symbol: str, code: str) -> PriceData:
        """获取港股价格（使用 hk_daily 接口）"""
        # Tushare 港股格式：00700.HK
        ts_code = f"{code}.HK"

        def _fetch():
            data = self._post("hk_daily", {"ts_code": ts_code, "limit": 1})
            items = data.get("data", {}).get("items", [])
            if not items:
                raise DataSourceError(f"未找到港股数据: {symbol}")
            fields = data["data"]["fields"]
            row = dict(zip(fields, items[0]))
            return PriceData(
                symbol=symbol,
                market="HK",
                current_price=Decimal(str(row["close"])),
                open_price=Decimal(str(row["open"])),
                high_price=Decimal(str(row["high"])),
                low_price=Decimal(str(row["low"])),
                volume=int(row.get("vol", 0)),
                source="tushare",
            )

        return self.fetch_with_retry(_fetch)

    def get_news(self, symbol: str) -> List[NewsData]:
        """Tushare 暂不提供新闻，返回空列表"""
        return []
