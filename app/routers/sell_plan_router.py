"""
卖出计划路由
"""
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.sell_plan_service import SellPlanService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def sell_plan_list(request: Request, db: Session = Depends(get_db)):
    """卖出计划列表页"""
    from app.models.sell_plan import SellPlan
    from app.models.stock import Stock

    try:
        service = SellPlanService(db)
        plans = service.list_plans(limit=100)

        # 构建列表数据
        plan_list = []
        for plan in plans:
            # 获取股票名称
            stock = db.query(Stock).filter(Stock.symbol == plan.symbol).first()
            stock_name = stock.name if stock else plan.symbol

            plan_list.append({
                "id": plan.id,
                "symbol": plan.symbol,
                "stock_name": stock_name,
                "planned_shares": plan.planned_shares,
                "planned_price": float(plan.planned_price) if plan.planned_price else None,
                "estimated_profit_pct": float(plan.estimated_profit_pct) if plan.estimated_profit_pct else None,
                "sell_type": plan.sell_type,
                "status": plan.status,
                "created_at": plan.created_at,
            })

        return templates.TemplateResponse("sell_plan_list.html", {
            "request": request,
            "plans": plan_list,
            "active_page": "sells"
        })
    except Exception as e:
        import traceback
        error_msg = str(e) + "\n" + traceback.format_exc()[:500]
        return templates.TemplateResponse("sell_plan_list.html", {
            "request": request,
            "plans": [],
            "error": error_msg,
            "active_page": "sells"
        })


@router.get("/new")
def sell_plan_new(request: Request, position_id: Optional[int] = None, trade_id: Optional[int] = None, db: Session = Depends(get_db)):
    """新建卖出计划页"""
    from app.models.position import Position
    from app.models.trade_plan import TradePlan
    from app.models.trade import Trade

    service = SellPlanService(db)

    # 默认数据
    default_data = {}
    buy_plans = []
    mode = "新建"

    # 如果指定了持仓，预填充数据
    if position_id:
        position = db.query(Position).filter(Position.id == position_id).first()
        if position:
            symbol = position.stock_symbol
            default_data = {
                "symbol": symbol,
                "market": symbol.split(":")[0] if ":" in symbol else "A",
                "current_shares": position.total_shares,
            }

            # 获取该股票的买入计划供选择
            buy_plans = db.query(TradePlan).filter(
                TradePlan.symbol == symbol,
                TradePlan.status.in_(["计划中", "已执行"])
            ).order_by(TradePlan.created_at.desc()).all()

    # 如果是补录模式（从交易记录），从卖出交易预填充数据
    if trade_id:
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if trade and trade.trade_type == "SELL":
            position = trade.position
            symbol = position.stock_symbol if position else ""
            default_data = {
                "symbol": symbol,
                "market": symbol.split(":")[0] if ":" in symbol else "A",
                "planned_price": float(trade.price) if trade.price else 0,
                "planned_shares": trade.shares,
            }
            mode = "补录"

            # 获取该股票的买入计划供选择
            if symbol:
                buy_plans = db.query(TradePlan).filter(
                    TradePlan.symbol == symbol,
                    TradePlan.status.in_(["计划中", "已执行"])
                ).order_by(TradePlan.created_at.desc()).all()

    return templates.TemplateResponse("sell_plan_form.html", {
        "request": request,
        "default_data": default_data,
        "buy_plans": buy_plans,
        "trigger_methods": service.SELL_TRIGGER_METHODS,
        "active_page": "sells",
        "mode": mode
    })


