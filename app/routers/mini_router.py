"""
小光剑 (Mini-Lightsaber) 路由

移动端轻量化只读子系统，展示持仓股票的三周期形态分析。

访问地址：/mini/
"""
import json
import logging
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.position import Position
from app.models.stock import Stock
from app.models.pattern_analysis import PatternAnalysis
from app.services.resonance_service import ResonanceService
from app.services.indicator_service import IndicatorService
from app.services.futu_kline_service import FutuKlineService
from app.data_sources.technical_anomaly_source import TechnicalAnomalySource, summarize_patterns
from app.services.fundamental_service import FundamentalService
import pandas as pd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mini")
templates = Jinja2Templates(directory="app/templates")

# 与 main.py 保持一致：注册 fromjson 过滤器，使模板可解析 *_json 字段
templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else {}


@router.get("/")
def mini_home(request: Request, db: Session = Depends(get_db)):
    """
    小光剑首页 — 持仓列表（按市场分Tab）
    """
    # 获取全部持仓
    positions = (
        db.query(Position)
        .filter(Position.total_shares > 0)
        .all()
    )

    # 按市场分组
    market_groups = {"HK": [], "US": [], "A": []}
    for pos in positions:
        market = pos.stock_symbol.split(":")[0] if ":" in pos.stock_symbol else "US"
        stock = db.get(Stock, pos.stock_symbol)

        # 获取最新的形态分析（日/周/月）
        analyses = {}
        for period in ["day", "week", "month"]:
            pa = (
                db.query(PatternAnalysis)
                .filter_by(stock_symbol=pos.stock_symbol, period=period)
                .order_by(PatternAnalysis.analysis_date.desc())
                .first()
            )
            if pa:
                analyses[period] = pa

        # 计算三周期共振
        resonance = None
        if len(analyses) == 3:
            svc = ResonanceService(db)
            resonance = svc.analyze_resonance(pos.stock_symbol)

        # 计算盈亏（用实时加权成本，绕开 avg_cost 字段历史错乱）
        current_price = float(stock.current_price) if stock and stock.current_price else 0
        display_cost = pos.display_avg_cost
        avg_cost = float(display_cost) if display_cost else 0
        pl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

        # 计算仓位占比
        market_value = pos.total_shares * current_price
        market_fund = float(pos.market_total_fund) if pos.market_total_fund else 1
        weight = (market_value / market_fund * 100) if market_fund > 0 else 0

        # 首页扩展字段：置信度评分 / 风险等级 / 共振方向(用于色条)
        confidence = None
        confidence_score = 0.0
        risk_level = None
        direction = "中性"

        day_pa = analyses.get("day")
        if day_pa:
            confidence = day_pa.confidence
            if day_pa.confidence_scores_json:
                try:
                    scores = json.loads(day_pa.confidence_scores_json)
                    fc = float(str(scores.get("form_completeness", "0")).replace("%", ""))
                    vm = float(str(scores.get("volume_match", "0")).replace("%", ""))
                    kld = float(str(scores.get("key_level_distance", "0")).replace("%", ""))
                    confidence_score = round((fc + vm + kld) / 3, 1)
                except (ValueError, KeyError, json.JSONDecodeError):
                    confidence_score = 0.0
            if day_pa.actionable_json:
                try:
                    act = json.loads(day_pa.actionable_json)
                    risk_level = act.get("risk_level")
                except json.JSONDecodeError:
                    pass

        if resonance and resonance.get("resonance"):
            state = resonance["resonance"].get("state", "")
            if "看涨" in state:
                direction = "看涨"
            elif "看跌" in state:
                direction = "看跌"

        card = {
            "symbol": pos.stock_symbol,
            "name": stock.name if stock else pos.stock_symbol,
            "market": market,
            "currency": stock.currency if stock else "",
            "current_price": current_price,
            "prev_close": float(stock.prev_close_price) if stock and stock.prev_close_price else current_price,
            "pl_pct": pl_pct,
            "weight": weight,
            "base_shares": pos.base_shares,
            "base_cost": float(pos.base_cost) if pos.base_cost else 0,
            "swing_shares": pos.swing_shares,
            "swing_cost": float(pos.swing_cost) if pos.swing_cost else 0,
            "analyses": analyses,
            "resonance": resonance,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "risk_level": risk_level,
            "direction": direction,
        }

        if market in market_groups:
            market_groups[market].append(card)

    # 排序：有分析的在前 → 共振强度降序 → 仓位降序
    for market in market_groups:
        market_groups[market].sort(
            key=lambda x: (
                0 if x.get("resonance") else 1,
                -(x["resonance"]["resonance"]["strength"] if x.get("resonance") else 0),
                -x["weight"],
            )
        )

    # 最后更新时间
    last_update = datetime.now().strftime("%m-%d %H:%M")

    return templates.TemplateResponse("mini/home.html", {
        "request": request,
        "market_groups": market_groups,
        "last_update": last_update,
        "title": "小光剑",
    })


