"""
趋势交易信号服务

股票分4类，每类使用不同指标组合：
  大市值科技平台：EMA金叉 + MACD + ADX
  周期/行业股：RSI + 布林带 + MACD背离
  防御低波动：布林带 + RSI
  生物医药：RSI极值 + ATR

输出信号包裹：
  action: BUY / SELL / WATCH / HOLD
  confidence: HIGH / MEDIUM（主辅指标全部同向=HIGH，冲突=WATCH）
  触发原因、仓位分析、止损止盈建议、历史回测参考
"""
import json
import logging

import pandas as pd
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.data_sources.history_source import HistorySource
from app.services.indicator_service import IndicatorService
from app.services.position_service import PositionService
from config.settings import BACKTEST_DIR

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 股票分类配置
# ─────────────────────────────────────────────────────────

# 每只股票对应的类别
STOCK_CATEGORY = {
    # 港股
    "HK:00700": "large_tech",   # 腾讯
    "HK:09988": "large_tech",   # 阿里
    "HK:01810": "large_tech",   # 小米
    "HK:03690": "large_tech",   # 美团
    "HK:00175": "cyclical",     # 吉利
    "HK:01888": "cyclical",     # 建滔
    "HK:00270": "defensive",    # 粤海投资
    "HK:01276": "biotech",      # 恒瑞
    "HK:06160": "biotech",      # 百济
    # 美股
    "US:AMZN": "large_tech",    # 亚马逊
    "US:META": "large_tech",    # Meta
    "US:MSFT": "large_tech",    # 微软
    "US:NFLX": "large_tech",    # 奈飞
    "US:NVDA": "large_tech",    # 英伟达
    "US:TSLA": "cyclical",      # 特斯拉
    "US:SOFI": "cyclical",      # SoFi
    "US:UNH":  "defensive",     # 联合健康
    "US:RKLB": "biotech",       # Rocket Lab
    "US:CRCL": "biotech",       # Circle
}

def _load_signal_params():
    """从JSON加载信号参数配置"""
    import json
    from pathlib import Path
    config_path = Path(__file__).parent.parent.parent / "config" / "signal_params.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("stocks", {}), data.get("categories", {}).get("swing_limits", {}), data.get("market_indices", {})
    except Exception as e:
        logger.error(f"加载信号参数配置失败: {e}")
        return {}, {}, {}

STOCK_PARAMS, CATEGORY_SWING_LIMIT, MARKET_INDEX = _load_signal_params()


# ─────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────

@dataclass
class PositionContext:
    """当前仓位上下文"""
    base_shares: int          # 底仓股数
    swing_shares: int         # 波段仓股数
    base_pct: float           # 底仓占总资产%
    swing_pct: float          # 波段仓占总资产%
    total_pct: float          # 合计%
    kelly_limit_pct: float    # 回测建议的Kelly上限%（0=无回测数据）
    available_swing_pct: float  # 可用波段空间%


@dataclass
class SignalResult:
    """单只股票信号输出"""
    symbol: str
    name: str
    category: str
    generated_at: str

    # 信号结论
    action: str               # BUY / SELL / WATCH / HOLD
    confidence: str           # HIGH / MEDIUM / LOW
    summary: str              # 一句话总结

    # 触发原因（列表）
    triggers: list            # 触发的技术条件
    conflicts: list           # 冲突的技术条件（WATCH时有内容）

    # 当前指标快照
    indicators: dict

    # 市场环境
    market_env: str           # BULL / BEAR / NEUTRAL
    market_env_note: str      # 降级说明（如有）

    # 仓位分析
    position: Optional[dict]

    # 止损止盈建议（基于回测结果）
    stop_loss_pct: Optional[float]    # 建议止损%（负数，如-7.5）
    target_pct_1: Optional[float]     # 第一阶段目标%（+15）
    backtest_ref: Optional[dict]      # 回测参考（胜率/EV/Kelly）


# ─────────────────────────────────────────────────────────
# 信号服务
# ─────────────────────────────────────────────────────────

