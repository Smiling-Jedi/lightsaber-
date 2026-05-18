"""
富途K线服务

功能：
- 通过富途 OpenD 拉取日K/周K/月K（QFQ前复权，调用 request_history_kline）
- 本地 CSV 缓存（当日内不重复请求）
- 计算 MA5/10/20/30/60/200 均线（仅日K）
- 返回前端所需的 OHLCV + MA 数据结构

需要 OpenD 运行在 127.0.0.1:11111
"""
import csv
import logging
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 缓存目录：项目 data/kline_cache/
CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "kline_cache"
)
os.makedirs(CACHE_DIR, exist_ok=True)

MA_PERIODS = [5, 10, 20, 30, 60, 200]

# 富途 request_history_kline 在传 start 时是「从 start 顺序往后取 max_count 条」，
# 所以 start 必须根据想要的 N 根 K线动态计算，不能用固定大窗口。
# 这里的 days_per_bar 略小于"实际平均"，让 start 靠近 today，
# 使富途返回的 N 条 K线能恰好覆盖到最新交易日（而不是从早期取满 N 条后就截止）：
#  - 日K: 5/7 工作日比例 ≈ 1.4 天/根
#  - 周K: 7.05 天/根（>7 给 1 天 buffer）
#  - 月K: 30.5 天/根
DAYS_PER_BAR = {
    "day": 1.4,
    "week": 7.05,
    "month": 30.5,
}