@router.get("/stock/{symbol:path}")
def mini_stock_detail(request: Request, symbol: str, db: Session = Depends(get_db)):
    """
    小光剑详情页 — 单只股票完整分析（金字塔5层 + 共振分析）
    """
    # 1. 获取股票和持仓信息
    stock = db.get(Stock, symbol)
    position = (
        db.query(Position)
        .filter_by(stock_symbol=symbol)
        .first()
    )

    # 2. 获取三周期形态分析
    analyses = {}
    for period in ["day", "week", "month"]:
        pa = (
            db.query(PatternAnalysis)
            .filter_by(stock_symbol=symbol, period=period)
            .order_by(PatternAnalysis.analysis_date.desc())
            .first()
        )
        if pa:
            analyses[period] = pa

    # 3. 计算共振
    resonance = None
    if len(analyses) == 3:
        svc = ResonanceService(db)
        resonance = svc.analyze_resonance(symbol)

    # 4. 获取关注事项（未来30天 + 待关注）
    from datetime import timedelta
    from app.models.watch_item import WatchItem

    watch_items = (
        db.query(WatchItem)
        .filter_by(stock_symbol=symbol, status="pending")
        .filter(
            WatchItem.expected_date.is_(None) |
            (WatchItem.expected_date <= date.today() + timedelta(days=30))
        )
        .order_by(WatchItem.expected_date.asc())
        .all()
    )

    # 5. 计算盈亏和仓位（用实时加权成本，绕开 avg_cost 字段历史错乱）
    current_price = float(stock.current_price) if stock and stock.current_price else 0
    prev_close = float(stock.prev_close_price) if stock and stock.prev_close_price else current_price
    display_cost = position.display_avg_cost if position else None
    avg_cost = float(display_cost) if display_cost else 0
    pl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
    market_value = position.total_shares * current_price if position else 0
    market_fund = float(position.market_total_fund) if position and position.market_total_fund else 1
    weight = (market_value / market_fund * 100) if market_fund > 0 else 0

    return templates.TemplateResponse("mini/detail.html", {
        "request": request,
        "symbol": symbol,
        "stock": stock,
        "position": position,
        "analyses": analyses,
        "resonance": resonance,
        "watch_items": watch_items,
        "current_price": current_price,
        "prev_close": prev_close,
        "pl_pct": pl_pct,
        "market_value": market_value,
        "weight": weight,
    })


