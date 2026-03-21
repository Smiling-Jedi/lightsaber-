"""
技术指标计算服务（纯 pandas 实现，无需 ta-lib）
"""
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class IndicatorService:
    """
    纯 pandas 实现的技术指标计算器。
    输入：OHLCV DataFrame（DatetimeIndex，列名小写）
    输出：原 DataFrame 追加指标列
    """

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        一次性计算所有指标，返回追加以下列的 DataFrame：
        ema20, ema60, macd, macd_signal, macd_hist,
        rsi14, atr14, bb_upper, bb_mid, bb_lower, adx14
        """
        if df.empty or len(df) < 30:
            logger.warning("历史数据不足30条，跳过指标计算")
            return df

        df = df.copy()

        # EMA
        df["ema20"] = self._ema(df["close"], 20)
        df["ema60"] = self._ema(df["close"], 60)

        # MACD
        df["macd"], df["macd_signal"], df["macd_hist"] = self._macd(df["close"])

        # RSI
        df["rsi14"] = self._rsi(df["close"], 14)

        # ATR（先算，ADX 会复用）
        df["atr14"] = self._atr(df, 14)

        # 布林带
        df["bb_upper"], df["bb_mid"], df["bb_lower"] = self._bollinger(df["close"])

        # ADX
        df["adx14"] = self._adx(df, 14)

        return df

    # ────────────────────────────────────────────────
    # 各指标实现
    # ────────────────────────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        """指数移动平均，span=period，adjust=False（标准递推公式）"""
        return series.ewm(span=period, adjust=False).mean()

    def _macd(
        self,
        series: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ):
        """
        MACD = EMA(fast) - EMA(slow)
        Signal = EMA(MACD, signal)
        Hist = MACD - Signal
        """
        ema_fast = self._ema(series, fast)
        ema_slow = self._ema(series, slow)
        macd = ema_fast - ema_slow
        macd_signal = self._ema(macd, signal)
        macd_hist = macd - macd_signal
        return macd, macd_signal, macd_hist

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        RSI（Wilder 平滑法）
        gain/loss 均用 ewm(alpha=1/period) 平滑
        """
        delta = series.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        rs = gain / loss.replace(0, np.inf)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        ATR（Wilder 平滑）
        True Range = max(H-L, |H-prev_C|, |L-prev_C|)
        """
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def _bollinger(
        series: pd.Series, period: int = 20, std_dev: float = 2.0
    ):
        """
        布林带
        中轨 = SMA(20)
        上轨 = 中轨 + 2 * std（总体标准差，与 TradingView 一致）
        下轨 = 中轨 - 2 * std
        """
        mid = series.rolling(period).mean()
        std = series.rolling(period).std(ddof=0)
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    @staticmethod
    def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        ADX（Wilder 平滑）
        +DM / -DM → +DI / -DI → DX → ADX
        """
        prev_high = df["high"].shift(1)
        prev_low = df["low"].shift(1)

        plus_dm = df["high"] - prev_high
        minus_dm = prev_low - df["low"]

        # 只保留有效方向移动
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        atr = df["atr14"]  # 复用已计算的 ATR
        eps = 1e-10

        plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + eps)
        minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + eps)

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + eps)
        adx = dx.ewm(alpha=1 / period, adjust=False).mean()
        return adx

    # ────────────────────────────────────────────────
    # 工具方法：提取最新指标快照
    # ────────────────────────────────────────────────

    @staticmethod
    def latest_snapshot(df: pd.DataFrame) -> dict:
        """提取最后一行的指标值，供信号服务使用"""
        if df.empty:
            return {}
        row = df.iloc[-1]
        snapshot = {}
        for col in ["ema20", "ema60", "macd", "macd_signal", "macd_hist",
                    "rsi14", "atr14", "bb_upper", "bb_mid", "bb_lower", "adx14", "close"]:
            if col in row.index and pd.notna(row[col]):
                snapshot[col] = round(float(row[col]), 4)
        return snapshot
