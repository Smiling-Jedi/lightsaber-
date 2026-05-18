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
