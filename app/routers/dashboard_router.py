"""
仪表盘路由
"""
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.analysis_service import AnalysisService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    """仪表盘首页 - 显示持仓体检报告"""
    analysis_service = AnalysisService(db)

    # 获取体检报告
    health_report = analysis_service.generate_health_check_report()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "report": health_report
    })


@router.get("/advice/{symbol}")
def stock_advice(symbol: str, request: Request, db: Session = Depends(get_db)):
    """单只股票建议"""
    from app.services.position_service import PositionService

    position_service = PositionService(db)
    analysis_service = AnalysisService(db)

    position = position_service.get_position_by_symbol(symbol)
    if not position:
        return {"error": "持仓不存在"}

    advice = analysis_service.analyze_single_position(position)

    return {
        "symbol": advice.symbol,
        "name": advice.name,
        "action": advice.action,
        "reason": advice.reason,
        "target_price_low": advice.target_price_low,
        "target_price_high": advice.target_price_high,
        "risk_level": advice.risk_level
    }
