"""
富途K线服务

功能：
- 通过富途 OpenD 拉取日K（QFQ前复权，调用 request_history_kline）
- 本地 CSV 缓存（当日内不重复请求）
- 计算 MA5/10/20/30/60/200 均线
- 返回前端所需的 OHLCV + MA 数据结构

需要 OpenD 运行在 127.0.0.1:11111
"""
import csv
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 缓存目录：项目 data/kline_cache/
CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "kline_cache"
)
os.makedirs(CACHE_DIR, exist_ok=True)

MA_PERIODS = [5, 10, 20, 30, 60, 200]


class FutuKlineService:

    def get_kline(self, symbol: str, count: int = 500) -> List[Dict]:
        """
        获取K线数据，优先读本地缓存（当日缓存）。

        symbol 格式：HK:00700
        count: 拉取根数，默认500（足够预热 MA200 + 展示1年）
        返回：按日期升序排列的 OHLCV + MA 列表
        """
        cache_file = self._cache_path(symbol)
        if self._is_cache_valid(cache_file):
            logger.info(f"使用K线缓存: {symbol}")
            rows = self._read_cache(cache_file)
        else:
            logger.info(f"从富途拉取K线: {symbol}")
            rows = self._fetch_from_futu(symbol, count)
            if rows:
                self._write_cache(cache_file, rows)

        return self._attach_ma(rows)

    # ─────────────────────────────────────────────────────
    # 富途拉取
    # ─────────────────────────────────────────────────────

    def _fetch_from_futu(self, symbol: str, count: int) -> List[Dict]:
        """调用富途 get_history_kline 获取日K（QFQ前复权）"""
        try:
            from futu import OpenQuoteContext, KLType, AuType, RET_OK

            futu_code = symbol.replace(":", ".", 1)  # HK:00700 → HK.00700
            ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            try:
                ret, data, _ = ctx.request_history_kline(
                    futu_code,
                    ktype=KLType.K_DAY,
                    autype=AuType.QFQ,
                    max_count=count,
                )
                if ret != RET_OK or data is None or data.empty:
                    logger.warning(f"富途K线拉取失败: {symbol}, ret={ret}")
                    return []

                rows = []
                for _, row in data.iterrows():
                    rows.append({
                        "date":   str(row["time_key"])[:10],
                        "open":   float(row["open"]),
                        "high":   float(row["high"]),
                        "low":    float(row["low"]),
                        "close":  float(row["close"]),
                        "volume": int(row["volume"]),
                    })
                return rows
            finally:
                ctx.close()
        except Exception as e:
            logger.error(f"富途K线拉取异常: {symbol}: {e}")
            return []

    # ─────────────────────────────────────────────────────
    # 本地缓存
    # ─────────────────────────────────────────────────────

    def _cache_path(self, symbol: str) -> str:
        safe = symbol.replace(":", "_")
        today = date.today().strftime("%Y%m%d")
        return os.path.join(CACHE_DIR, f"{safe}_{today}.csv")

    def _is_cache_valid(self, path: str) -> bool:
        return os.path.exists(path) and os.path.getsize(path) > 100

    def _write_cache(self, path: str, rows: List[Dict]):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)

    def _read_cache(self, path: str) -> List[Dict]:
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "date":   row["date"],
                    "open":   float(row["open"]),
                    "high":   float(row["high"]),
                    "low":    float(row["low"]),
                    "close":  float(row["close"]),
                    "volume": int(row["volume"]),
                })
        return rows

    # ─────────────────────────────────────────────────────
    # MA 计算
    # ─────────────────────────────────────────────────────

    def _attach_ma(self, rows: List[Dict]) -> List[Dict]:
        """在每根K线上附加 MA5/10/20/30/60/200 值"""
        closes = [r["close"] for r in rows]
        ma_data: Dict[int, List[Optional[float]]] = {}
        for period in MA_PERIODS:
            ma_data[period] = self._calc_ma(closes, period)

        result = []
        for i, row in enumerate(rows):
            item = dict(row)
            for period in MA_PERIODS:
                val = ma_data[period][i]
                item[f"ma{period}"] = round(val, 4) if val is not None else None
            result.append(item)
        return result

    def _calc_ma(self, closes: List[float], period: int) -> List[Optional[float]]:
        result = []
        for i in range(len(closes)):
            if i < period - 1:
                result.append(None)
            else:
                avg = sum(closes[i - period + 1: i + 1]) / period
                result.append(avg)
        return result
