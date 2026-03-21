"""
持仓管理路由
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import logging
from datetime import datetime

from app.core.database import get_db
from app.services.position_service import PositionService
from app.services.price_service import PriceService
from app.services.news_service import NewsService
from app.services.futu_sync_service import FutuSyncService
from app.services.demo_service import is_demo_mode
from app.fixtures.demo_data import get_demo_portfolio
from app.models.cash import CashBalance

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def positions_list(request: Request, db: Session = Depends(get_db)):
    """持仓列表页"""
    demo = is_demo_mode(request)

    if demo:
        portfolio = get_demo_portfolio()
        last_update = datetime(2026, 3, 21, 15, 54, 0)
        cash_balances = {}
    else:
        # 自动从富途同步最新持仓
        try:
            sync_result = FutuSyncService(db).sync()
            logger.info(f"富途持仓自动同步: {sync_result}")
        except Exception as e:
            logger.warning(f"富途持仓同步失败（页面继续加载）: {e}")

        position_service = PositionService(db)
        price_service = PriceService(db)
        portfolio = position_service.get_portfolio_summary()
        last_update = price_service.get_last_update_time()
        cash_balances = {cb.market: cb for cb in db.query(CashBalance).all()}

    return templates.TemplateResponse("positions.html", {
        "request": request,
        "portfolio": portfolio,
        "last_update": last_update,
        "cash_balances": cash_balances,
        "is_demo": demo,
    })


@router.get("/{symbol}")
def position_detail(symbol: str, request: Request, db: Session = Depends(get_db)):
    """持仓详情页"""
    position_service = PositionService(db)
    news_service = NewsService(db)

    position = position_service.get_position_by_symbol(symbol)
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")

    # 获取持仓摘要
    summary = position_service.get_position_summary(position)

    # 获取相关新闻
    news_list = news_service.get_stock_news(symbol, limit=10)
    news_dicts = [news_service.to_dict(n) for n in news_list]

    return templates.TemplateResponse("detail.html", {
        "request": request,
        "position": summary,
        "news": news_dicts,
        "trades": position.trades
    })
