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
        rsi14, atr14, bb_upper, bb_mid, bb_lower, adx14,
        kdj_k, kdj_d, kdj_j, cci14,
        bias6, bias12, bias24, wmsr14
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

        # ── 新增指标（2026-05-15）──
        # KDJ（9/3/3）
        df["kdj_k"], df["kdj_d"], df["kdj_j"] = self._kdj(df, n=9, m1=3, m2=3)

        # CCI（14）
        df["cci14"] = self._cci(df, n=14)

        # BIAS（6/12/24）
        df["bias6"], df["bias12"], df["bias24"] = self._bias(df, n=6, m1=12, m2=24)

        # WMSR（14）
        df["wmsr14"] = self._wmsr(df, n=14)

        # ── v2 新增：成交量指标 ──
        # OBV
        df["obv"] = self._obv(df)

        # VWAP（20日）
        df["vwap20"] = self._vwap(df, period=20)

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
    # 新增指标（2026-05-15）
    # ────────────────────────────────────────────────

    @staticmethod
    def _kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3):
        """
        KDJ（随机指标）
        RSV = (close - lowest_low_n) / (highest_high_n - lowest_low_n) * 100
        K = 2/3 * prev_K + 1/3 * RSV
        D = 2/3 * prev_D + 1/3 * K
        J = 3K - 2D
        """
        low_list = df["low"].rolling(window=n, min_periods=n).min()
        high_list = df["high"].rolling(window=n, min_periods=n).max()
        rsv = (df["close"] - low_list) / (high_list - low_list) * 100

        # 处理除零：如果 high == low，RSV = 50（中性）
        rsv = rsv.where(high_list != low_list, 50)
        rsv = rsv.fillna(50)

        k = pd.Series(index=df.index, dtype=float)
        d = pd.Series(index=df.index, dtype=float)

        k.iloc[0] = 50
        d.iloc[0] = 50

        for i in range(1, len(df)):
            k.iloc[i] = 2 / 3 * k.iloc[i - 1] + 1 / 3 * rsv.iloc[i]
            d.iloc[i] = 2 / 3 * d.iloc[i - 1] + 1 / 3 * k.iloc[i]

        j = 3 * k - 2 * d
        return k, d, j

    @staticmethod
    def _cci(df: pd.DataFrame, n: int = 14) -> pd.Series:
        """
        CCI（商品通道指数）
        TP = (high + low + close) / 3
        CCI = (TP - SMA(TP, n)) / (0.015 * mean_deviation)
        """
        tp = (df["high"] + df["low"] + df["close"]) / 3
        sma_tp = tp.rolling(window=n, min_periods=n).mean()
        mean_dev = tp.rolling(window=n, min_periods=n).apply(
            lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
        )
        cci = (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.inf))
        return cci

    @staticmethod
    def _bias(df: pd.DataFrame, n: int = 6, m1: int = 12, m2: int = 24):
        """
        BIAS（乖离率）
        BIAS_n = (close - MA(close, n)) / MA(close, n) * 100
        返回多周期：bias6, bias12, bias24
        """
        ma6 = df["close"].rolling(window=n, min_periods=n).mean()
        ma12 = df["close"].rolling(window=m1, min_periods=m1).mean()
        ma24 = df["close"].rolling(window=m2, min_periods=m2).mean()

        bias6 = (df["close"] - ma6) / ma6.replace(0, np.inf) * 100
        bias12 = (df["close"] - ma12) / ma12.replace(0, np.inf) * 100
        bias24 = (df["close"] - ma24) / ma24.replace(0, np.inf) * 100

        return bias6, bias12, bias24

    @staticmethod
    def _wmsr(df: pd.DataFrame, n: int = 14) -> pd.Series:
        """
        WMSR（威廉指标，Williams %R）
        WMSR = (highest_high_n - close) / (highest_high_n - lowest_low_n) * -100
        范围：0 ~ -100，-20以上超买，-80以下超卖
        """
        highest_high = df["high"].rolling(window=n, min_periods=n).max()
        lowest_low = df["low"].rolling(window=n, min_periods=n).min()

        wmsr = (highest_high - df["close"]) / (highest_high - lowest_low) * -100
        # 处理除零
        wmsr = wmsr.where(highest_high != lowest_low, -50)
        return wmsr

    # ────────────────────────────────────────────────
    # 工具方法：提取最新指标快照
    # ────────────────────────────────────────────────

    @staticmethod
    def _obv(df: pd.DataFrame) -> pd.Series:
        """
        OBV（On Balance Volume）
        今日OBV = 昨日OBV + sign(今日close - 昨日close) × 今日volume
        """
        close_diff = df["close"].diff()
        obv = (close_diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0)) * df["volume"]).cumsum()
        return obv

    @staticmethod
    def _vwap(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """
        VWAP（Volume Weighted Average Price）
        typical_price = (high + low + close) / 3
        VWAP = cumsum(typical_price * volume) / cumsum(volume)
        这里用滚动窗口计算
        """
        tp = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (tp * df["volume"]).rolling(window=period, min_periods=1).sum() / df["volume"].rolling(window=period, min_periods=1).sum()
        return vwap

    @staticmethod
    def latest_snapshot(df: pd.DataFrame) -> dict:
        """提取最后一行的指标值，供信号服务使用"""
        if df.empty:
            return {}
        row = df.iloc[-1]
        snapshot = {}
        for col in ["ema20", "ema60", "macd", "macd_signal", "macd_hist",
                    "rsi14", "atr14", "bb_upper", "bb_mid", "bb_lower", "adx14", "close",
                    "kdj_k", "kdj_d", "kdj_j", "cci14",
                    "bias6", "bias12", "bias24", "wmsr14"]:
            if col in row.index and pd.notna(row[col]):
                snapshot[col] = round(float(row[col]), 4)
        return snapshot