class FutuKlineService:

    def get_kline(
        self, symbol: str, count: int = 500,
        ktype_str: str = "day"
    ) -> List[Dict]:
        """
        获取K线数据，优先读本地缓存（当日缓存）。

        symbol 格式：HK:00700
        count: 拉取根数，默认500
        ktype_str: K线周期 - day/week/month
        返回：按日期升序排列的 OHLCV + MA 列表
        """
        cache_file = self._cache_path(symbol, ktype_str)
        if self._is_cache_valid(cache_file):
            logger.info(f"使用K线缓存: {symbol} ({ktype_str})")
            rows = self._read_cache(cache_file)
        else:
            logger.info(f"从富途拉取K线: {symbol} ({ktype_str})")
            rows = self._fetch_from_futu(symbol, count, ktype_str)
            if rows:
                self._write_cache(cache_file, rows)
            else:
                # 富途拉取失败，对 A 股尝试 tushare
                tushare_rows = self._fetch_from_tushare(symbol, count, ktype_str)
                if tushare_rows:
                    logger.info(f"使用 tushare 补全 A 股 K 线: {symbol} ({ktype_str})")
                    rows = tushare_rows
                    self._write_cache(cache_file, rows)
                else:
                    # 富途拉取失败且无缓存
                    latest_cache = self._find_latest_cache(symbol, ktype_str)
                    if latest_cache:
                        logger.info(f"使用最近缓存: {latest_cache}")
                        rows = self._read_cache(latest_cache)

        # 仅日K计算MA
        if ktype_str == "day":
            return self._attach_ma(rows)
        return rows

    # ─────────────────────────────────────────────────────
    # 富途拉取
    # ─────────────────────────────────────────────────────

    def _fetch_from_futu(
        self, symbol: str, count: int, ktype_str: str = "day"
    ) -> List[Dict]:
        """调用富途 request_history_kline 获取K线（QFQ前复权）"""
        try:
            from futu import OpenQuoteContext, KLType, AuType, RET_OK

            # K线周期映射
            ktype_map = {
                "day": KLType.K_DAY,
                "week": KLType.K_WEEK,
                "month": KLType.K_MON,
            }
            ktype = ktype_map.get(ktype_str, KLType.K_DAY)

            # 处理 A: 前缀(A股 / 港股通)路由
            futu_code = symbol
            if symbol.startswith("A:"):
                code = symbol[2:]
                # 港股通持仓在 A 股账户里,代码是 5 位港股原代码(如 A:01810 / A:09988)
                if len(code) == 5:
                    futu_code = f"HK.{code}"
                # 60/68/69 开头的 6 位是上海
                elif code.startswith(('60', '68', '69')):
                    futu_code = f"SH.{code}"
                # 其它 6 位是深圳
                else:
                    futu_code = f"SZ.{code}"
            else:
                futu_code = symbol.replace(":", ".", 1)  # HK:00700 → HK.00700

            ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            try:
                # 富途 request_history_kline 在不传 start/end 时默认从早期日期取数，
                # 且 max_count 是「从 start 顺序取 N 条」，所以 start 必须根据 count 动态计算。
                end_date = date.today()
                days_per_bar = DAYS_PER_BAR.get(ktype_str, 1.6)
                lookback = int(count * days_per_bar)
                start_date = end_date - timedelta(days=lookback)
                ret, data, _ = ctx.request_history_kline(
                    futu_code,
                    ktype=ktype,
                    autype=AuType.QFQ,
                    max_count=count,
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                )
                if ret != RET_OK or data is None or data.empty:
                    logger.warning(
                        f"富途K线拉取失败: {symbol} ({ktype_str}), ret={ret}"
                    )
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
            logger.error(f"富途K线拉取异常: {symbol} ({ktype_str}): {e}")
            return []

    def _fetch_from_tushare(
        self, symbol: str, count: int, ktype_str: str = "day"
    ) -> List[Dict]:
        """tushare pro 补全 A 股 K 线(daily/weekly/monthly)"""
        if not symbol.startswith("A:"):
            return []
        try:
            import tushare as ts
            from config.settings import TUSHARE_TOKEN

            code = symbol[2:]
            # ts_code 后缀判断
            if code.startswith(("60", "68", "69", "51", "56", "58")):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"

            # 周期映射 + 回推天数
            period_map = {"day": 1.6, "week": 7.0, "month": 31.0}
            lookback_days = int(count * period_map.get(ktype_str, 1.6))
            end_date = date.today()
            start_date = end_date - timedelta(days=lookback_days)

            ts.set_token(TUSHARE_TOKEN)
            pro = ts.pro_api()

            # ETF 用 fund_xxx 接口,股票用 daily/weekly/monthly
            is_etf = code.startswith(("51", "56", "58"))

            if ktype_str == "day":
                if is_etf:
                    df = pro.fund_daily(
                        ts_code=ts_code,
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                    )
                else:
                    df = pro.daily(
                        ts_code=ts_code,
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                    )
            elif ktype_str == "week":
                if is_etf:
                    df = pro.fund_weekly(
                        ts_code=ts_code,
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                    )
                else:
                    df = pro.weekly(
                        ts_code=ts_code,
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                    )
            elif ktype_str == "month":
                if is_etf:
                    df = pro.fund_monthly(
                        ts_code=ts_code,
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                    )
                else:
                    df = pro.monthly(
                        ts_code=ts_code,
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                    )
            else:
                return []

            if df is None or df.empty:
                return []

            # tushare 返回日期降序,需要转成升序并适配格式
            df = df.sort_values("trade_date")
            rows = []
            for _, row in df.iterrows():
                rows.append({
                    "date": str(row["trade_date"]),
                    "open":   float(row["open"]),
                    "high":   float(row["high"]),
                    "low":    float(row["low"]),
                    "close":  float(row["close"]),
                    "volume": int(row.get("vol", 0)),
                })
            return rows
        except Exception as e:
            logger.warning(f"tushare K 线补全失败: {symbol} ({ktype_str}): {e}")
            return []

    # ─────────────────────────────────────────────────────
    # 本地缓存
    # ─────────────────────────────────────────────────────

    def _cache_path(self, symbol: str, ktype_str: str = "day") -> str:
        safe = symbol.replace(":", "_")
        today = date.today().strftime("%Y%m%d")
        return os.path.join(CACHE_DIR, f"{safe}_{ktype_str}_{today}.csv")

    def _find_latest_cache(
        self, symbol: str, ktype_str: str = "day"
    ) -> Optional[str]:
        """查找该股票最近的缓存文件（不管日期）"""
        safe = symbol.replace(":", "_")
        prefix = f"{safe}_{ktype_str}_"
        candidates = []
        for fname in os.listdir(CACHE_DIR):
            if fname.startswith(prefix) and fname.endswith(".csv"):
                path = os.path.join(CACHE_DIR, fname)
                candidates.append((path, os.path.getmtime(path)))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

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
