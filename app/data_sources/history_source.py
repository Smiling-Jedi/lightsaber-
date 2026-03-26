"""
历史日线数据源
- 港股/美股：富途 OpenD (request_history_kline)，需 OpenD 运行在 127.0.0.1:11111
- A股：Tushare
- 本地 CSV 缓存，当日有效不重复拉取
"""
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import HISTORY_DIR, TUSHARE_TOKEN

logger = logging.getLogger(__name__)


class HistorySource:
    """
    历史日线数据源，统一返回 DataFrame。
    列：date(DatetimeIndex), open, high, low, close, volume（均小写）
    """

    def get_history(
        self,
        symbol: str,
        days: int = 2500,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        获取股票历史日线数据。

        Args:
            symbol: 光剑格式，如 "HK:00700"、"US:TSLA"、"A:600519"
            days: 获取最近多少个交易日（约2500=10年）
            force_refresh: 强制重新拉取，忽略缓存

        Returns:
            DataFrame，列：open/high/low/close/volume，DatetimeIndex
            失败时返回空 DataFrame
        """
        cache_path = self._cache_path(symbol)

        if not force_refresh and self._is_cache_valid(cache_path):
            try:
                df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                df.columns = df.columns.str.lower()
                logger.debug(f"命中缓存: {symbol} ({len(df)}条)")
                return df.tail(days)
            except Exception as e:
                logger.warning(f"读取缓存失败 {symbol}: {e}")

        # 拉取新数据
        market = symbol.split(":")[0] if ":" in symbol else "HK"
        code = symbol.split(":")[-1]

        try:
            if market in ("HK", "US"):
                df = self._fetch_futu(code, market, days)
            else:
                df = self._fetch_tushare(code, days)

            if not df.empty:
                df.to_csv(cache_path)
                logger.info(f"历史数据已缓存: {symbol} ({len(df)}条)")
            return df

        except Exception as e:
            logger.error(f"拉取历史数据失败 {symbol}: {e}")
            # 缓存失效但有旧数据时，尝试返回旧数据
            if cache_path.exists():
                try:
                    df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                    df.columns = df.columns.str.lower()
                    logger.warning(f"使用旧缓存数据: {symbol}")
                    return df.tail(days)
                except Exception:
                    pass
            return pd.DataFrame()

    def _fetch_futu(self, code: str, market: str, days: int) -> pd.DataFrame:
        """通过富途 OpenD 拉取港股/美股历史日线数据"""
        from futu import KLType, AuType, RET_OK
        from app.data_sources.futu_connection import get_futu_context

        # 光剑格式 → 富途格式：HK:00700 → HK.00700，US:TSLA → US.TSLA
        futu_code = f"{market}.{code}"

        start_date = (datetime.today() - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")
        end_date = datetime.today().strftime("%Y-%m-%d")

        # 使用全局复用的连接
        ctx = get_futu_context()

        all_rows = []
        page_key = None
        while True:
            ret, data, next_key = ctx.request_history_kline(
                futu_code,
                start=start_date,
                end=end_date,
                ktype=KLType.K_DAY,
                autype=AuType.QFQ,
                max_count=1000,
                page_req_key=page_key,
            )
            if ret != RET_OK:
                raise ValueError(f"富途 K 线请求失败 {futu_code}: {data}")
            all_rows.append(data)
            if next_key is None:
                break
            page_key = next_key

        df = pd.concat(all_rows, ignore_index=True)
        if df.empty:
            raise ValueError(f"富途未返回数据: {futu_code}")

        # 整理格式：time_key → DatetimeIndex，只保留 OHLCV
        df["date"] = pd.to_datetime(df["time_key"])
        df = df.set_index("date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index.name = "date"

        return df.tail(days)

    def _fetch_tushare(self, code: str, days: int) -> pd.DataFrame:
        """通过 Tushare 拉取 A 股历史数据"""
        try:
            import tushare as ts
            pro = ts.pro_api(TUSHARE_TOKEN)
        except ImportError:
            raise ImportError("tushare 未安装，A股历史数据不可用")

        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")

        # A股代码格式：600519 → 600519.SH / 000001 → 000001.SZ
        ts_code = self._to_tushare_code(code)

        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

        if df is None or df.empty:
            raise ValueError(f"Tushare 未返回数据: {ts_code}")

        # 整理列名和格式
        df = df.rename(columns={"vol": "volume", "trade_date": "date"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[cols].copy()

        return df.tail(days)

    @staticmethod
    def _to_tushare_code(code: str) -> str:
        """A股代码转 Tushare 格式：600519 → 600519.SH，000001 → 000001.SZ"""
        if code.startswith("6"):
            return f"{code}.SH"
        return f"{code}.SZ"

    def _cache_path(self, symbol: str) -> Path:
        """缓存文件路径，冒号替换为下划线"""
        safe_name = symbol.replace(":", "_")
        return HISTORY_DIR / f"{safe_name}.csv"

    @staticmethod
    def _is_cache_valid(path: Path) -> bool:
        """缓存文件是否为今日更新"""
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime).date()
        return mtime == date.today()
