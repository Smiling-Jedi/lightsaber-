"""
回测引擎

策略：
  入场：指标信号触发（RSI超卖 / EMA金叉 / 组合信号）
  出场：
    阶段一：价格涨到目标% → 卖出50%，止损上移至入场价
    阶段二：B信号（RSI超买/MACD死叉）或持有期满 → 卖出剩余50%
    止损：价格跌破入场价×(1-stop_pct) → 全仓离场

回测指标输出：
  胜率、期望值EV%、盈亏比、MAE止损建议、Kelly仓位、连续最大亏损
  Walk-Forward验证（前70%训练，后30%验证）
"""
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from app.data_sources.history_source import HistorySource
from app.services.indicator_service import IndicatorService
from config.settings import BACKTEST_DIR

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price_1: float        # 第一半出场价（目标价 or 止损）
    exit_price_2: Optional[float]  # 第二半出场价（None表示止损全仓离场）
    exit_reason_1: str         # TARGET / STOP_LOSS
    exit_reason_2: Optional[str]   # B_SIGNAL / HOLD_PERIOD / None
    pct_1: float               # 第一半收益率
    pct_2: Optional[float]     # 第二半收益率
    combined_pct: float        # 综合收益率
    mae: float                 # 最大不利波动（入场后最大跌幅）


@dataclass
class BacktestStats:
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    ev_pct: float              # 期望值 = 胜率×平均盈 + 亏损率×平均亏
    profit_factor: float       # 盈亏比 = avg_win / |avg_loss|
    max_consecutive_loss: int
    mae_50th: float            # MAE 50th百分位（中位数）
    mae_75th: float            # MAE 75th百分位（建议止损参考）
    kelly_pct: float           # Kelly仓位建议（半Kelly）
    expected_contribution: float  # EV% × Kelly% = 总资产期望贡献


@dataclass
class ParamResult:
    strategy: str
    params: dict
    stats: BacktestStats
    trades: list


@dataclass
class BacktestReport:
    symbol: str
    generated_at: str
    data_start: str
    data_end: str
    total_data_days: int
    best_params: dict          # 最优参数（按EV×Kelly排序）
    param_sweep: list          # 所有参数组合结果
    walk_forward: dict         # Walk-Forward验证结果
    stop_loss_recommendation: dict  # 基于MAE的止损建议


# ─────────────────────────────────────────────────────────
# 回测引擎
# ─────────────────────────────────────────────────────────

