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
        return get_demo_portfolio()
    position_service = PositionService(db)
    return position_service.get_portfolio_summary()


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
def get_portfolio_signals(request: Request, db: Session = Depends(get_db)) -> Dict:
    """
    对所有持仓股生成趋势信号（分类指标体系）
    """
    if is_demo_mode(request):
        return get_demo_signals()
    signal_service = SignalService(db)
    results = signal_service.generate_portfolio_signals()
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
    return asdict(r)


# ── 信号日志 ──────────────────────────────────────────────

@router.post("/signals/save")
def save_portfolio_signals(db: Session = Depends(get_db)) -> Dict:
    """生成信号并将 BUY/SELL 自动保存到日志"""
    signal_svc = SignalService(db)
    log_svc = SignalLogService(db)
    results = signal_svc.generate_portfolio_signals()
    saved = []
    for r in results:
        log = log_svc.save_signal(r)
        if log:
            saved.append({"id": log.id, "symbol": log.symbol, "action": log.action})
    return {"saved": len(saved), "records": saved}


@router.get("/signal-logs/pending")
def get_pending_signals(db: Session = Depends(get_db)) -> Dict:
    """获取所有待跟踪信号（已入场、未出场）"""
    log_svc = SignalLogService(db)
    logs = log_svc.get_all_actionable()
    return {"count": len(logs), "logs": [l.to_dict() for l in logs]}


@router.post("/signal-logs/{log_id}/enter")
def mark_entered(log_id: int, entered_price: float, db: Session = Depends(get_db)) -> Dict:
    """标记已按信号入场"""
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
    log = log_svc.mark_exit(log_id, exit_price, status, note)
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