def _compute_indicator_summary(df: pd.DataFrame) -> dict:
    """基于指标计算三段式综合分析结论"""
    if df.empty or len(df) < 30:
        return {"error": "数据不足"}

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    # ── 基础指标提取 ──
    ema20 = latest["ema20"]
    ema60 = latest["ema60"]
    macd_hist = latest["macd_hist"]
    macd_hist_prev = prev["macd_hist"]
    rsi = latest["rsi14"]
    adx = latest["adx14"]
    bb_upper = latest["bb_upper"]
    bb_lower = latest["bb_lower"]
    close = latest["close"]
    obv = latest.get("obv")
    obv_prev = prev.get("obv") if len(df) >= 2 else obv
    vwap = latest.get("vwap20")

    # ── 布尔状态 ──
    ema_bull = ema20 > ema60
    macd_positive = macd_hist > 0
    macd_expand = macd_hist > macd_hist_prev
    bb_break_upper = close > bb_upper
    bb_break_lower = close < bb_lower
    obv_rise = obv is not None and obv_prev is not None and obv > obv_prev
    obv_fall = obv is not None and obv_prev is not None and obv < obv_prev
    vwap_pct = ((close - vwap) / vwap * 100) if vwap and vwap != 0 else 0

    # ── 兼容字段（供返回用） ──
    ema_trend = "向上" if ema_bull else "向下"
    ema_golden = ema_bull and prev["ema20"] <= prev["ema60"]
    ema_dead = not ema_bull and prev["ema20"] >= prev["ema60"]
    rsi_state = "超买" if rsi > 70 else ("超卖" if rsi < 30 else "正常")
    bb_pos = "上轨附近" if close >= bb_upper * 0.995 else (
        "下轨附近" if close <= bb_lower * 1.005 else "中轨区域"
    )
    trend_strength = "强趋势" if adx > 40 else ("弱趋势" if adx > 20 else "震荡")
    atr = latest["atr14"]
    atr_pct = atr / close * 100 if close > 0 else 0

    # ═══════════════════════════════════════════════
    # 第一段：趋势与强度
    # ═══════════════════════════════════════════════
    trend_parts = []
    trend_parts.append(f"EMA20({'>' if ema_bull else '<'}EMA60)")

    if macd_expand:
        trend_parts.append(f"MACD柱({'+' if macd_hist > 0 else ''}{macd_hist:.2f})扩大")
    elif macd_positive:
        trend_parts.append(f"MACD柱({macd_hist:.2f})为正但收窄")
    else:
        trend_parts.append(f"MACD柱({macd_hist:.2f})为负")

    if adx > 40:
        trend_parts.append(f"ADX={adx:.1f}，趋势极强")
    elif adx > 25:
        trend_parts.append(f"ADX={adx:.1f}，趋势强度中等")
    elif adx >= 20:
        trend_parts.append(f"ADX={adx:.1f}，趋势偏弱")
    else:
        trend_parts.append(f"ADX={adx:.1f}，震荡环境")

    # 精确趋势描述
    if adx < 20:
        if ema_bull and macd_positive:
            trend_summary = "方向偏强，但动能不足，震荡为主"
        elif not ema_bull and not macd_positive:
            trend_summary = "方向偏弱，但动能不足，震荡为主"
        else:
            trend_summary = "趋势动能不足，震荡为主"
    elif ema_bull and macd_positive:
        trend_summary = "中期趋势向上，顺势格局清晰"
    elif ema_bull and not macd_positive:
        trend_summary = "趋势向上但动能在减弱"
    elif not ema_bull and macd_positive:
        trend_summary = "趋势向下但动能在修复"
    else:
        trend_summary = "中期趋势向下，空头格局清晰"

    section1 = "、".join(trend_parts) + "，" + trend_summary

    # ═══════════════════════════════════════════════
    # 第二段：价格风险
    # ═══════════════════════════════════════════════
    risk_parts = []
    if rsi > 70:
        risk_parts.append(f"RSI(14)={rsi:.1f}，超买区间(>70)")
    elif rsi > 65:
        risk_parts.append(f"RSI(14)={rsi:.1f}，接近超买区")
    elif rsi < 30:
        risk_parts.append(f"RSI(14)={rsi:.1f}，超卖区间(<30)")
    elif rsi < 35:
        risk_parts.append(f"RSI(14)={rsi:.1f}，接近超卖区")

    if bb_break_upper:
        risk_parts.append(f"价格({close:.2f})突破布林带上轨({bb_upper:.2f})")
    elif bb_break_lower:
        risk_parts.append(f"价格({close:.2f})跌破布林带下轨({bb_lower:.2f})")

    if abs(vwap_pct) > 3:
        if vwap_pct > 0:
            risk_parts.append(f"高于20日加权均价(VWAP={vwap:.2f}){vwap_pct:.1f}%")
        else:
            risk_parts.append(f"低于20日加权均价(VWAP={vwap:.2f}){abs(vwap_pct):.1f}%")
    elif vwap is not None and abs(vwap_pct) <= 3:
        risk_parts.append(f"接近20日加权均价(VWAP={vwap:.2f})")

    overheat = sum([rsi > 70, bb_break_upper, vwap_pct > 3])
    oversold = sum([rsi < 30, bb_break_lower, vwap_pct < -3])

    if overheat >= 2:
        risk_summary = "短期偏贵，不宜追高"
        confidence = "low"
        signal = "偏空"
    elif overheat == 1:
        risk_summary = "短期有溢价，谨慎追高"
        confidence = "medium"
        signal = "中性"
    elif oversold >= 2:
        risk_summary = "短期超卖，或有反弹机会"
        confidence = "high"
        signal = "偏多"
    elif oversold == 1:
        risk_summary = "短期偏低，可关注"
        confidence = "medium"
        signal = "偏多"
    else:
        risk_summary = "价格处于合理区间"
        confidence = "medium"
        signal = "中性"

    if risk_parts:
        section2 = "、".join(risk_parts) + "，" + risk_summary
    else:
        section2 = risk_summary

    # ═══════════════════════════════════════════════
    # 第三段：量价权衡（场景化描述）
    # ═══════════════════════════════════════════════
    volume_parts = []
    if obv_rise:
        volume_parts.append("OBV上升")
    elif obv_fall:
        volume_parts.append("OBV下降")

    # VWAP偏离（第3段只给定性描述，不重复数值）
    vwap_desc = ""
    if vwap_pct > 3:
        vwap_desc = "价格已大幅偏离均价"
    elif vwap_pct < -3:
        vwap_desc = "价格低于均价"

    # 场景化结论
    if obv_rise and ema_bull and vwap_pct > 3:
        volume_summary = "资金持续追捧推高价格，偏离均价较远，追高风险较大"
    elif obv_rise and not ema_bull and vwap_pct < -3:
        volume_summary = "资金在低位持续流入，或为左侧布局信号，但趋势未扭转前需谨慎"
    elif obv_rise and not ema_bull and abs(vwap_pct) <= 3:
        volume_summary = "资金流入但趋势向下，存在量价背离"
    elif obv_fall and ema_bull and vwap_pct > 3:
        volume_summary = "资金开始撤离但价格仍处高位，风险在积聚"
    elif obv_fall and ema_bull and vwap_pct < -3:
        volume_summary = "资金流出但价格已偏低，或进入洗盘阶段"
    elif obv_fall and not ema_bull and vwap_pct < -3:
        volume_summary = "资金持续撤离，弱势格局未改"
    elif obv_fall and not ema_bull and abs(vwap_pct) <= 3:
        volume_summary = "资金流出配合趋势向下，弱势确认"
    elif obv_rise and ema_bull and abs(vwap_pct) <= 3:
        volume_summary = "资金流入配合趋势向上，量价健康"
    elif obv_fall and ema_bull and abs(vwap_pct) <= 3:
        volume_summary = "价格上涨但资金跟进不足，上涨持续性存疑"
    elif obv_rise and not ema_bull and vwap_pct > 3:
        volume_summary = "资金流入但价格偏高且趋势向下，矛盾信号"
    elif obv_fall and not ema_bull and vwap_pct > 3:
        volume_summary = "资金撤离配合趋势向下且价格偏高，调整压力较大"
    else:
        volume_summary = ""

    if volume_parts and volume_summary:
        section3 = "、".join(volume_parts) + "，" + volume_summary
    elif volume_summary:
        section3 = volume_summary
    else:
        section3 = ""

    # ═══════════════════════════════════════════════
    # 组装结论 + 最终建议
    # ═══════════════════════════════════════════════
    conclusions = [
        f"<b>📈 趋势与强度：</b>{section1}",
        f"<b>⚠️ 价格风险：</b>{section2}",
    ]
    if section3:
        conclusions.append(f"<b>💰 量价权衡：</b>{section3}")

    # ═══════════════════════════════════════════════
    # 最终建议（基于三段综合：趋势+价格+量价）
    # ═══════════════════════════════════════════════

    # 重新计算 signal，基于趋势方向（不被价格风险覆盖）
    if adx < 20:
        trend_signal = "震荡"
    elif ema_bull and macd_positive:
        trend_signal = "偏多"
    elif not ema_bull and not macd_positive:
        trend_signal = "偏空"
    else:
        trend_signal = "矛盾"

    # 量价状态
    volume_health = "健康" if (obv_rise and ema_bull) or (obv_fall and not ema_bull) else (
        "背离" if (obv_rise and not ema_bull) or (obv_fall and ema_bull) else "中性"
    )

    # 建议矩阵
    if trend_signal == "偏多":
        if overheat >= 2:
            suggestion = "趋势向好但短期严重过热，不宜追高，持仓者继续持有"
        elif overheat == 1:
            suggestion = "趋势向好但价格偏高，等待回踩再考虑加仓"
        elif oversold >= 1:
            suggestion = "趋势向好且价格偏低，是较好的加仓机会"
        elif volume_health == "背离":
            suggestion = "趋势向好但资金不配合，上涨持续性存疑，谨慎加仓"
        else:
            suggestion = "趋势向好，量价配合健康，可持仓或逢回调加仓"
    elif trend_signal == "偏空":
        if oversold >= 2:
            suggestion = "趋势偏弱但已超卖，不宜追空，等企稳信号"
        elif oversold == 1:
            suggestion = "趋势偏弱且价格偏低，左侧布局需谨慎"
        elif overheat >= 1:
            suggestion = "趋势向下且价格偏高，减仓为宜"
        elif volume_health == "背离":
            suggestion = "趋势偏弱但有资金在低位流入，关注能否企稳"
        else:
            suggestion = "趋势偏弱，观望或减仓"
    elif trend_signal == "震荡":
        if oversold >= 1:
            suggestion = "震荡环境中价格偏低，可小仓位试探"
        elif overheat >= 1:
            suggestion = "震荡环境中价格偏高，减仓或观望"
        else:
            suggestion = "震荡为主，减少波段操作，观望"
    else:  # 矛盾
        if overheat >= 1:
            suggestion = "动能与趋势方向矛盾且价格偏高，观望为宜"
        elif oversold >= 1:
            suggestion = "动能与趋势方向矛盾但价格偏低，等待方向明朗"
        else:
            suggestion = "动能与趋势方向矛盾，方向不明，观望为主"

    # signal 用于前端兼容性，综合趋势+价格+量价
    if trend_signal == "偏多" and overheat < 2 and volume_health != "背离":
        signal = "偏多"
    elif trend_signal == "偏空" and oversold < 2 and volume_health != "背离":
        signal = "偏空"
    elif oversold >= 2 and trend_signal in ("偏多", "震荡"):
        signal = "偏多"
    elif overheat >= 2 and trend_signal in ("偏空", "震荡"):
        signal = "偏空"
    else:
        signal = "中性"

    return {
        "ema_trend": ema_trend,
        "ema_golden_cross": ema_golden,
        "ema_dead_cross": ema_dead,
        "macd_bull": macd_positive,
        "macd_strengthen": macd_expand,
        "macd_weaken": macd_hist < macd_hist_prev,
        "rsi": round(rsi, 1),
        "rsi_state": rsi_state,
        "bb_position": bb_pos,
        "bb_break_upper": bb_break_upper,
        "bb_break_lower": bb_break_lower,
        "adx": round(adx, 1),
        "trend_strength": trend_strength,
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "conclusions": conclusions,
        "signal": signal,
        "suggestion": suggestion,
        "confidence": confidence,
        # 原始数值
        "ema20": round(ema20, 2),
        "ema60": round(ema60, 2),
        "macd": round(latest["macd"], 2),
        "macd_hist": round(macd_hist, 2),
        "bb_upper": round(bb_upper, 2),
        "bb_mid": round(latest["bb_mid"], 2),
        "bb_lower": round(bb_lower, 2),
        # v2 新增成交量指标
        "obv": round(obv, 0) if obv is not None else None,
        "vwap20": round(vwap, 2) if vwap is not None else None,
    }