class BacktestService:

    # 默认参数矩阵
    RSI_THRESHOLDS = [30, 35, 40]
    TARGET_PCTS = [10, 15, 20, 25, 30]
    HOLD_MONTHS = [3, 6, 9, 12]
    STOP_PCTS = [5, 7, 10]

    # B信号阈值（第二阶段出场）
    RSI_EXIT_THRESHOLD = 70    # RSI超买
    SIGNAL_COOLDOWN = 5        # 信号冷却期（天），避免持仓中重复入场

    def __init__(self):
        self.history_src = HistorySource()
        self.indicator_svc = IndicatorService()

    # ─────────────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────────────

    def run_full_backtest(self, symbol: str, days: int = 2500) -> BacktestReport:
        """
        对单只股票执行完整回测，结果写入 JSON。
        days=2500 约为10年交易日。
        """
        logger.info(f"开始回测: {symbol}，历史数据 {days} 天")

        # 拉取并计算指标
        df = self.history_src.get_history(symbol, days=days, force_refresh=False)
        if df.empty or len(df) < 200:
            raise ValueError(f"历史数据不足，无法回测: {symbol}（{len(df)}条）")

        df = self.indicator_svc.compute_all(df)
        df = df.dropna(subset=["rsi14", "ema20", "ema60", "macd", "macd_signal"])

        data_start = str(df.index[0].date())
        data_end = str(df.index[-1].date())
        logger.info(f"有效数据: {data_start} ~ {data_end}，共 {len(df)} 条")

        # 参数矩阵扫描
        all_results = self._param_sweep(df, symbol)

        # Walk-Forward 验证（前70%训练，后30%验证）
        split = int(len(df) * 0.7)
        df_train = df.iloc[:split]
        df_test = df.iloc[split:]
        wf = self._walk_forward_check(df_train, df_test, symbol)

        # 找最优参数（按期望贡献 EV×Kelly 排序）
        best = self._find_best_params(all_results)

        # 止损建议（基于最优参数的 MAE 分布）
        stop_rec = self._stop_loss_recommendation(all_results, best)

        report = BacktestReport(
            symbol=symbol,
            generated_at=datetime.now().isoformat(),
            data_start=data_start,
            data_end=data_end,
            total_data_days=len(df),
            best_params=best,
            param_sweep=self._serialize_results(all_results),
            walk_forward=wf,
            stop_loss_recommendation=stop_rec,
        )

        self._save_report(symbol, report)
        return report

    def load_report(self, symbol: str) -> Optional[dict]:
        """加载已有回测结果 JSON"""
        path = self._report_path(symbol)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ─────────────────────────────────────────────────────
    # 参数矩阵扫描
    # ─────────────────────────────────────────────────────

    def _param_sweep(self, df: pd.DataFrame, symbol: str) -> list[ParamResult]:
        results = []

        for rsi_entry in self.RSI_THRESHOLDS:
            for target_pct in self.TARGET_PCTS:
                for hold_months in self.HOLD_MONTHS:
                    for stop_pct in self.STOP_PCTS:
                        params = {
                            "strategy": "RSI_oversold",
                            "rsi_entry": rsi_entry,
                            "target_pct": target_pct,
                            "hold_months": hold_months,
                            "stop_pct": stop_pct,
                        }
                        signal_mask = df["rsi14"] < rsi_entry
                        trades = self._simulate_trades(df, signal_mask, params)
                        if len(trades) < 2:
                            continue
                        stats = self._calc_stats(trades)
                        results.append(ParamResult(
                            strategy="RSI_oversold",
                            params=params,
                            stats=stats,
                            trades=[asdict(t) for t in trades],
                        ))

        # EMA 金叉策略
        for target_pct in self.TARGET_PCTS:
            for hold_months in self.HOLD_MONTHS:
                for stop_pct in self.STOP_PCTS:
                    params = {
                        "strategy": "EMA_cross",
                        "target_pct": target_pct,
                        "hold_months": hold_months,
                        "stop_pct": stop_pct,
                    }
                    signal_mask = (
                        (df["ema20"] > df["ema60"]) &
                        (df["ema20"].shift(1) <= df["ema60"].shift(1))
                    )
                    trades = self._simulate_trades(df, signal_mask, params)
                    if len(trades) < 2:
                        continue
                    stats = self._calc_stats(trades)
                    results.append(ParamResult(
                        strategy="EMA_cross",
                        params=params,
                        stats=stats,
                        trades=[asdict(t) for t in trades],
                    ))

        # 组合信号：EMA金叉 + RSI低位
        for rsi_entry in self.RSI_THRESHOLDS:
            for target_pct in self.TARGET_PCTS:
                for hold_months in self.HOLD_MONTHS:
                    for stop_pct in self.STOP_PCTS:
                        params = {
                            "strategy": "EMA_cross+RSI",
                            "rsi_entry": rsi_entry,
                            "target_pct": target_pct,
                            "hold_months": hold_months,
                            "stop_pct": stop_pct,
                        }
                        signal_mask = (
                            (df["ema20"] > df["ema60"]) &
                            (df["ema20"].shift(1) <= df["ema60"].shift(1)) &
                            (df["rsi14"] < rsi_entry)
                        )
                        trades = self._simulate_trades(df, signal_mask, params)
                        if len(trades) < 2:
                            continue
                        stats = self._calc_stats(trades)
                        results.append(ParamResult(
                            strategy="EMA_cross+RSI",
                            params=params,
                            stats=stats,
                            trades=[asdict(t) for t in trades],
                        ))

        logger.info(f"参数扫描完成：{len(results)} 组有效结果")
        return results

    # ─────────────────────────────────────────────────────
    # 核心模拟：两阶段出场
    # ─────────────────────────────────────────────────────

    def _simulate_trades(
        self,
        df: pd.DataFrame,
        signal_mask: pd.Series,
        params: dict,
    ) -> list[TradeRecord]:
        """
        模拟交易：两阶段出场策略
        - 入场：信号次日开盘价
        - 阶段一：价格涨到 target_pct% → 卖出50%，止损上移至入场价
        - 阶段二：B信号（RSI>70或MACD死叉）或持有期满 → 卖出剩余50%
        - 止损：任一阶段价格跌破止损线 → 全仓出场
        """
        target_pct = params["target_pct"] / 100
        stop_pct = params["stop_pct"] / 100
        hold_days = int(params["hold_months"] * 21)  # 约每月21个交易日

        trades = []
        in_position = False
        cooldown = 0
        prices = df["close"].values
        opens = df["open"].values
        rsi = df["rsi14"].values
        macd_hist = df["macd_hist"].values
        signals = signal_mask.values
        dates = df.index

        i = 0
        while i < len(df) - 2:
            # 冷却期
            if cooldown > 0:
                cooldown -= 1
                i += 1
                continue

            if not in_position and signals[i]:
                # 次日开盘入场
                entry_idx = i + 1
                if entry_idx >= len(df):
                    break

                entry_price = opens[entry_idx]
                if entry_price <= 0:
                    i += 1
                    continue

                stop_price = entry_price * (1 - stop_pct)
                target_price = entry_price * (1 + target_pct)
                entry_date = str(dates[entry_idx].date())

                # 记录 MAE（最大不利波动）
                mae = 0.0
                stage1_done = False
                exit_price_1 = None
                exit_reason_1 = None
                exit_price_2 = None
                exit_reason_2 = None

                j = entry_idx + 1
                exit_idx = min(entry_idx + hold_days, len(df) - 1)

                while j <= exit_idx:
                    low = df["low"].values[j]
                    high = df["high"].values[j]
                    close = prices[j]

                    # 更新 MAE
                    drop = (close - entry_price) / entry_price
                    if drop < mae:
                        mae = drop

                    current_stop = stop_price if not stage1_done else entry_price

                    # 止损判断
                    if low <= current_stop:
                        if not stage1_done:
                            # 全仓止损
                            exit_price_1 = current_stop
                            exit_reason_1 = "STOP_LOSS"
                        else:
                            # 第二半止损
                            exit_price_2 = current_stop
                            exit_reason_2 = "STOP_LOSS"
                        break

                    # 第一阶段：涨到目标价
                    if not stage1_done and high >= target_price:
                        exit_price_1 = target_price
                        exit_reason_1 = "TARGET"
                        stage1_done = True
                        # 止损上移至入场价（无风险仓位）
                        # 继续持有第二半

                    # 第二阶段 B 信号（仅在第一阶段完成后）
                    if stage1_done:
                        b_signal = (
                            rsi[j] > self.RSI_EXIT_THRESHOLD or
                            (macd_hist[j] < 0 and macd_hist[j - 1] >= 0)
                        )
                        if b_signal:
                            exit_price_2 = close
                            exit_reason_2 = "B_SIGNAL"
                            break

                    j += 1

                # 持有期满未出场
                if stage1_done and exit_price_2 is None:
                    exit_price_2 = prices[min(j, len(df) - 1)]
                    exit_reason_2 = "HOLD_PERIOD"
                elif not stage1_done and exit_price_1 is None:
                    # 持有期满，第一阶段目标未达到，以收盘价出场
                    exit_price_1 = prices[min(j, len(df) - 1)]
                    exit_reason_1 = "HOLD_PERIOD"

                # 计算收益率
                pct_1 = (exit_price_1 - entry_price) / entry_price
                pct_2 = None
                if stage1_done and exit_price_2 is not None:
                    pct_2 = (exit_price_2 - entry_price) / entry_price
                    combined_pct = (pct_1 + pct_2) / 2
                else:
                    combined_pct = pct_1

                exit_date = str(dates[min(j, len(df) - 1)].date())

                trades.append(TradeRecord(
                    entry_date=entry_date,
                    exit_date=exit_date,
                    entry_price=round(entry_price, 4),
                    exit_price_1=round(exit_price_1, 4),
                    exit_price_2=round(exit_price_2, 4) if exit_price_2 else None,
                    exit_reason_1=exit_reason_1,
                    exit_reason_2=exit_reason_2,
                    pct_1=round(pct_1 * 100, 2),
                    pct_2=round(pct_2 * 100, 2) if pct_2 is not None else None,
                    combined_pct=round(combined_pct * 100, 2),
                    mae=round(mae * 100, 2),
                ))

                cooldown = self.SIGNAL_COOLDOWN
                i = j + 1
                continue

            i += 1

        return trades

    # ─────────────────────────────────────────────────────
    # 统计计算
    # ─────────────────────────────────────────────────────

    def _calc_stats(self, trades: list[TradeRecord]) -> BacktestStats:
        returns = [t.combined_pct for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        maes = [abs(t.mae) for t in trades]

        total = len(returns)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total if total > 0 else 0

        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        ev = win_rate * avg_win + (1 - win_rate) * avg_loss

        profit_factor = avg_win / abs(avg_loss) if avg_loss != 0 and wins else 0.0

        # 最大连续亏损
        max_consec_loss = 0
        cur = 0
        for r in returns:
            if r <= 0:
                cur += 1
                max_consec_loss = max(max_consec_loss, cur)
            else:
                cur = 0

        mae_50 = float(np.percentile(maes, 50)) if maes else 0.0
        mae_75 = float(np.percentile(maes, 75)) if maes else 0.0

        # Kelly 公式（半Kelly）
        kelly_raw = win_rate - (1 - win_rate) / profit_factor if profit_factor > 0 else 0
        kelly = max(0, min(kelly_raw * 0.5, 0.5))  # 半Kelly，上限50%

        expected_contribution = ev * kelly * 100  # 总资产期望贡献（基点）

        return BacktestStats(
            total_trades=total,
            win_trades=win_count,
            loss_trades=loss_count,
            win_rate=round(win_rate, 3),
            avg_win_pct=round(avg_win, 2),
            avg_loss_pct=round(avg_loss, 2),
            ev_pct=round(ev, 2),
            profit_factor=round(profit_factor, 2),
            max_consecutive_loss=max_consec_loss,
            mae_50th=round(mae_50, 2),
            mae_75th=round(mae_75, 2),
            kelly_pct=round(kelly * 100, 1),
            expected_contribution=round(expected_contribution, 3),
        )

    # ─────────────────────────────────────────────────────
    # Walk-Forward 验证
    # ─────────────────────────────────────────────────────

    def _walk_forward_check(
        self, df_train: pd.DataFrame, df_test: pd.DataFrame, symbol: str
    ) -> dict:
        """用训练集找最优RSI参数，在测试集验证"""
        best_params = None
        best_ev = -999

        for rsi_entry in self.RSI_THRESHOLDS:
            for target_pct in [15, 20, 25]:
                params = {
                    "strategy": "RSI_oversold",
                    "rsi_entry": rsi_entry,
                    "target_pct": target_pct,
                    "hold_months": 6,
                    "stop_pct": 7,
                }
                signal_mask = df_train["rsi14"] < rsi_entry
                trades = self._simulate_trades(df_train, signal_mask, params)
                if len(trades) < 3:
                    continue
                stats = self._calc_stats(trades)
                if stats.ev_pct > best_ev:
                    best_ev = stats.ev_pct
                    best_params = params.copy()

        if not best_params:
            return {"status": "insufficient_data"}

        # 在测试集验证
        signal_mask_test = df_test["rsi14"] < best_params["rsi_entry"]
        test_trades = self._simulate_trades(df_test, signal_mask_test, best_params)

        if len(test_trades) < 2:
            return {
                "status": "insufficient_test_data",
                "best_params": best_params,
                "train_ev": round(best_ev, 2),
            }

        test_stats = self._calc_stats(test_trades)
        ev_diff = abs(best_ev - test_stats.ev_pct)
        is_robust = bool(ev_diff < 5.0 and test_stats.ev_pct > 0)  # 误差<5%且测试集正收益

        return {
            "status": "completed",
            "best_params_from_train": best_params,
            "train_ev_pct": round(best_ev, 2),
            "test_ev_pct": round(test_stats.ev_pct, 2),
            "test_win_rate": test_stats.win_rate,
            "test_trades": test_stats.total_trades,
            "ev_diff": round(ev_diff, 2),
            "is_robust": is_robust,
            "conclusion": "参数稳健" if is_robust else "存在过拟合风险，建议保守使用",
        }

    # ─────────────────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────────────────

    @staticmethod
    def _find_best_params(results: list[ParamResult]) -> dict:
        """按期望贡献（EV×Kelly）找最优，要求至少5笔交易"""
        valid = [r for r in results if r.stats.total_trades >= 5]
        if not valid:
            return {}
        best = max(valid, key=lambda r: r.stats.expected_contribution)
        return {
            "strategy": best.strategy,
            "params": best.params,
            "stats": asdict(best.stats),
        }

    @staticmethod
    def _stop_loss_recommendation(results: list[ParamResult], best: dict) -> dict:
        """基于最优参数的 MAE 分布给出止损建议"""
        if not best or not results:
            return {}
        strategy = best.get("strategy", "")
        params = best.get("params", {})
        target = [
            r for r in results
            if r.strategy == strategy
            and r.params.get("rsi_entry") == params.get("rsi_entry")
        ]
        if not target:
            return {}
        best_result = target[0]
        return {
            "mae_50th_pct": best_result.stats.mae_50th,
            "mae_75th_pct": best_result.stats.mae_75th,
            "suggested_stop_pct": round(best_result.stats.mae_75th * 1.2, 1),
            "explanation": (
                f"历史盈利交易中，75%的交易最大回撤不超过 {best_result.stats.mae_75th:.1f}%，"
                f"建议止损设在 -{round(best_result.stats.mae_75th * 1.2, 1)}%（75th百分位+20%缓冲）"
            ),
        }

    @staticmethod
    def _serialize_results(results: list[ParamResult]) -> list[dict]:
        """序列化结果（只保留统计数据，不含每笔交易明细）"""
        output = []
        for r in results:
            output.append({
                "strategy": r.strategy,
                "params": r.params,
                "stats": asdict(r.stats),
            })
        # 按期望贡献倒序排列
        output.sort(key=lambda x: x["stats"]["expected_contribution"], reverse=True)
        return output

    def _report_path(self, symbol: str) -> Path:
        safe = symbol.replace(":", "_")
        return BACKTEST_DIR / f"{safe}_backtest.json"

    def _save_report(self, symbol: str, report: BacktestReport):
        import numpy as np

        class _NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, (np.integer,)):
                    return int(obj)
                if isinstance(obj, (np.floating,)):
                    return float(obj)
                if isinstance(obj, np.bool_):
                    return bool(obj)
                return super().default(obj)

        path = self._report_path(symbol)
        data = asdict(report)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, cls=_NumpyEncoder)
        logger.info(f"回测报告已保存: {path}")
