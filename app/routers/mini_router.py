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
    """基于指标计算综合分析结论"""
    if df.empty or len(df) < 30:
        return {"error": "数据不足"}

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    # EMA趋势判断
    ema_trend = "向上" if latest["ema20"] > latest["ema60"] else "向下"
    ema_golden = latest["ema20"] > latest["ema60"] and prev["ema20"] <= prev["ema60"]
    ema_dead = latest["ema20"] < latest["ema60"] and prev["ema20"] >= prev["ema60"]

    # MACD判断
    macd_bull = latest["macd_hist"] > 0
    macd_strengthen = latest["macd_hist"] > prev["macd_hist"]
    macd_weaken = latest["macd_hist"] < prev["macd_hist"]

    # RSI判断
    rsi = latest["rsi14"]
    rsi_state = "超买" if rsi > 70 else ("超卖" if rsi < 30 else "正常")
    rsi_near_high = 65 <= rsi <= 70
    rsi_near_low = 30 <= rsi <= 35

    # 布林带判断
    bb_pos = "上轨附近" if latest["close"] >= latest["bb_upper"] * 0.995 else (
        "下轨附近" if latest["close"] <= latest["bb_lower"] * 1.005 else "中轨区域"
    )
    bb_break_upper = latest["close"] > latest["bb_upper"]
    bb_break_lower = latest["close"] < latest["bb_lower"]

    # ADX判断
    adx = latest["adx14"]
    trend_strength = "强趋势" if adx > 40 else ("弱趋势" if adx > 20 else "震荡")

    # ATR
    atr = latest["atr14"]
    atr_pct = atr / latest["close"] * 100 if latest["close"] > 0 else 0

    # 综合结论生成
    conclusions = []
    signal = "中性"
    confidence = "medium"

    # 趋势方向
    if ema_trend == "向上" and macd_bull:
        conclusions.append("中期趋势向上，动量偏多")
        signal = "偏多"
    elif ema_trend == "向下" and not macd_bull:
        conclusions.append("中期趋势向下，动量偏空")
        signal = "偏空"
    else:
        conclusions.append("趋势方向不明，动量矛盾")
        signal = "中性"

    # RSI警告
    if rsi > 70:
        conclusions.append(f"RSI={rsi:.1f}，进入超买区，不宜追高")
        confidence = "low"
    elif rsi > 65:
        conclusions.append(f"RSI={rsi:.1f}，接近超买，谨慎加仓")
    elif rsi < 30:
        conclusions.append(f"RSI={rsi:.1f}，进入超卖区，可能有反弹机会")
        confidence = "high"
    elif rsi < 35:
        conclusions.append(f"RSI={rsi:.1f}，接近超卖，可关注")

    # MACD动量
    if macd_strengthen:
        conclusions.append("MACD动量增强，趋势有望延续")
    elif macd_weaken:
        conclusions.append("MACD动量减弱，警惕趋势反转")

    # 布林带
    if bb_break_upper:
        conclusions.append("价格突破布林带上轨，短期偏贵")
    elif bb_break_lower:
        conclusions.append("价格跌破布林带下轨，短期超卖")

    # ADX
    if adx > 40:
        conclusions.append(f"ADX={adx:.1f}，强趋势环境，顺势操作")
    elif adx < 20:
        conclusions.append(f"ADX={adx:.1f}，震荡环境，减少波段操作")

    # OBV 和 VWAP 分析
    obv = latest.get("obv")
    vwap = latest.get("vwap20")
    obv_prev = prev.get("obv") if len(df) >= 2 else obv
    if obv is not None and obv_prev is not None:
        obv_change = obv - obv_prev
        if obv_change > 0:
            conclusions.append("OBV上升，资金流入，量价配合健康")
        elif obv_change < 0:
            conclusions.append("OBV下降，资金流出，警惕量价背离")

    if vwap is not None:
        price_vs_vwap = latest["close"] - vwap
        vwap_pct = price_vs_vwap / vwap * 100 if vwap != 0 else 0
        if abs(vwap_pct) < 1:
            conclusions.append(f"价格接近VWAP({vwap:.2f})，处于机构成本中枢")
        elif vwap_pct > 3:
            conclusions.append(f"价格高于VWAP({vwap:.2f}) {vwap_pct:.1f}%，偏离机构成本")
        elif vwap_pct < -3:
            conclusions.append(f"价格低于VWAP({vwap:.2f}) {abs(vwap_pct):.1f}%，低于机构成本")

    # 最终建议
    if signal == "偏多" and rsi < 70 and not bb_break_upper:
        suggestion = "方向偏多，等待回踩再考虑加仓"
    elif signal == "偏多" and (rsi > 70 or bb_break_upper):
        suggestion = "方向偏多但短期过热，暂缓加仓"
    elif signal == "偏空" and rsi > 30:
        suggestion = "趋势偏弱，观望或减仓"
    elif signal == "偏空" and rsi < 30:
        suggestion = "超跌区域，不宜追空，等企稳"
    else:
        suggestion = "方向不明，观望为主"

    return {
        "ema_trend": ema_trend,
        "ema_golden_cross": ema_golden,
        "ema_dead_cross": ema_dead,
        "macd_bull": macd_bull,
        "macd_strengthen": macd_strengthen,
        "macd_weaken": macd_weaken,
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
        "ema20": round(latest["ema20"], 2),
        "ema60": round(latest["ema60"], 2),
        "macd": round(latest["macd"], 2),
        "macd_hist": round(latest["macd_hist"], 2),
        "bb_upper": round(latest["bb_upper"], 2),
        "bb_mid": round(latest["bb_mid"], 2),
        "bb_lower": round(latest["bb_lower"], 2),
        # v2 新增成交量指标
        "obv": round(latest["obv"], 0) if "obv" in latest and pd.notna(latest["obv"]) else None,
        "vwap20": round(latest["vwap20"], 2) if "vwap20" in latest and pd.notna(latest["vwap20"]) else None,
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
