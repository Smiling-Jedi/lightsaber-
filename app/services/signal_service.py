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
from app.services.signal_cache_service import get_signal_cache
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
class TradeInstruction:
    """
    完整交易指令（B+D渐进方案扩展接口）
    为后续表达式方案预留结构，当前阶段逐步启用部分字段
    """
    # 入场条件（当前阶段：硬编码分类规则；未来：表达式）
    entry_condition: str = ""          # 如 "rsi14 < 40 AND close <= bb_lower"
    entry_type: str = "MARKET"         # MARKET / LIMIT / CONDITIONAL

    # 仓位模型（多模型支持）
    sizing_model: str = "KELLY_HALF"   # KELLY_HALF / FIXED_RISK / VOLATILITY_ADJUSTED
    sizing_params: dict = None         # 模型参数

    # 出场条件
    stop_condition: str = ""           # 如 "close < entry_price * 0.93" 或 ATR-based
    profit_conditions: list = None     # [{"condition": "rsi14 > 70", "pct": 50}]

    # 执行偏好
    execution_style: str = "SINGLE"    # SINGLE / TWAP / BATCH（分批建仓）
    time_limit_days: int = 3           # 指令有效期

    # 优先级评分（多信号排序用）
    priority_score: float = 0.0        # EV加权综合评分

    # 具体交易建议（基于当前持仓和资产计算）
    recommended_shares: int = 0        # 建议买入股数（第一批）
    recommended_shares_second: int = 0 # 建议买入股数（第二批，分批建仓）
    entry_price_reference: float = 0.0 # 参考入场价（最新收盘价）
    position_value_estimated: float = 0.0  # 预计占用资金

    def __post_init__(self):
        if self.sizing_params is None:
            self.sizing_params = {}
        if self.profit_conditions is None:
            self.profit_conditions = []


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

    # B+D方案：完整交易指令（新增）
    instruction: Optional[TradeInstruction] = None  # 交易执行指令


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

    def _generate_signal_internal(self, symbol: str) -> SignalResult:
        """
        内部信号生成方法（不含缓存逻辑，供批量调用）
        """
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

        # B+D方案：ATR动态止损（2×ATR，14日周期）
        atr14 = snap.get("atr14", 0)
        close_price = snap.get("close", 0)
        if atr14 > 0 and close_price > 0:
            atr_stop_pct = -round(atr14 * 2 / close_price * 100, 1)  # 2×ATR作为止损
            # 取ATR止损和固定止损中更保守（更负）的一个
            stop_pct = min(stop_pct, atr_stop_pct)

        # B+D方案：多模型仓位计算参数
        sizing_model = params.get("sizing_model", "KELLY_HALF")
        sizing_params = self._build_sizing_params(params, snap, kelly_limit)

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
            "kelly_pct":     kelly_limit,
            "stop_loss_pct": stop_pct,
            "target_pct_1":  target_pct,
            "hold_months":   STOCK_PARAMS.get(symbol, {}).get("hold_months"),
            "wf_robust":     wf_robust,
            "credibility":   STOCK_PARAMS.get(symbol, {}).get("credibility", "LOW"),
        })

        # 股票名称
        name = self._get_stock_name(symbol)

        summary = self._build_summary(action, confidence, triggers, conflicts)

        # B+D方案：构建TradeInstruction
        instruction = self._build_trade_instruction(
            symbol=symbol,
            action=action,
            sizing_model=sizing_model,
            sizing_params=sizing_params,
            stop_pct=stop_pct,
            target_pct=target_pct,
            snap=snap,
            backtest_ref=backtest_ref,
        )

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
            instruction=instruction,
        )

    def generate_signal(self, symbol: str, use_cache: bool = True) -> SignalResult:
        """
        对单只股票生成信号包裹

        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存（默认True），设为False强制重新计算
        """
        # 检查缓存
        if use_cache:
            cache = get_signal_cache()
            cached_result = cache.get(symbol)
            if cached_result is not None:
                logger.debug(f"信号缓存命中: {symbol}")
                return cached_result

        # 生成信号
        result = self._generate_signal_internal(symbol)

        # 保存到缓存
        if use_cache:
            cache = get_signal_cache()
            cache.set(symbol, result)

        return result

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

    def generate_portfolio_signals(self, use_cache: bool = True) -> list[SignalResult]:
        """
        只对持仓中的股票生成信号（B+D方案：按EV排序）

        Args:
            use_cache: 是否使用缓存（默认True），设为False强制重新计算
        """
        positions = self.position_svc.get_all_positions()
        symbols_in_portfolio = {p.stock_symbol for p in positions}
        symbols = [s for s in STOCK_CATEGORY if s in symbols_in_portfolio]

        if not symbols:
            return []

        # 预热市场环境缓存（每个市场只拉一次指数数据）
        for market in {s.split(":")[0] for s in symbols}:
            self._check_market_env(market)

        results = []
        symbols_to_generate = []

        if use_cache:
            # 批量检查缓存
            cache = get_signal_cache()
            cached_results = cache.get_portfolio_cache(symbols)

            for symbol in symbols:
                if symbol in cached_results:
                    results.append(cached_results[symbol])
                    logger.debug(f"批量缓存命中: {symbol}")
                else:
                    symbols_to_generate.append(symbol)
        else:
            symbols_to_generate = symbols

        # 生成未缓存的信号
        new_results = []
        for symbol in symbols_to_generate:
            try:
                result = self._generate_signal_internal(symbol)
                new_results.append(result)
                results.append(result)
            except Exception as e:
                logger.error(f"生成信号失败 {symbol}: {e}")

        # 批量保存新结果到缓存
        if use_cache and new_results:
            cache = get_signal_cache()
            cache.set_portfolio_cache(new_results)
            logger.info(f"批量缓存已保存: {len(new_results)} 个信号")

        # B+D方案：多信号按EV排序（高EV优先）
        results = self._sort_by_ev_priority(results)
        return results

    def _sort_by_ev_priority(self, results: list[SignalResult]) -> list[SignalResult]:
        """
        B+D方案：多信号排序
        权重：EV(40%) + Kelly(30%) + 信心度(20%) + 市场环境(10%)
        BUY信号优先于WATCH/HOLD
        """
        def priority_key(r: SignalResult) -> tuple:
            # BUY信号优先
            is_buy = 1 if r.action == "BUY" else 0

            # 计算优先级得分
            ev = r.backtest_ref.get("ev_pct", 0) if r.backtest_ref else 0
            kelly = r.backtest_ref.get("kelly_pct", 0) if r.backtest_ref else 0

            # 信心度映射
            conf_map = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}
            conf_score = conf_map.get(r.confidence, 0.5)

            # 市场环境映射
            env_map = {"BULL": 1.0, "NEUTRAL": 0.7, "BEAR": 0.4}
            env_score = env_map.get(r.market_env, 0.7)

            # 加权得分
            score = (ev * 0.4) + (kelly * 0.3) + (conf_score * 20 * 0.2) + (env_score * 10 * 0.1)

            return (is_buy, score)

        return sorted(results, key=priority_key, reverse=True)

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
            instruction=None,
        )

    # ─────────────────────────────────────────────────────
    # B+D方案：多模型仓位计算与TradeInstruction构建
    # ─────────────────────────────────────────────────────

    def _build_sizing_params(self, params: dict, snap: dict, kelly_limit: float) -> dict:
        """
        构建多模型仓位参数
        支持：KELLY_HALF / FIXED_RISK / VOLATILITY_ADJUSTED
        """
        atr14 = snap.get("atr14", 0)
        close_price = snap.get("close", 0)

        sizing_params = {
            "kelly_pct": kelly_limit,
            "atr14": atr14,
            "close": close_price,
        }

        # FIXED_RISK模型参数：固定风险金额 / ATR
        if atr14 > 0:
            # 假设账户100万，每笔风险1% = 1万，仓位 = 1万 / (2×ATR)
            fixed_risk_amount = 10000  # 固定风险金额1万
            risk_per_share = atr14 * 2  # 2×ATR作为每股风险
            fixed_risk_shares = int(fixed_risk_amount / risk_per_share)
            sizing_params["fixed_risk_shares"] = fixed_risk_shares
            sizing_params["risk_per_share"] = risk_per_share

        # VOLATILITY_ADJUSTED模型参数：波动率越高，仓位越低
        if close_price > 0 and atr14 > 0:
            atr_pct = atr14 / close_price
            # 基准波动率5%，仓位与波动率成反比
            vol_factor = max(0.3, min(1.0, 0.05 / atr_pct))
            sizing_params["volatility_factor"] = round(vol_factor, 2)
            sizing_params["vol_adjusted_pct"] = round(kelly_limit * vol_factor, 1)

        return sizing_params

    def _build_trade_instruction(
        self,
        symbol: str,
        action: str,
        sizing_model: str,
        sizing_params: dict,
        stop_pct: float,
        target_pct: float,
        snap: dict,
        backtest_ref: dict,
    ) -> Optional[TradeInstruction]:
        """
        构建完整交易指令（B+D方案核心扩展接口）
        当前阶段实现：分批建仓 + ATR止损 + 多模型参数 + 具体股数计算
        未来阶段扩展：条件表达式解析
        """
        if action not in ("BUY", "SELL"):
            return None

        # 计算优先级得分（用于多信号排序）
        ev = backtest_ref.get("ev_pct", 0) if backtest_ref else 0
        kelly = backtest_ref.get("kelly_pct", 0) if backtest_ref else 0
        priority_score = ev * 0.4 + kelly * 0.3

        # 入场条件（当前硬编码，未来扩展为表达式）
        category = STOCK_CATEGORY.get(symbol, "large_tech")
        entry_conditions = {
            "large_tech": "ema_cross_up AND adx > 25",
            "cyclical": "rsi14 < 40 AND close <= bb_lower",
            "defensive": "close <= bb_lower * 1.015 AND rsi14 < 45",
            "biotech": "rsi14 < 30",
        }

        # 止损条件：使用ATR动态止损
        atr14 = snap.get("atr14", 0)
        stop_condition = f"fixed_stop_{stop_pct}%"
        if atr14 > 0:
            stop_condition = f"atr_based_2x_atr14"

        # 获取最新价格
        close_price = snap.get("close", 0)

        # 计算建议买入股数
        recommended_shares = 0
        recommended_shares_second = 0
        position_value = 0.0

        if action == "BUY" and close_price > 0:
            recommended_shares, recommended_shares_second, position_value = self._calculate_shares(
                symbol=symbol,
                sizing_model=sizing_model,
                sizing_params=sizing_params,
                close_price=close_price,
            )

        instruction = TradeInstruction(
            entry_condition=entry_conditions.get(category, ""),
            entry_type="MARKET" if action == "BUY" else "MARKET",
            sizing_model=sizing_model,
            sizing_params=sizing_params,
            stop_condition=stop_condition,
            profit_conditions=[
                {"condition": f"target_{target_pct}%", "pct": 100}
            ],
            execution_style="BATCH" if action == "BUY" else "SINGLE",  # 分批建仓
            time_limit_days=3,
            priority_score=round(priority_score, 2),
            # 具体交易建议
            recommended_shares=recommended_shares,
            recommended_shares_second=recommended_shares_second,
            entry_price_reference=round(close_price, 2) if close_price else 0.0,
            position_value_estimated=round(position_value, 2),
        )

        return instruction

    def _calculate_shares(
        self,
        symbol: str,
        sizing_model: str,
        sizing_params: dict,
        close_price: float,
    ) -> tuple[int, int, float]:
        """
        计算建议买入股数

        返回: (第一批股数, 第二批股数, 预计占用资金)
        """
        try:
            # 获取当前仓位上下文
            pos_ctx = self._build_position_context(symbol)

            # 可用波段空间（%）
            if pos_ctx:
                # 有持仓：按剩余可用空间计算
                available_pct = pos_ctx.get("available_swing_pct", 0)
            else:
                # 无持仓：按完整 Kelly 上限计算
                available_pct = sizing_params.get("kelly_pct", 0)

            if available_pct <= 0:
                return 0, 0, 0.0

            # 获取总资产（本市场）
            portfolio = self.position_svc.get_portfolio_summary()
            market = symbol.split(":")[0]
            market_data = portfolio.get("markets", {}).get(market, {})
            total_assets = market_data.get("total_with_cash", 0)

            if total_assets <= 0:
                return 0, 0, 0.0

            # 可用资金金额
            available_amount = total_assets * available_pct / 100

            # 根据仓位模型调整
            if sizing_model == "FIXED_RISK":
                # 固定风险模型：直接使用预计算股数
                shares = sizing_params.get("fixed_risk_shares", 0)
            elif sizing_model == "VOLATILITY_ADJUSTED":
                # 波动率调整：Kelly * 波动率因子
                vol_factor = sizing_params.get("volatility_factor", 0.7)
                adjusted_amount = available_amount * vol_factor
                shares = int(adjusted_amount / close_price)
            else:
                # 默认 KELLY_HALF：可用空间的一半作为第一批
                # B+D方案：分两批，第一批用可用空间的50%
                first_batch_amount = available_amount * 0.5
                shares = int(first_batch_amount / close_price)

            if shares <= 0:
                return 0, 0, 0.0

            # 第二批股数（B+D方案：与第一批相同，等待回调或确认后买入）
            shares_second = shares

            # 预计占用资金（两批合计）
            total_value = (shares + shares_second) * close_price

            return shares, shares_second, total_value

        except Exception as e:
            logger.warning(f"计算建议股数失败 {symbol}: {e}")
            return 0, 0, 0.0