@router.get("/v2/stock/{symbol:path}")
def mini_stock_detail_v2(request: Request, symbol: str, db: Session = Depends(get_db)):
    """
    小光剑详情页 v2 — 增加技术指标展示和综合分析
    """
    # 1. 获取股票和持仓信息（与 v1 相同）
    stock = db.get(Stock, symbol)
    position = (
        db.query(Position)
        .filter_by(stock_symbol=symbol)
        .first()
    )

    # 2. 获取三周期形态分析（与 v1 相同）
    from app.models.watch_item import WatchItem
    analyses = {}
    for period in ["day", "week", "month"]:
        pa = (
            db.query(PatternAnalysis)
            .filter_by(stock_symbol=symbol, period=period)
            .order_by(PatternAnalysis.analysis_date.desc())
            .first()
        )
        if pa:
            analyses[period] = pa

    # 3. 计算共振（与 v1 相同）
    resonance = None
    if len(analyses) == 3:
        svc = ResonanceService(db)
        resonance = svc.analyze_resonance(symbol)

    # 4. 获取关注事项（与 v1 相同）
    watch_items = (
        db.query(WatchItem)
        .filter_by(stock_symbol=symbol, status="pending")
        .filter(
            WatchItem.expected_date.is_(None) |
            (WatchItem.expected_date <= date.today() + timedelta(days=30))
        )
        .order_by(WatchItem.expected_date.asc())
        .all()
    )

    # 5. 计算盈亏和仓位（与 v1 相同）
    current_price = float(stock.current_price) if stock and stock.current_price else 0
    prev_close = float(stock.prev_close_price) if stock and stock.prev_close_price else current_price
    display_cost = position.display_avg_cost if position else None
    avg_cost = float(display_cost) if display_cost else 0
    pl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
    market_value = position.total_shares * current_price if position else 0
    market_fund = float(position.market_total_fund) if position and position.market_total_fund else 1
    weight = (market_value / market_fund * 100) if market_fund > 0 else 0

    # 6. v2 新增：计算技术指标
    indicator_summary = None
    try:
        kline_service = FutuKlineService()
        rows = kline_service.get_kline(symbol, count=120, ktype_str="day")
        if rows and len(rows) >= 30:
            df = pd.DataFrame(rows)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            df = df.dropna(subset=["close", "high", "low"])

            if len(df) >= 30:
                ind_service = IndicatorService()
                df = ind_service.compute_all(df)
                indicator_summary = _compute_indicator_summary(df)
    except Exception as e:
        logger.warning(f"指标计算失败 {symbol}: {e}")
        indicator_summary = {"error": str(e)}

    # 7. v2 新增：获取技术异动信号
    anomaly_summary = None
    try:
        anomaly_source = TechnicalAnomalySource()
        anomaly_results = anomaly_source.fetch_all_timeframes(symbol)
        anomaly_summary = summarize_patterns(anomaly_results)
    except Exception as e:
        logger.warning(f"技术异动查询失败 {symbol}: {e}")
        anomaly_summary = {"error": str(e)}

    # 8. v2 新增：获取基本面快照
    fundamental = None
    if stock and stock.name:
        try:
            fund_service = FundamentalService()
            fundamental = fund_service.get_snapshot(symbol, stock.name)
        except Exception as e:
            logger.warning(f"基本面查询失败 {symbol}: {e}")
            fundamental = {"error": str(e)}

    return templates.TemplateResponse("mini-v2/detail.html", {
        "request": request,
        "symbol": symbol,
        "stock": stock,
        "position": position,
        "analyses": analyses,
        "resonance": resonance,
        "watch_items": watch_items,
        "current_price": current_price,
        "prev_close": prev_close,
        "pl_pct": pl_pct,
        "market_value": market_value,
        "weight": weight,
        "indicator_summary": indicator_summary,
        "anomaly_summary": anomaly_summary,
        "fundamental": fundamental,
    })


