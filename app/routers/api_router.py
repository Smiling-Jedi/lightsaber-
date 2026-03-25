"""
API 接口路由
用于 AJAX 请求和数据更新
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from typing import Dict, Optional

from app.core.database import get_db
from app.services.demo_service import is_demo_mode, verify_password, COOKIE_NAME
from app.fixtures.demo_data import get_demo_portfolio, get_demo_signals
from app.services.position_service import PositionService
from app.services.price_service import PriceService
from app.services.news_service import NewsService
from app.services.analysis_service import AnalysisService
from app.services.signal_service import SignalService
from app.services.signal_log_service import SignalLogService
from app.services.futu_sync_service import FutuSyncService
from app.services.futu_kline_service import FutuKlineService
from app.services.trade_timeline_service import TradeTimelineService
from app.models.sim_position import SimPosition
from app.models.position import Position
from app.models.stock import Stock
from app.models.cash import CashBalance

router = APIRouter()


# ── 演示模式切换 ──────────────────────────────────────────────

@router.post("/demo/switch")
def demo_switch(request: Request, response: Response, body: dict) -> Dict:
    """
    切换演示/真实模式
    body: {mode: "demo"|"real", password: "..."}
    """
    mode = body.get("mode", "")
    if mode == "demo":
        response.set_cookie(COOKIE_NAME, "demo", max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
        return {"ok": True, "mode": "demo"}
    elif mode == "real":
        if not verify_password(body.get("password", "")):
            return {"ok": False, "error": "密码错误"}
        response.delete_cookie(COOKIE_NAME)
        return {"ok": True, "mode": "real"}
    return {"ok": False, "error": "invalid mode"}


@router.post("/futu/sync")
def futu_sync(db: Session = Depends(get_db)) -> Dict:
    """从富途 OpenD 同步实盘持仓到本地数据库"""
    svc = FutuSyncService(db)
    return svc.sync()


@router.post("/prices/update")
def update_prices(db: Session = Depends(get_db)) -> Dict:
    """
    更新所有股票股价
    """
    price_service = PriceService(db)
    results = price_service.update_all_prices()
    return results


@router.post("/prices/update/{market}")
def update_market_prices(market: str, db: Session = Depends(get_db)) -> Dict:
    """
    按市场更新股价
    market: A, HK, US
    """
    price_service = PriceService(db)
    results = price_service.update_market_prices(market)
    return results


@router.post("/news/update")
def update_news(db: Session = Depends(get_db)) -> Dict:
    """
    更新所有股票新闻
    """
    news_service = NewsService(db)
    results = news_service.fetch_all_news(max_per_stock=5)
    return results


@router.get("/portfolio/summary")
def get_portfolio_summary(request: Request, db: Session = Depends(get_db)) -> Dict:
    """
    获取投资组合汇总
    """
    if is_demo_mode(request):
        portfolio = get_demo_portfolio()
        portfolio["cash_breakdown"] = {
            "HK_FUND": 200000,
            "HK_CASH": 50000,
            "USD_FUND": 100000,
            "USD_CASH": 20000,
            "CNY": 100000
        }
        return portfolio

    position_service = PositionService(db)
    portfolio = position_service.get_portfolio_summary()

    # 添加现金明细
    cash_breakdown = {}
    for cb in db.query(CashBalance).all():
        if cb.market == "FUND":
            cash_breakdown["HK_FUND"] = cash_breakdown.get("HK_FUND", 0) + float(cb.amount)
        elif cb.market == "USD_FUND":
            cash_breakdown["USD_FUND"] = cash_breakdown.get("USD_FUND", 0) + float(cb.amount)
        elif cb.currency == "HKD":
            cash_breakdown["HK_CASH"] = cash_breakdown.get("HK_CASH", 0) + float(cb.amount)
        elif cb.currency == "USD":
            cash_breakdown["USD_CASH"] = cash_breakdown.get("USD_CASH", 0) + float(cb.amount)
        elif cb.currency == "CNY":
            cash_breakdown["CNY"] = cash_breakdown.get("CNY", 0) + float(cb.amount)

    portfolio["cash_breakdown"] = cash_breakdown
    return portfolio


@router.get("/portfolio/advice")
def get_portfolio_advice(db: Session = Depends(get_db)) -> Dict:
    """
    获取投资组合建议
    """
    analysis_service = AnalysisService(db)
    advice = analysis_service.analyze_portfolio()

    return {
        "overall_suggestion": advice.overall_suggestion,
        "risk_warnings": advice.risk_warnings,
        "market_distribution": advice.market_distribution,
        "positions": [
            {
                "symbol": a.symbol,
                "name": a.name,
                "action": a.action,
                "reason": a.reason,
                "target_low": a.target_price_low,
                "target_high": a.target_price_high,
                "risk": a.risk_level
            }
            for a in advice.position_advices
        ]
    }


@router.get("/position/{symbol}/risk")
def check_position_risk(symbol: str, db: Session = Depends(get_db)) -> Dict:
    """
    检查特定持仓风险
    """
    analysis_service = AnalysisService(db)
    return analysis_service.check_position_risk(symbol)


@router.get("/signals/portfolio")
def get_portfolio_signals(request: Request, refresh: bool = False, db: Session = Depends(get_db)) -> Dict:
    """
    对所有持仓股生成趋势信号（分类指标体系）

    Args:
        refresh: 是否强制刷新缓存（默认False），设为True强制重新计算
    """
    if is_demo_mode(request):
        return get_demo_signals()
    signal_service = SignalService(db)
    results = signal_service.generate_portfolio_signals(use_cache=not refresh)
    return {
        "count": len(results),
        "signals": [_format_signal(r) for r in results],
    }


@router.get("/signals/{symbol}/summary")
def get_signal_summary(symbol: str, db: Session = Depends(get_db)) -> Dict:
    """
    生成单只股票的今日小结（LLM生成，当日相同信号缓存复用）
    symbol 格式：HK_00700
    """
    from app.services.signal_summary_service import generate_summary
    symbol = symbol.replace("_", ":") if ":" not in symbol else symbol
    signal_service = SignalService(db)
    result = signal_service.generate_signal(symbol)
    sig_dict = _format_signal(result)
    text = generate_summary(sig_dict)
    return {"symbol": symbol, "summary": text}


@router.get("/signals/{symbol}")
def get_signal(symbol: str, db: Session = Depends(get_db)) -> Dict:
    """
    对单只股票生成趋势信号
    symbol 格式：HK:00700 → 传入时用 HK_00700（URL安全）
    """
    # 支持两种格式：HK_00700 或 HK:00700
    symbol = symbol.replace("_", ":") if ":" not in symbol else symbol
    signal_service = SignalService(db)
    result = signal_service.generate_signal(symbol)
    return _format_signal(result)


def _format_signal(r) -> dict:
    from dataclasses import asdict
    result = asdict(r)
    # 处理TradeInstruction中的嵌套dataclass
    if r.instruction:
        result['instruction'] = asdict(r.instruction)
    return result


# ── 信号日志 ──────────────────────────────────────────────

@router.post("/signals/save")
def save_portfolio_signals(db: Session = Depends(get_db)) -> Dict:
    """生成信号并将 BUY/SELL 自动保存到日志（真实 + 模拟并行）"""
    signal_svc = SignalService(db)
    log_svc = SignalLogService(db)
    results = signal_svc.generate_portfolio_signals()
    saved = []
    saved_sim = []
    for r in results:
        # 真实信号
        log = log_svc.save_signal(r)
        if log:
            saved.append({"id": log.id, "symbol": log.symbol, "action": log.action})
        # 模拟信号（并行触发，自动入场）
        if r.action in ("BUY", "SELL"):
            log_sim = log_svc.save_signal_simulated(r)
            if log_sim:
                saved_sim.append({"id": log_sim.id, "symbol": log_sim.symbol, "action": log_sim.action})
    return {"saved": len(saved), "records": saved, "simulated": len(saved_sim), "sim_records": saved_sim}


@router.get("/signal-logs/pending")
def get_pending_signals(db: Session = Depends(get_db)) -> Dict:
    """获取所有待跟踪信号（已入场、未出场）"""
    log_svc = SignalLogService(db)
    logs = log_svc.get_all_actionable()
    return {"count": len(logs), "logs": [l.to_dict() for l in logs]}


@router.post("/signal-logs/{log_id}/enter")
def mark_entered(log_id: int, entered_price: float, db: Session = Depends(get_db)) -> Dict:
    """标记已按信号入场"""
    if entered_price <= 0:
        raise HTTPException(status_code=422, detail="入场价必须为正数")
    log_svc = SignalLogService(db)
    log = log_svc.mark_entered(log_id, entered_price)
    if not log:
        raise HTTPException(status_code=404, detail="信号记录不存在")
    return log.to_dict()


@router.post("/signal-logs/{log_id}/exit")
def mark_exit(
    log_id: int, exit_price: float, status: str,
    note: str = "", db: Session = Depends(get_db)
) -> Dict:
    """记录出场结果（status: HIT_TARGET / HIT_STOP / EXPIRED / CANCELLED / SKIPPED）"""
    log_svc = SignalLogService(db)
    try:
        log = log_svc.mark_exit(log_id, exit_price, status, note)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not log:
        raise HTTPException(status_code=404, detail="信号记录不存在")
    return log.to_dict()


@router.get("/signal-logs/performance")
def get_performance(symbol: str = None, db: Session = Depends(get_db)) -> Dict:
    """实盘绩效统计（胜率/EV/盈亏比，与回测对比用）"""
    log_svc = SignalLogService(db)
    return log_svc.get_performance(symbol=symbol)


@router.get("/signal-logs/history")
def get_signal_history(symbol: str = None, limit: int = 50, db: Session = Depends(get_db)) -> Dict:
    """历史信号记录"""
    log_svc = SignalLogService(db)
    logs = log_svc.get_history(symbol=symbol, limit=limit)
    return {"count": len(logs), "logs": [l.to_dict() for l in logs]}


@router.get("/news/{symbol}")
def get_stock_news(symbol: str, request: Request, db: Session = Depends(get_db)) -> Dict:
    """
    获取单只股票的 TOP 3 重要资讯（HIGH + MEDIUM）
    symbol 格式：HK_00700 或 HK:00700
    """
    if is_demo_mode(request):
        return {"symbol": symbol, "news": []}
    symbol = symbol.replace("_", ":") if ":" not in symbol else symbol
    news_service = NewsService(db)
    news = news_service.get_top_news(symbol, limit=5)
    return {"symbol": symbol, "news": [news_service.to_dict(n) for n in news]}


@router.get("/stock/{symbol}/kline")
def get_stock_kline(symbol: str, request: Request, db: Session = Depends(get_db)) -> Dict:
    """
    获取个股K线数据（含均线 + 两套交易打点）
    symbol 格式：HK_00700 或 HK:00700
    """
    symbol = symbol.replace("_", ":") if ":" not in symbol else symbol

    if is_demo_mode(request):
        from app.fixtures.demo_data import get_demo_kline
        return get_demo_kline(symbol)

    # K线 + MA
    kline_svc = FutuKlineService()
    kline_data = kline_svc.get_kline(symbol, count=500)

    # 真实成交打点（从 trades 表）
    position = db.query(Position).filter_by(stock_symbol=symbol).first()
    real_trades = []
    if position:
        from app.models.trade import Trade
        trades = db.query(Trade).filter_by(position_id=position.id).order_by(Trade.trade_date).all()
        for t in trades:
            real_trades.append({
                "date":   t.trade_date.isoformat() if t.trade_date else None,
                "type":   t.trade_type,
                "price":  float(t.price) if t.price else None,
                "shares": t.shares,
                "pct":    None,
            })

    # 模拟成交打点（从 signal_logs is_simulated=True）
    from app.models.signal_log import SignalLog
    sim_logs = (
        db.query(SignalLog)
        .filter(
            SignalLog.symbol == symbol,
            SignalLog.is_simulated == True,
            SignalLog.action.in_(["BUY", "SELL"]),
            SignalLog.entered == True,
        )
        .order_by(SignalLog.entered_at)
        .all()
    )
    sim_trades = []
    for log in sim_logs:
        trade_date = (log.entered_at.date() if log.entered_at else
                      log.generated_at.date() if log.generated_at else None)
        sim_trades.append({
            "date":   trade_date.isoformat() if trade_date else None,
            "type":   log.action,
            "price":  log.entered_price or log.entry_price,
            "shares": None,
            "pct":    log.actual_pct,
        })

    return {
        "symbol": symbol,
        "ohlcv":  kline_data,
        "real_trades": real_trades,
        "sim_trades":  sim_trades,
    }


@router.get("/stock/{symbol}/trades")
def get_stock_trades(symbol: str, request: Request, db: Session = Depends(get_db)) -> Dict:
    """
    获取个股交易统计（实盘 + 模拟各自胜率/EV/盈亏比）+ 统一时间轴
    symbol 格式：HK_00700 或 HK:00700
    """
    symbol = symbol.replace("_", ":") if ":" not in symbol else symbol

    if is_demo_mode(request):
        from app.fixtures.demo_data import get_demo_trades
        return get_demo_trades(symbol)

    log_svc = SignalLogService(db)

    real_perf = log_svc.get_performance(symbol=symbol, is_simulated=False)
    sim_perf  = log_svc.get_performance(symbol=symbol, is_simulated=True)

    timeline_svc = TradeTimelineService(db)
    timeline = timeline_svc.get_timeline(symbol)

    return {
        "real": {"stats": real_perf},
        "sim":  {"stats": sim_perf},
        "timeline": timeline["rows"],
    }


@router.get("/stock/{symbol}/positions/compare")
def get_positions_compare(symbol: str, request: Request, db: Session = Depends(get_db)) -> Dict:
    """
    获取实盘 vs 模拟持仓对比数据
    symbol 格式：HK_00700 或 HK:00700
    """
    symbol = symbol.replace("_", ":") if ":" not in symbol else symbol

    if is_demo_mode(request):
        from app.fixtures.demo_data import get_demo_positions_compare
        return get_demo_positions_compare(symbol)

    # 真实持仓
    position = db.query(Position).filter_by(stock_symbol=symbol).first()
    stock = db.get(Stock, symbol)
    current_price = float(stock.current_price) if stock and stock.current_price else 0

    real = None
    if position:
        invested = position.total_shares * float(position.avg_cost or 0)
        market_val = position.total_shares * current_price
        pnl_amount = market_val - invested
        # 负成本（成本已回收）：以市值为基数计算超额收益率，与 calculate_profit_pct 保持一致
        if invested > 0:
            pnl_pct = pnl_amount / invested * 100
        elif market_val > 0:
            pnl_pct = pnl_amount / market_val * 100
        else:
            pnl_pct = 0
        real = {
            "shares":       position.total_shares,
            "avg_cost":     float(position.avg_cost) if position.avg_cost else None,
            "market_value": round(market_val, 2),
            "pnl_amount":   round(pnl_amount, 2),
            "pnl_pct":      round(pnl_pct, 1),
        }

    # 模拟持仓
    sim_pos = db.query(SimPosition).filter_by(symbol=symbol).first()
    sim = None
    if sim_pos:
        invested_sim = (sim_pos.shares or 0) * (sim_pos.avg_cost or 0)
        market_val_sim = (sim_pos.shares or 0) * current_price
        pnl_amount_sim = market_val_sim - invested_sim
        pnl_pct_sim = (pnl_amount_sim / invested_sim * 100) if invested_sim > 0 else 0
        sim = {
            "snapshot_date":    sim_pos.snapshot_date.isoformat() if sim_pos.snapshot_date else None,
            "shares":           sim_pos.shares,
            "avg_cost":         sim_pos.avg_cost,
            "market_value":     round(market_val_sim, 2),
            "pnl_amount":       round(pnl_amount_sim, 2),
            "pnl_pct":          round(pnl_pct_sim, 1),
            "initial_shares":   sim_pos.initial_shares,
            "initial_avg_cost": sim_pos.initial_avg_cost,
            # B+D方案：分批建仓字段
            "batch_status":     sim_pos.batch_status or "IDLE",
            "first_batch_shares": sim_pos.first_batch_shares or 0,
            "first_batch_price": sim_pos.first_batch_price,
            "first_batch_date": sim_pos.first_batch_date.isoformat() if sim_pos.first_batch_date else None,
            "second_batch_pending": sim_pos.second_batch_pending or 0,
        }

    # 现金
    cash_hk = db.get(CashBalance, "HK")
    cash_us = db.get(CashBalance, "US")

    return {
        "symbol":        symbol,
        "current_price": current_price,
        "real":  real,
        "sim":   sim,
        "cash": {
            "HKD": float(cash_hk.amount) if cash_hk else 0,
            "USD": float(cash_us.amount) if cash_us else 0,
        },
    }


@router.get("/exchange_rate/{from_currency}")
def get_exchange_rate(from_currency: str, db: Session = Depends(get_db)) -> Dict:
    """
    获取汇率
    """
    price_service = PriceService(db)
    rate = price_service.get_exchange_rate(from_currency)
    return {
        "from": from_currency,
        "to": "CNY",
        "rate": float(rate)
    }


@router.post("/signals/clear-cache")
def clear_signal_cache(symbol: str = None, db: Session = Depends(get_db)) -> Dict:
    """
    清除信号缓存

    Args:
        symbol: 指定股票代码，None表示清除所有缓存
    """
    from app.services.signal_cache_service import get_signal_cache
    cache = get_signal_cache()
    cache.clear(symbol)
    return {"success": True, "message": f"缓存已清除: {symbol or '全部'}"}
def refresh_report(db: Session = Depends(get_db)) -> Dict:
    """
    刷新持仓体检报告（重新计算所有指标）
    """
    try:
        analysis_service = AnalysisService(db)
        report = analysis_service.generate_health_check_report()
        return {
            "success": True,
            "generated_at": report.get("generated_at"),
            "health_score": report.get("summary", {}).get("health_score"),
            "total_assets": report.get("summary", {}).get("total_assets")
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