class SignalService:

    def __init__(self, db: Session):
        self.db = db
        self.history_src = HistorySource()
        self.indicator_svc = IndicatorService()
        self.position_svc = PositionService(db)
        self._market_env_cache: dict = {}  # market → (env, note)

    # ─────────────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────────────

    def generate_signal(self, symbol: str) -> SignalResult:
        """对单只股票生成信号包裹"""
        category = STOCK_CATEGORY.get(symbol, "large_tech")

        # 拉历史数据 + 计算指标
        df = self.history_src.get_history(symbol, days=500)
        if df.empty or len(df) < 60:
            return self._insufficient_data_result(symbol, category)

        df = self.indicator_svc.compute_all(df)
        df = df.dropna(subset=["rsi14", "ema20", "ema60"])

        if df.empty:
            return self._insufficient_data_result(symbol, category)

        snap = self.indicator_svc.latest_snapshot(df)

        # 市场环境
        market = symbol.split(":")[0]
        env, env_note = self._check_market_env(market)

        # 分类信号逻辑
        if category == "large_tech":
            action, confidence, triggers, conflicts = self._signal_large_tech(df, snap)
        elif category == "cyclical":
            action, confidence, triggers, conflicts = self._signal_cyclical(df, snap)
        elif category == "defensive":
            action, confidence, triggers, conflicts = self._signal_defensive(df, snap)
        else:  # biotech
            action, confidence, triggers, conflicts = self._signal_biotech(df, snap)

        # 市场环境降级：BUY → WATCH（熊市环境）
        if action == "BUY" and env == "BEAR":
            action = "WATCH"
            env_note = f"原始信号为BUY，因{env_note}，降级为WATCH"

        # 从STOCK_PARAMS读取回测结论参数
        params = STOCK_PARAMS.get(symbol, {})
        kelly_limit = params.get("kelly_pct", 0)
        stop_pct = params.get("stop_pct", -7)
        target_pct = params.get("target_pct", 25)
        wf_robust = params.get("wf_robust", True)

        # WF过拟合股票：BUY信号附加警告
        if action == "BUY" and not wf_robust:
            triggers.append("⚠️ 该股回测WF验证不稳健，建议仓位保守，以基本面判断为主")

        # Kelly=0的股票（样本不足/无数据）：不建议波段
        if action == "BUY" and kelly_limit == 0:
            action = "WATCH"
            triggers.append("⚠️ 回测样本不足，无可靠参数依据，不建议单靠技术信号入场")

        # 仓位上下文
        pos_ctx = self._build_position_context(symbol)

        # 仓位超标时不建议加仓
        if action == "BUY" and pos_ctx and kelly_limit > 0:
            if pos_ctx["total_pct"] >= kelly_limit:
                action = "WATCH"
                triggers.append(f"⚠️ 当前仓位({pos_ctx['total_pct']:.1f}%)已达Kelly上限({kelly_limit:.1f}%)，不建议加仓")

        # 同类集中度检查
        if action == "BUY":
            category_note = self._check_category_concentration(symbol, category)
            if category_note:
                action = "WATCH"
                triggers.append(category_note)

        # 回测参考（合并STOCK_PARAMS + JSON报告）
        backtest_ref = self._load_backtest_ref(symbol) or {}
        backtest_ref.update({
            "kelly_pct": kelly_limit,
            "stop_loss_pct": stop_pct,
            "target_pct_1": target_pct,
            "wf_robust": wf_robust,
            "credibility": STOCK_PARAMS.get(symbol, {}).get("credibility", "LOW"),
        })

        # 股票名称
        name = self._get_stock_name(symbol)

        summary = self._build_summary(action, confidence, triggers, conflicts)

        return SignalResult(
            symbol=symbol,
            name=name,
            category=category,
            generated_at=str(date.today()),
            action=action,
            confidence=confidence,
            summary=summary,
            triggers=triggers,
            conflicts=conflicts,
            indicators=snap,
            market_env=env,
            market_env_note=env_note,
            position=pos_ctx,
            stop_loss_pct=float(stop_pct),
            target_pct_1=float(target_pct),
            backtest_ref=backtest_ref,
        )

    def generate_all_signals(self) -> list[SignalResult]:
        """对所有已知股票生成信号"""
        results = []
        for symbol in STOCK_CATEGORY:
            try:
                result = self.generate_signal(symbol)
                results.append(result)
            except Exception as e:
                logger.error(f"生成信号失败 {symbol}: {e}")
        return results

    def generate_portfolio_signals(self) -> list[SignalResult]:
        """只对持仓中的股票生成信号"""
        positions = self.position_svc.get_all_positions()
        symbols_in_portfolio = {p.stock_symbol for p in positions}
        symbols = [s for s in STOCK_CATEGORY if s in symbols_in_portfolio]

        # 预热市场环境缓存（每个市场只拉一次指数数据）
        for market in {s.split(":")[0] for s in symbols}:
            self._check_market_env(market)

        results = []
        for symbol in symbols:
            try:
                results.append(self.generate_signal(symbol))
            except Exception as e:
                logger.error(f"生成信号失败 {symbol}: {e}")
        return results

    # ─────────────────────────────────────────────────────
    # 各类别信号逻辑
    # ─────────────────────────────────────────────────────

    def _signal_large_tech(self, df, snap):
        """
        大市值科技平台：EMA金叉 + MACD + ADX
        主信号：EMA20 > EMA60（金叉）+ ADX > 25（趋势确认）
        辅助：MACD柱由负转正
        卖出：EMA死叉 OR MACD由正转负且ADX减弱
        """
        triggers = []
        conflicts = []

        ema20 = snap.get("ema20", 0)
        ema60 = snap.get("ema60", 0)
        adx = snap.get("adx14", 0)
        macd_hist = snap.get("macd_hist", 0)
        rsi = snap.get("rsi14", 50)
        close = snap.get("close", 0)

        # 检测金叉/死叉（最近3天）
        recent = df.tail(4)
        ema_cross_up = (
            recent["ema20"].iloc[-1] > recent["ema60"].iloc[-1] and
            recent["ema20"].iloc[-2] <= recent["ema60"].iloc[-2]
        ) if len(recent) >= 2 else False

        ema_cross_down = (
            recent["ema20"].iloc[-1] < recent["ema60"].iloc[-1] and
            recent["ema20"].iloc[-2] >= recent["ema60"].iloc[-2]
        ) if len(recent) >= 2 else False

        macd_turn_positive = (
            recent["macd_hist"].iloc[-1] > 0 and
            recent["macd_hist"].iloc[-2] <= 0
        ) if len(recent) >= 2 else False

        macd_turn_negative = (
            recent["macd_hist"].iloc[-1] < 0 and
            recent["macd_hist"].iloc[-2] >= 0
        ) if len(recent) >= 2 else False

        ema_bullish = ema20 > ema60  # 当前多头排列

        # BUY 逻辑
        buy_primary = ema_cross_up and adx > 25
        buy_aux = macd_turn_positive
        sell_primary = ema_cross_down
        sell_aux = macd_turn_negative and adx < 20

        if buy_primary:
            triggers.append(f"EMA金叉（EMA20={ema20:.2f} 上穿 EMA60={ema60:.2f}）")
        if adx > 25:
            triggers.append(f"ADX={adx:.1f} > 25（趋势强度确认）")
        if buy_aux:
            triggers.append(f"MACD柱由负转正（动能增强）")
        if rsi < 45 and ema_bullish:
            triggers.append(f"RSI={rsi:.1f}（超卖区，加分项）")

        if sell_primary:
            triggers.append(f"EMA死叉（EMA20={ema20:.2f} 下穿 EMA60={ema60:.2f}）")
        if macd_turn_negative:
            triggers.append(f"MACD柱由正转负（动能减弱）")

        # 冲突检测
        if buy_primary and macd_turn_negative:
            conflicts.append("EMA金叉 vs MACD柱转负（方向矛盾）")
        if ema_bullish and macd_turn_negative and adx > 25:
            conflicts.append("趋势向上但动能减弱")

        # 判断action
        if sell_primary and (macd_turn_negative or adx < 20):
            action = "SELL"
            confidence = "HIGH" if sell_primary and sell_aux else "MEDIUM"
        elif sell_primary:
            action = "WATCH"
            confidence = "MEDIUM"
            conflicts.append("EMA死叉但辅助指标未确认")
        elif buy_primary and buy_aux:
            action = "BUY"
            confidence = "HIGH"
        elif buy_primary:
            action = "BUY"
            confidence = "MEDIUM"
        elif conflicts:
            action = "WATCH"
            confidence = "LOW"
        else:
            action = "HOLD"
            confidence = "MEDIUM"
            triggers.append(f"当前：EMA20={'>' if ema20>ema60 else '<'}EMA60，ADX={adx:.1f}，无明显信号")

        # ADX（趋势强度指标）降级：金叉发生时ADX<15说明市场横盘无趋势，大概率是噪音
        # 仅对EMA金叉策略生效，RSI策略（均值回归）在低ADX环境下反而有效
        if action == "BUY" and adx < 15:
            action = "WATCH"
            confidence = "LOW"
            conflicts.append(f"ADX={adx:.1f} < 15（横盘震荡，趋势未确立，金叉可信度低）")

        return action, confidence, triggers, conflicts

    def _signal_cyclical(self, df, snap):
        """
        周期/行业股：RSI + 布林带 + MACD背离
        主信号：RSI < 动态阈值 + 触及布林下轨
        辅助：MACD背离（价格新低但MACD不新低）
        卖出：RSI > 70 OR 价格触及布林上轨
        """
        triggers = []
        conflicts = []

        rsi = snap.get("rsi14", 50)
        close = snap.get("close", 0)
        bb_lower = snap.get("bb_lower", 0)
        bb_upper = snap.get("bb_upper", 0)
        bb_mid = snap.get("bb_mid", 0)
        macd_hist = snap.get("macd_hist", 0)

        # MACD背离检测（价格创近期新低但MACD柱不新低）
        recent = df.tail(20)
        macd_divergence = False
        if len(recent) >= 10:
            price_low_idx = recent["close"].idxmin()
            current_close = recent["close"].iloc[-1]
            # 当前价格接近近20日低点（90%以内）
            near_low = current_close <= recent["close"].min() * 1.05
            if near_low:
                # MACD柱是否高于低点时的值（背离）
                hist_at_low = recent.loc[price_low_idx, "macd_hist"] if price_low_idx in recent.index else 0
                if macd_hist > hist_at_low:
                    macd_divergence = True

        near_bb_lower = close <= bb_lower * 1.02  # 触及或接近下轨（2%内）
        near_bb_upper = close >= bb_upper * 0.98  # 触及或接近上轨
        below_mid = close < bb_mid

        buy_primary = rsi < 40 and near_bb_lower
        buy_aux = macd_divergence
        sell_primary = rsi > 70
        sell_aux = near_bb_upper

        if buy_primary:
            triggers.append(f"RSI={rsi:.1f} < 40（超卖）")
            triggers.append(f"价格触及布林下轨（{bb_lower:.2f}）")
        if buy_aux:
            triggers.append("MACD背离（价格新低但MACD柱底部抬升，潜在反转）")
        if rsi < 35:
            triggers.append(f"RSI极度超卖（{rsi:.1f}），关注反弹")

        if sell_primary:
            triggers.append(f"RSI={rsi:.1f} > 70（超买，波段止盈区间）")
        if sell_aux:
            triggers.append(f"价格触及布林上轨（{bb_upper:.2f}）")

        # 冲突
        if near_bb_lower and sell_primary:
            conflicts.append("价格在布林下轨但RSI超买（数据异常或极端行情）")
        if rsi < 40 and near_bb_upper:
            conflicts.append("RSI超卖但价格在布林上轨（方向矛盾）")

        if conflicts:
            action = "WATCH"
            confidence = "LOW"
        elif sell_primary and sell_aux:
            action = "SELL"
            confidence = "HIGH"
        elif sell_primary:
            action = "SELL"
            confidence = "MEDIUM"
        elif buy_primary and buy_aux:
            action = "BUY"
            confidence = "HIGH"
        elif buy_primary:
            action = "BUY"
            confidence = "MEDIUM"
        else:
            action = "HOLD"
            confidence = "MEDIUM"
            triggers.append(f"RSI={rsi:.1f}，价格在布林带中（{bb_lower:.2f}~{bb_upper:.2f}），无明显信号")

        return action, confidence, triggers, conflicts

    def _signal_defensive(self, df, snap):
        """
        防御低波动股：布林带 + RSI
        主信号：价格偏离布林中轨 + RSI低位
        逻辑简单：低买高卖均值回归
        """
        triggers = []
        conflicts = []

        rsi = snap.get("rsi14", 50)
        close = snap.get("close", 0)
        bb_lower = snap.get("bb_lower", 0)
        bb_upper = snap.get("bb_upper", 0)
        bb_mid = snap.get("bb_mid", 0)

        if bb_mid > 0:
            deviation_pct = (close - bb_mid) / bb_mid * 100
        else:
            deviation_pct = 0

        near_bb_lower = close <= bb_lower * 1.015
        near_bb_upper = close >= bb_upper * 0.985

        buy_primary = near_bb_lower and rsi < 45
        sell_primary = near_bb_upper and rsi > 55

        if buy_primary:
            triggers.append(f"价格接近布林下轨（{close:.2f} vs {bb_lower:.2f}）")
            triggers.append(f"RSI={rsi:.1f}（低位，支持买入）")
        if sell_primary:
            triggers.append(f"价格接近布林上轨（{close:.2f} vs {bb_upper:.2f}）")
            triggers.append(f"RSI={rsi:.1f}（高位，支持卖出）")

        # 冲突
        if near_bb_lower and rsi > 60:
            conflicts.append("价格在布林下轨但RSI偏高")
        if near_bb_upper and rsi < 40:
            conflicts.append("价格在布林上轨但RSI偏低")

        if conflicts:
            action = "WATCH"
            confidence = "LOW"
        elif sell_primary:
            action = "SELL"
            confidence = "HIGH"
        elif buy_primary:
            action = "BUY"
            confidence = "HIGH"
        else:
            action = "HOLD"
            confidence = "MEDIUM"
            triggers.append(
                f"价格在布林带中（偏离中轨{deviation_pct:+.1f}%），RSI={rsi:.1f}，无明显信号"
            )

        return action, confidence, triggers, conflicts

    def _signal_biotech(self, df, snap):
        """
        生物医药（高波动）：RSI极值 + ATR止损参考
        主信号：RSI < 30（极度超卖）
        辅助：ATR判断波动率是否正常（防止数据异常）
        卖出：RSI > 75
        """
        triggers = []
        conflicts = []

        rsi = snap.get("rsi14", 50)
        atr = snap.get("atr14", 0)
        close = snap.get("close", 0)

        # ATR% = ATR / 价格，衡量波动率水平
        atr_pct = atr / close * 100 if close > 0 else 0

        # 历史ATR均值（用于判断当前波动是否异常）
        recent_atr_mean = df["atr14"].tail(60).mean() if "atr14" in df.columns else atr
        atr_elevated = atr > recent_atr_mean * 1.5  # 波动率高于均值150%

        buy_primary = rsi < 30
        sell_primary = rsi > 75

        if buy_primary:
            triggers.append(f"RSI={rsi:.1f} < 30（极度超卖）")
            triggers.append(f"ATR止损参考：入场后止损建议 -{atr_pct:.1f}%~-{atr_pct*1.5:.1f}%")
        if sell_primary:
            triggers.append(f"RSI={rsi:.1f} > 75（超买，波段止盈区间）")

        if atr_elevated:
            conflicts.append(f"当前波动率偏高（ATR={atr:.2f} vs 均值{recent_atr_mean:.2f}），止损需加宽")

        # 生物医药：冲突不影响信号，但降低信心
        if sell_primary:
            action = "SELL"
            confidence = "HIGH"
        elif buy_primary and not atr_elevated:
            action = "BUY"
            confidence = "HIGH"
        elif buy_primary:
            action = "BUY"
            confidence = "MEDIUM"
            # 不设conflicts，但在triggers里说明
        else:
            action = "HOLD"
            confidence = "MEDIUM"
            triggers.append(f"RSI={rsi:.1f}（未达极值），持仓观察")

        return action, confidence, triggers, conflicts

    # ─────────────────────────────────────────────────────
    # 市场环境检测
    # ─────────────────────────────────────────────────────

    def _check_market_env(self, market: str) -> tuple[str, str]:
        """
        检测市场整体趋势。结果在本次请求内缓存，避免同市场重复拉指数。
        返回：(env, note)  env: BULL / BEAR / NEUTRAL
        """
        if market in self._market_env_cache:
            return self._market_env_cache[market]

        yahoo_symbol = MARKET_INDEX.get(market)
        if not yahoo_symbol:
            result = ("NEUTRAL", "")
            self._market_env_cache[market] = result
            return result

        try:
            df = self._fetch_index(yahoo_symbol, days=120)
            if df.empty or len(df) < 60:
                result = ("NEUTRAL", "指数数据不足")
                self._market_env_cache[market] = result
                return result

            df = self.indicator_svc.compute_all(df)
            df = df.dropna(subset=["ema20", "ema60"])
            if df.empty:
                result = ("NEUTRAL", "")
                self._market_env_cache[market] = result
                return result

            snap = self.indicator_svc.latest_snapshot(df)
            ema20 = snap.get("ema20", 0)
            ema60 = snap.get("ema60", 0)

            if ema20 < ema60:
                result = ("BEAR", f"市场指数EMA20({ema20:.0f})<EMA60({ema60:.0f})，处于下跌趋势")
            elif ema20 > ema60 * 1.02:
                result = ("BULL", f"市场指数EMA20({ema20:.0f})>EMA60({ema60:.0f})，处于上升趋势")
            else:
                result = ("NEUTRAL", "市场指数EMA20/60接近，趋势不明确")

            self._market_env_cache[market] = result
            return result

        except Exception as e:
            logger.warning(f"市场环境检测失败 {market}: {e}")
            result = ("NEUTRAL", "环境检测失败")
            self._market_env_cache[market] = result
            return result

    @staticmethod
    def _fetch_index(futu_code: str, days: int = 120):
        """通过富途 OpenD 获取市场指数历史数据"""
        from futu import OpenQuoteContext, KLType, AuType, RET_OK
        from datetime import datetime, timedelta

        start_date = (datetime.today() - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")
        end_date = datetime.today().strftime("%Y-%m-%d")

        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        try:
            ret, data, _ = ctx.request_history_kline(
                futu_code,
                start=start_date,
                end=end_date,
                ktype=KLType.K_DAY,
                autype=AuType.QFQ,
                max_count=1000,
            )
        finally:
            ctx.close()

        if ret != RET_OK or data.empty:
            return pd.DataFrame()

        data["date"] = pd.to_datetime(data["time_key"])
        data = data.set_index("date").sort_index()
        data = data[["open", "high", "low", "close", "volume"]].copy()
        data.index.name = "date"
        return data

    # ─────────────────────────────────────────────────────
    # 仓位上下文
    # ─────────────────────────────────────────────────────

    def _build_position_context(self, symbol: str) -> Optional[dict]:
        """从持仓数据构建仓位上下文"""
        try:
            position = self.position_svc.get_position_by_symbol(symbol)
            if not position:
                return None

            stock = position.stock
            if not stock or not stock.current_price:
                return None

            price = float(stock.current_price)
            portfolio = self.position_svc.get_portfolio_summary()
            total_assets = float(portfolio.get("total_value", 0))
            if total_assets <= 0:
                return None

            base_value = position.base_shares * price
            swing_value = position.swing_shares * price
            base_pct = base_value / total_assets * 100
            swing_pct = swing_value / total_assets * 100
            total_pct = base_pct + swing_pct

            # 从回测结果读取Kelly上限
            kelly_limit = self._get_kelly_limit(symbol)

            available = max(0, kelly_limit - total_pct) if kelly_limit > 0 else 5.0

            return {
                "base_shares": position.base_shares,
                "swing_shares": position.swing_shares,
                "base_pct": round(base_pct, 1),
                "swing_pct": round(swing_pct, 1),
                "total_pct": round(total_pct, 1),
                "kelly_limit_pct": round(kelly_limit, 1),
                "available_swing_pct": round(available, 1),
            }
        except Exception as e:
            logger.warning(f"构建仓位上下文失败 {symbol}: {e}")
            return None

    def _get_kelly_limit(self, symbol: str) -> float:
        """从回测报告读取Kelly仓位建议"""
        ref = self._load_backtest_ref(symbol)
        if ref:
            return ref.get("kelly_pct", 0.0)
        return 0.0

    # ─────────────────────────────────────────────────────
    # 同类集中度检查
    # ─────────────────────────────────────────────────────

    def _check_category_concentration(self, symbol: str, category: str) -> Optional[str]:
        """检查同类股票波段仓位是否超过上限"""
        limit = CATEGORY_SWING_LIMIT.get(category, 0.10)
        same_category = [s for s, c in STOCK_CATEGORY.items() if c == category and s != symbol]

        total_swing_pct = 0.0
        try:
            portfolio = self.position_svc.get_portfolio_summary()
            total_assets = float(portfolio.get("total_value", 0))
            if total_assets <= 0:
                return None

            for s in same_category:
                pos = self.position_svc.get_position_by_symbol(s)
                if pos and pos.stock and pos.stock.current_price:
                    price = float(pos.stock.current_price)
                    swing_value = pos.swing_shares * price
                    total_swing_pct += swing_value / total_assets * 100

        except Exception as e:
            logger.warning(f"同类集中度检查失败: {e}")
            return None

        if total_swing_pct >= limit * 100:
            return f"⚠️ 同类({category})波段仓位已达上限（{total_swing_pct:.1f}% / {limit*100:.0f}%）"
        return None

    # ─────────────────────────────────────────────────────
    # 回测结果引用
    # ─────────────────────────────────────────────────────

    def _load_backtest_ref(self, symbol: str) -> Optional[dict]:
        """加载回测报告，提取关键参考数据"""
        safe = symbol.replace(":", "_")
        path = BACKTEST_DIR / f"{safe}_backtest.json"
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                report = json.load(f)

            best = report.get("best_params", {})
            if not best:
                return None

            stats = best.get("stats", {})
            stop_rec = report.get("stop_loss_recommendation", {})
            params = best.get("params", {})

            return {
                "win_rate": stats.get("win_rate", 0),
                "ev_pct": stats.get("ev_pct", 0),
                "kelly_pct": stats.get("kelly_pct", 0),
                "total_trades": stats.get("total_trades", 0),
                "stop_loss_pct": -abs(stop_rec.get("suggested_stop_pct", 7)),
                "target_pct_1": params.get("target_pct", None),
                "wf_robust": report.get("walk_forward", {}).get("is_robust", None),
                "wf_conclusion": report.get("walk_forward", {}).get("conclusion", ""),
            }
        except Exception as e:
            logger.warning(f"加载回测报告失败 {symbol}: {e}")
            return None

    # ─────────────────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────────────────

    def _get_stock_name(self, symbol: str) -> str:
        try:
            positions = self.position_svc.get_all_positions()
            for p in positions:
                if p.stock_symbol == symbol and p.stock:
                    return p.stock.name
        except Exception:
            pass
        # 默认名称映射
        names = {
            "HK:00700": "腾讯控股",
            "HK:09988": "阿里巴巴",
            "HK:01810": "小米集团",
            "HK:03690": "美团",
            "HK:00175": "吉利汽车",
            "HK:01888": "建滔积层板",
            "HK:00270": "粤海投资",
            "HK:01276": "恒瑞医药",
            "HK:06160": "百济神州",
        }
        return names.get(symbol, symbol)

    def _build_summary(self, action, confidence, triggers, conflicts) -> str:
        action_labels = {
            "BUY": "买入信号",
            "SELL": "卖出信号",
            "WATCH": "观察信号",
            "HOLD": "继续持有",
        }
        conf_labels = {
            "HIGH": "（高信心）",
            "MEDIUM": "（中等信心）",
            "LOW": "（低信心）",
        }
        label = action_labels.get(action, action)
        conf = conf_labels.get(confidence, "")
        if conflicts:
            return f"{label}{conf} — 存在{len(conflicts)}个指标冲突，建议谨慎"
        if triggers:
            return f"{label}{conf} — {triggers[0]}"
        return f"{label}{conf}"

    def _insufficient_data_result(self, symbol: str, category: str) -> SignalResult:
        return SignalResult(
            symbol=symbol,
            name=self._get_stock_name(symbol),
            category=category,
            generated_at=str(date.today()),
            action="HOLD",
            confidence="LOW",
            summary="数据不足，无法生成信号",
            triggers=["历史数据不足60条，跳过信号计算"],
            conflicts=[],
            indicators={},
            market_env="NEUTRAL",
            market_env_note="",
            position=None,
            stop_loss_pct=None,
            target_pct_1=None,
            backtest_ref=None,
        )