@router.get("/v2/")
def mini_home_v2(request: Request, db: Session = Depends(get_db)):
    """
    小光剑首页 v2 — 与 v1 相同结构，但链接指向 v2 详情页
    """
    positions = (
        db.query(Position)
        .filter(Position.total_shares > 0)
        .all()
    )

    market_groups = {"HK": [], "US": [], "A": []}
    for pos in positions:
        market = pos.stock_symbol.split(":")[0] if ":" in pos.stock_symbol else "US"
        stock = db.get(Stock, pos.stock_symbol)

        analyses = {}
        for period in ["day", "week", "month"]:
            pa = (
                db.query(PatternAnalysis)
                .filter_by(stock_symbol=pos.stock_symbol, period=period)
                .order_by(PatternAnalysis.analysis_date.desc())
                .first()
            )
            if pa:
                analyses[period] = pa

        resonance = None
        if len(analyses) == 3:
            svc = ResonanceService(db)
            resonance = svc.analyze_resonance(pos.stock_symbol)

        current_price = float(stock.current_price) if stock and stock.current_price else 0
        display_cost = pos.display_avg_cost
        avg_cost = float(display_cost) if display_cost else 0
        pl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

        market_value = pos.total_shares * current_price
        market_fund = float(pos.market_total_fund) if pos.market_total_fund else 1
        weight = (market_value / market_fund * 100) if market_fund > 0 else 0

        confidence = None
        confidence_score = 0.0
        risk_level = None
        direction = "中性"

        day_pa = analyses.get("day")
        if day_pa:
            confidence = day_pa.confidence
            if day_pa.confidence_scores_json:
                try:
                    scores = json.loads(day_pa.confidence_scores_json)
                    fc = float(str(scores.get("form_completeness", "0")).replace("%", ""))
                    vm = float(str(scores.get("volume_match", "0")).replace("%", ""))
                    kld = float(str(scores.get("key_level_distance", "0")).replace("%", ""))
                    confidence_score = round((fc + vm + kld) / 3, 1)
                except (ValueError, KeyError, json.JSONDecodeError):
                    confidence_score = 0.0
            if day_pa.actionable_json:
                try:
                    act = json.loads(day_pa.actionable_json)
                    risk_level = act.get("risk_level")
                except json.JSONDecodeError:
                    pass

        if resonance and resonance.get("resonance"):
            state = resonance["resonance"].get("state", "")
            if "看涨" in state:
                direction = "看涨"
            elif "看跌" in state:
                direction = "看跌"

        card = {
            "symbol": pos.stock_symbol,
            "name": stock.name if stock else pos.stock_symbol,
            "market": market,
            "currency": stock.currency if stock else "",
            "current_price": current_price,
            "prev_close": float(stock.prev_close_price) if stock and stock.prev_close_price else current_price,
            "pl_pct": pl_pct,
            "weight": weight,
            "base_shares": pos.base_shares,
            "base_cost": float(pos.base_cost) if pos.base_cost else 0,
            "swing_shares": pos.swing_shares,
            "swing_cost": float(pos.swing_cost) if pos.swing_cost else 0,
            "analyses": analyses,
            "resonance": resonance,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "risk_level": risk_level,
            "direction": direction,
        }

        if market in market_groups:
            market_groups[market].append(card)

    for market in market_groups:
        market_groups[market].sort(
            key=lambda x: (
                0 if x.get("resonance") else 1,
                -(x["resonance"]["resonance"]["strength"] if x.get("resonance") else 0),
                -x["weight"],
            )
        )

    last_update = datetime.now().strftime("%m-%d %H:%M")

    return templates.TemplateResponse("mini-v2/home.html", {
        "request": request,
        "market_groups": market_groups,
        "last_update": last_update,
        "title": "小光剑 v2",
    })