@router.post("/api/evaluate")
def api_evaluate_sell_plan(
    symbol: str = Form(...),
    buy_plan_id: str = Form(None),
    planned_price: str = Form(None),
    planned_shares: int = Form(...),
    sell_trigger_method: str = Form(...),
    sell_trigger_param: str = Form(...),
    original_target_price: str = Form(None),
    sell_reason: str = Form(...),
    note: str = Form(None),
    db: Session = Depends(get_db)
):
    """评估卖出计划（不保存）"""
    service = SellPlanService(db)

    # 参数验证
    errors = []

    if not symbol or not symbol.strip():
        errors.append("股票代码不能为空")

    # 解析计划卖出价
    try:
        planned_price_val = float(planned_price) if planned_price else 0
    except (ValueError, TypeError):
        planned_price_val = 0

    # 解析原目标价
    try:
        original_target_val = float(original_target_price) if original_target_price else 0
    except (ValueError, TypeError):
        original_target_val = 0

    # 解析买入计划ID
    try:
        buy_plan_id_val = int(buy_plan_id) if buy_plan_id else None
    except (ValueError, TypeError):
        buy_plan_id_val = None

    # 解析触发参数
    try:
        trigger_param_val = float(sell_trigger_param) if sell_trigger_param else 0
    except (ValueError, TypeError):
        trigger_param_val = 0

    # 卖出理由必填检查（最少10字）
    if not sell_reason or not sell_reason.strip():
        errors.append("卖出理由不能为空")
    elif len(sell_reason.strip()) < 10:
        errors.append("卖出理由最少需要10个字")

    # 如果有验证错误，返回错误响应
    if errors:
        return {
            "error": "表单验证失败",
            "messages": errors,
            "evaluation": {
                "overall": "信息不完整",
                "overall_code": "red",
                "checks": [
                    {
                        "item": "表单填写",
                        "status": "fail",
                        "message": "；".join(errors)
                    }
                ],
            }
        }

    data = {
        "symbol": symbol,
        "buy_plan_id": buy_plan_id_val,
        "planned_price": planned_price_val,
        "planned_shares": planned_shares,
        "sell_trigger_method": sell_trigger_method,
        "sell_trigger_param": trigger_param_val,
        "original_target_price": original_target_val,
        "sell_reason": sell_reason,
        "note": note,
    }

    result = service.evaluate_plan(data)
    return result


@router.post("/api")
def api_create_sell_plan(
    request: Request,
    symbol: str = Form(...),
    buy_plan_id: str = Form(None),
    planned_price: str = Form(None),
    planned_shares: int = Form(...),
    sell_trigger_method: str = Form(...),
    sell_trigger_param: str = Form(...),
    original_target_price: str = Form(None),
    sell_reason: str = Form(...),
    note: str = Form(None),
    db: Session = Depends(get_db)
):
    """创建卖出计划"""
    service = SellPlanService(db)

    # 参数验证（同evaluate）
    errors = []

    if not symbol or not symbol.strip():
        errors.append("股票代码不能为空")

    try:
        planned_price_val = float(planned_price) if planned_price else 0
    except (ValueError, TypeError):
        planned_price_val = 0

    try:
        original_target_val = float(original_target_price) if original_target_price else 0
    except (ValueError, TypeError):
        original_target_val = 0

    try:
        buy_plan_id_val = int(buy_plan_id) if buy_plan_id else None
    except (ValueError, TypeError):
        buy_plan_id_val = None

    try:
        trigger_param_val = float(sell_trigger_param) if sell_trigger_param else 0
    except (ValueError, TypeError):
        trigger_param_val = 0

    if not sell_reason or not sell_reason.strip():
        errors.append("卖出理由不能为空")
    elif len(sell_reason.strip()) < 10:
        errors.append("卖出理由最少需要10个字")

    if errors:
        return templates.TemplateResponse("sell_plan_form.html", {
            "request": request,
            "default_data": {"symbol": symbol},
            "trigger_methods": service.SELL_TRIGGER_METHODS,
            "active_page": "sells",
            "error": "；".join(errors)
        })

    data = {
        "symbol": symbol,
        "buy_plan_id": buy_plan_id_val,
        "planned_price": planned_price_val,
        "planned_shares": planned_shares,
        "sell_trigger_method": sell_trigger_method,
        "sell_trigger_param": trigger_param_val,
        "original_target_price": original_target_val,
        "sell_reason": sell_reason,
        "note": note,
    }

    plan = service.create_plan(data)

    return RedirectResponse(url="/sells/", status_code=303)


@router.get("/{plan_id}")
def sell_plan_detail(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """卖出计划详情页"""
    service = SellPlanService(db)
    plan = service.get_plan(plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")

    return templates.TemplateResponse("sell_plan_detail.html", {
        "request": request,
        "plan": plan,
        "active_page": "sells"
    })