@router.get("/v3/stock/{symbol:path}")
def mini_stock_detail_v3(request: Request, symbol: str, db: Session = Depends(get_db)):
    """
    小光剑详情页 v3 — 在 v2 基础上增加 #8/#9 优化
    """
    # 1. 获取股票和持仓信息（与 v2 相同）
    stock = db.get(Stock, symbol)
    position = (
        db.query(Position)
        .filter_by(stock_symbol=symbol)
        .first()
    )

    # 2. 获取三周期形态分析（与 v2 相同）
    from app.models.watch_item import WatchItem
    analyses = {}
    for period in ["day", "week", "month"]:
        pa = (
            db.query(PatternAnalysis)
            .filter_by(stock_symbol=symbol, period=period)
            .order_by(PatternAnalysis.analysis_date.desc())
            .first()
        )
        if pa:
            analyses[period] = pa

    # 3. 计算共振（与 v2 相同）
    resonance = None
    if len(analyses) == 3:
        svc = ResonanceService(db)
        resonance = svc.analyze_resonance(symbol)

    # 4. 获取关注事项（与 v2 相同）
    watch_items = (
        db.query(WatchItem)
        .filter_by(stock_symbol=symbol, status="pending")
        .filter(
            WatchItem.expected_date.is_(None) |
            (WatchItem.expected_date <= date.today() + timedelta(days=30))
        )
        .order_by(WatchItem.expected_date.asc())
        .all()
    )

    # 5. 计算盈亏和仓位（与 v2 相同）
    current_price = float(stock.current_price) if stock and stock.current_price else 0
    prev_close = float(stock.prev_close_price) if stock and stock.prev_close_price else current_price
    display_cost = position.display_avg_cost if position else None
    avg_cost = float(display_cost) if display_cost else 0
    pl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
    market_value = position.total_shares * current_price if position else 0
    market_fund = float(position.market_total_fund) if position and position.market_total_fund else 1
    weight = (market_value / market_fund * 100) if market_fund > 0 else 0

    # 6. v3：计算技术指标
    indicator_summary = None
    try:
        kline_service = FutuKlineService()
        rows = kline_service.get_kline(symbol, count=120, ktype_str="day")
        if rows and len(rows) >= 30:
            df = pd.DataFrame(rows)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            df = df.dropna(subset=["close", "high", "low"])

            if len(df) >= 30:
                ind_service = IndicatorService()
                df = ind_service.compute_all(df)
                indicator_summary = _compute_indicator_summary(df)
    except Exception as e:
        logger.warning(f"指标计算失败 {symbol}: {e}")
        indicator_summary = {"error": str(e)}

    # 7. v3：获取技术异动信号
    anomaly_summary = None
    try:
        anomaly_source = TechnicalAnomalySource()
        anomaly_results = anomaly_source.fetch_all_timeframes(symbol)
        anomaly_summary = summarize_patterns(anomaly_results)
    except Exception as e:
        logger.warning(f"技术异动查询失败 {symbol}: {e}")
        anomaly_summary = {"error": str(e)}

    # 8. v3：获取基本面快照
    fundamental = None
    if stock and stock.name:
        try:
            fund_service = FundamentalService()
            fundamental = fund_service.get_snapshot(symbol, stock.name)
        except Exception as e:
            logger.warning(f"基本面查询失败 {symbol}: {e}")
            fundamental = {"error": str(e)}

    return templates.TemplateResponse("mini-v3/detail.html", {
        "request": request,
        "symbol": symbol,
        "stock": stock,
        "position": position,
        "analyses": analyses,
        "resonance": resonance,
        "watch_items": watch_items,
        "current_price": current_price,
        "prev_close": prev_close,
        "pl_pct": pl_pct,
        "market_value": market_value,
        "weight": weight,
        "indicator_summary": indicator_summary,
        "anomaly_summary": anomaly_summary,
        "fundamental": fundamental,
    })


@router.get("/v3/")
def mini_home_v3(request: Request, db: Session = Depends(get_db)):
    """
    小光剑首页 v3 — 链接指向 v3 详情页
    """
    positions = (
        db.query(Position)
        .filter(Position.total_shares > 0)
        .all()
    )

    market_groups = {"HK": [], "US": [], "A": []}
    for pos in positions:
        market = pos.stock_symbol.split(":")[0] if ":" in pos.stock_symbol else "US"
        stock = db.get(Stock, pos.stock_symbol)

        analyses = {}
        for period in ["day", "week", "month"]:
            pa = (
                db.query(PatternAnalysis)
                .filter_by(stock_symbol=pos.stock_symbol, period=period)
                .order_by(PatternAnalysis.analysis_date.desc())
                .first()
            )
            if pa:
                analyses[period] = pa

        resonance = None
        if len(analyses) == 3:
            svc = ResonanceService(db)
            resonance = svc.analyze_resonance(pos.stock_symbol)

        current_price = float(stock.current_price) if stock and stock.current_price else 0
        display_cost = pos.display_avg_cost
        avg_cost = float(display_cost) if display_cost else 0
        pl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

        market_value = pos.total_shares * current_price
        market_fund = float(pos.market_total_fund) if pos.market_total_fund else 1
        weight = (market_value / market_fund * 100) if market_fund > 0 else 0

        confidence = None
        confidence_score = 0.0
        direction = "中性"

        day_pa = analyses.get("day")
        if day_pa:
            confidence = day_pa.confidence
            if day_pa.confidence_scores_json:
                try:
                    scores = json.loads(day_pa.confidence_scores_json)
                    fc = float(str(scores.get("form_completeness", "0")).replace("%", ""))
                    vm = float(str(scores.get("volume_match", "0")).replace("%", ""))
                    kld = float(str(scores.get("key_level_distance", "0")).replace("%", ""))
                    confidence_score = round((fc + vm + kld) / 3, 1)
                except (ValueError, KeyError, json.JSONDecodeError):
                    confidence_score = 0.0

        if resonance and resonance.get("resonance"):
            state = resonance["resonance"].get("state", "")
            if "看涨" in state:
                direction = "看涨"
            elif "看跌" in state:
                direction = "看跌"

        card = {
            "symbol": pos.stock_symbol,
            "name": stock.name if stock else pos.stock_symbol,
            "market": market,
            "currency": stock.currency if stock else "",
            "current_price": current_price,
            "prev_close": float(stock.prev_close_price) if stock and stock.prev_close_price else current_price,
            "pl_pct": pl_pct,
            "weight": weight,
            "base_shares": pos.base_shares,
            "base_cost": float(pos.base_cost) if pos.base_cost else 0,
            "swing_shares": pos.swing_shares,
            "swing_cost": float(pos.swing_cost) if pos.swing_cost else 0,
            "analyses": analyses,
            "resonance": resonance,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "direction": direction,
        }

        if market in market_groups:
            market_groups[market].append(card)

    for market in market_groups:
        market_groups[market].sort(
            key=lambda x: (
                0 if x.get("resonance") else 1,
                -(x["resonance"]["resonance"]["strength"] if x.get("resonance") else 0),
                -x["weight"],
            )
        )

    last_update = datetime.now().strftime("%m-%d %H:%M")

    return templates.TemplateResponse("mini-v3/home.html", {
        "request": request,
        "market_groups": market_groups,
        "last_update": last_update,
        "title": "小光剑 v3",
    })
