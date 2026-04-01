"""
交易计划路由
"""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.trade_plan_service import TradePlanService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def trade_plan_list(request: Request, db: Session = Depends(get_db)):
    """交易记录列表页（从trades表获取实际交易）"""
    from app.models.trade import Trade
    from app.models.position import Position

    try:
        from app.models.trade_plan import TradePlan

        # 获取所有交易记录
        trades = db.query(Trade).order_by(Trade.trade_date.desc()).limit(100).all()

        # 构建交易列表数据
        trade_list = []
        for trade in trades:
            # 获取持仓信息
            position = db.query(Position).filter(Position.id == trade.position_id).first()
            symbol = position.stock_symbol if position else ""

            # 获取股票名称
            from app.models.stock import Stock
            stock = db.query(Stock).filter(Stock.symbol == symbol).first() if symbol else None
            stock_name = stock.name if stock else symbol

            # 检查是否有对应的交易计划
            plan = db.query(TradePlan).filter(TradePlan.trade_id == trade.id).first()

            # 计算评估分数
            eval_score = None
            eval_code = None
            if plan:
                from app.services.trade_plan_service import TradePlanService
                service = TradePlanService(db)
                eval_data = {
                    "symbol": plan.symbol,
                    "strategy_type": plan.strategy_type,
                    "planned_price": float(plan.planned_price),
                    "target_price": float(plan.target_price),
                    "planned_shares": plan.planned_shares,
                    "stop_loss_method": plan.stop_loss_method,
                    "stop_loss_param": float(plan.stop_loss_param),
                    "buy_reason": plan.buy_reason or "",
                    "note": plan.note,
                }
                try:
                    eval_result = service.evaluate_plan(eval_data)
                    # 处理错误返回格式
                    if "error" in eval_result:
                        eval_score = 0
                        eval_code = "red"
                    else:
                        checks = eval_result.get("evaluation", {}).get("checks", [])
                        score = 100
                        for check in checks:
                            if check["status"] == "fail":
                                score -= 30
                            elif check["status"] == "warning":
                                score -= 15
                        eval_score = max(0, score)
                        eval_code = eval_result.get("evaluation", {}).get("overall_code", "yellow")
                except:
                    pass

            trade_list.append({
                "id": trade.id,
                "trade_date": trade.trade_date,
                "symbol": symbol,
                "stock_name": stock_name,
                "trade_type": trade.trade_type,
                "shares": trade.shares,
                "price": float(trade.price) if trade.price else 0,
                "total_cost": float(trade.total_cost) if trade.total_cost else 0,
                "has_plan": plan is not None,
                "plan_id": plan.id if plan else None,
                "plan": plan,
                "eval_score": eval_score,
                "eval_code": eval_code,
            })

        return templates.TemplateResponse("trade_plan_list.html", {
            "request": request,
            "trades": trade_list,
            "active_page": "trades"
        })
    except Exception as e:
        import traceback
        error_msg = str(e) + "\n" + traceback.format_exc()[:500]
        return templates.TemplateResponse("trade_plan_list.html", {
            "request": request,
            "trades": [],
            "error": error_msg,
            "active_page": "trades"
        })


@router.get("/new")
def trade_plan_new(request: Request, trade_id: int = None, db: Session = Depends(get_db)):
    """新建交易计划页"""
    from app.models.trade import Trade
    from app.models.position import Position

    service = TradePlanService(db)

    # 默认数据
    default_data = {}
    mode = "新建"

    # 如果是补录模式，从trade预填充数据
    if trade_id:
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if trade:
            position = trade.position
            symbol = position.stock_symbol if position else ""
            # 解析symbol获取市场和代码
            if ":" in symbol:
                market, code = symbol.split(":", 1)
            else:
                market, code = "A", symbol

            default_data = {
                "market": market,
                "stock_code": code,
                "symbol": symbol,
                "planned_price": float(trade.price),
                "planned_shares": trade.shares,
            }
            mode = "补录"

    return templates.TemplateResponse("trade_plan_form.html", {
        "request": request,
        "mode": mode,
        "default_data": default_data,
        "strategy_defaults": service.STRATEGY_DEFAULTS,
        "stop_loss_methods": service.STOP_LOSS_METHODS,
        "active_page": "trades"
    })


@router.get("/{plan_id}")
def trade_plan_detail(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """计划详情页"""
    service = TradePlanService(db)
    plan = service.get_plan(plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")

    return templates.TemplateResponse("trade_plan_detail.html", {
        "request": request,
        "plan": plan,
        "active_page": "trades"
    })


@router.post("/api/evaluate")
def api_evaluate_plan(
    symbol: str = Form(...),
    strategy_type: str = Form(...),
    planned_price: str = Form(...),
    target_price: str = Form(...),
    planned_shares: str = Form(...),
    stop_loss_method: str = Form(...),
    stop_loss_param: str = Form(...),
    buy_reason: str = Form(...),
    note: str = Form(None),
    db: Session = Depends(get_db)
):
    """评估交易计划（不保存）"""
    # 参数验证
    errors = []

    if not symbol or not symbol.strip():
        errors.append("股票代码不能为空")

    # 解析计划买入价
    try:
        planned_price_val = float(planned_price) if planned_price else 0
        if planned_price_val <= 0:
            errors.append("计划买入价必须大于0")
    except (ValueError, TypeError):
        errors.append("计划买入价格式错误")
        planned_price_val = 0

    # 解析目标价
    try:
        target_price_val = float(target_price) if target_price else 0
        if target_price_val <= 0:
            errors.append("目标价必须大于0")
    except (ValueError, TypeError):
        errors.append("目标价格式错误")
        target_price_val = 0

    # 解析计划股数
    try:
        planned_shares_val = int(planned_shares) if planned_shares else 0
        if planned_shares_val <= 0:
            errors.append("计划股数必须大于0")
    except (ValueError, TypeError):
        errors.append("计划股数格式错误")
        planned_shares_val = 0

    # 解析止损参数
    try:
        stop_loss_param_val = float(stop_loss_param) if stop_loss_param else 0
    except (ValueError, TypeError):
        errors.append("止损参数格式错误")
        stop_loss_param_val = 0

    # 目标价必须大于买入价
    if target_price_val > 0 and planned_price_val > 0 and target_price_val <= planned_price_val:
        errors.append("目标价必须高于计划买入价")

    # 买入理由必填检查（最少10字）
    if not buy_reason or not buy_reason.strip():
        errors.append("买入理由不能为空")
    elif len(buy_reason.strip()) < 10:
        errors.append("买入理由最少需要10个字")

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
                "suggestions": ["请填写所有必填字段后再评估"]
            }
        }

    service = TradePlanService(db)

    data = {
        "symbol": symbol,
        "strategy_type": strategy_type,
        "planned_price": planned_price_val,
        "target_price": target_price_val,
        "planned_shares": planned_shares_val,
        "stop_loss_method": stop_loss_method,
        "stop_loss_param": stop_loss_param_val,
        "buy_reason": buy_reason,
        "note": note,
    }

    result = service.evaluate_plan(data)
    return result


@router.get("/api/eval-detail/{plan_id}")
def api_eval_detail(plan_id: int, db: Session = Depends(get_db)):
    """获取计划评估详情（用于列表页浮层）"""
    from app.models.trade_plan import TradePlan
    service = TradePlanService(db)

    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")

    # 重新执行评估
    data = {
        "symbol": plan.symbol,
        "strategy_type": plan.strategy_type,
        "planned_price": float(plan.planned_price),
        "target_price": float(plan.target_price),
        "planned_shares": plan.planned_shares,
        "stop_loss_method": plan.stop_loss_method,
        "stop_loss_param": float(plan.stop_loss_param),
        "buy_reason": plan.buy_reason or "",
        "note": plan.note,
    }

    eval_result = service.evaluate_plan(data)

    # 计算分数
    checks = eval_result.get("evaluation", {}).get("checks", [])
    score = 100
    for check in checks:
        if check["status"] == "fail":
            score -= 30
        elif check["status"] == "warning":
            score -= 15
    score = max(0, score)

    return {
        "symbol": plan.symbol,
        "strategy_type": plan.strategy_type,
        "eval_score": score,
        "evaluation": eval_result.get("evaluation", {}),
    }


@router.post("/api")
def api_create_plan(
    request: Request,
    symbol: str = Form(...),
    strategy_type: str = Form(...),
    planned_price: str = Form(...),
    target_price: str = Form(...),
    planned_shares: str = Form(...),
    stop_loss_method: str = Form(...),
    stop_loss_param: str = Form(...),
    buy_reason: str = Form(...),
    note: str = Form(None),
    trade_id: str = Form(None),
    db: Session = Depends(get_db)
):
    """创建交易计划"""
    # 参数验证
    errors = []

    if not symbol or not symbol.strip():
        errors.append("股票代码不能为空")

    # 解析计划买入价
    try:
        planned_price_val = float(planned_price) if planned_price else 0
        if planned_price_val <= 0:
            errors.append("计划买入价必须大于0")
    except (ValueError, TypeError):
        errors.append("计划买入价格式错误")
        planned_price_val = 0

    # 解析目标价
    try:
        target_price_val = float(target_price) if target_price else 0
        if target_price_val <= 0:
            errors.append("目标价必须大于0")
    except (ValueError, TypeError):
        errors.append("目标价格式错误")
        target_price_val = 0

    # 解析计划股数
    try:
        planned_shares_val = int(planned_shares) if planned_shares else 0
        if planned_shares_val <= 0:
            errors.append("计划股数必须大于0")
    except (ValueError, TypeError):
        errors.append("计划股数格式错误")
        planned_shares_val = 0

    # 解析止损参数
    try:
        stop_loss_param_val = float(stop_loss_param) if stop_loss_param else 0
    except (ValueError, TypeError):
        errors.append("止损参数格式错误")
        stop_loss_param_val = 0

    # 解析 trade_id
    try:
        trade_id_val = int(trade_id) if trade_id else None
    except (ValueError, TypeError):
        trade_id_val = None

    # 目标价必须大于买入价
    if target_price_val > 0 and planned_price_val > 0 and target_price_val <= planned_price_val:
        errors.append("目标价必须高于计划买入价")

    # 买入理由必填检查（最少10字）
    if not buy_reason or not buy_reason.strip():
        errors.append("买入理由不能为空")
    elif len(buy_reason.strip()) < 10:
        errors.append("买入理由最少需要10个字")

    # 检查是否已存在该交易的计划
    if trade_id_val:
        from app.models.trade_plan import TradePlan
        existing = db.query(TradePlan).filter(TradePlan.trade_id == trade_id_val).first()
        if existing:
            errors.append(f"该交易已存在计划(ID:{existing.id})，请勿重复创建")

    # 如果有验证错误，显示错误页面
    if errors:
        return templates.TemplateResponse("trade_plan_form.html", {
            "request": request,
            "mode": "新建",
            "default_data": {
                "market": symbol.split(":")[0] if ":" in symbol else "A",
                "stock_code": symbol.split(":")[1] if ":" in symbol else "",
                "symbol": symbol,
                "planned_price": planned_price_val if planned_price_val > 0 else "",
                "planned_shares": planned_shares_val if planned_shares_val > 0 else "",
            },
            "strategy_defaults": TradePlanService(db).STRATEGY_DEFAULTS,
            "stop_loss_methods": TradePlanService(db).STOP_LOSS_METHODS,
            "active_page": "trades",
            "error": "；".join(errors)
        })

    service = TradePlanService(db)

    data = {
        "symbol": symbol,
        "strategy_type": strategy_type,
        "planned_price": planned_price_val,
        "target_price": target_price_val,
        "planned_shares": planned_shares_val,
        "stop_loss_method": stop_loss_method,
        "stop_loss_param": stop_loss_param_val,
        "buy_reason": buy_reason,
        "note": note,
        "trade_id": trade_id_val,
    }

    try:
        plan = service.create_plan(data)
    except ValueError as e:
        # 业务逻辑错误（如止损价高于买入价等）
        return templates.TemplateResponse("trade_plan_form.html", {
            "request": request,
            "mode": "新建",
            "default_data": {
                "market": symbol.split(":")[0] if ":" in symbol else "A",
                "stock_code": symbol.split(":")[1] if ":" in symbol else "",
                "symbol": symbol,
                "planned_price": planned_price_val if planned_price_val > 0 else "",
                "planned_shares": planned_shares_val if planned_shares_val > 0 else "",
            },
            "strategy_defaults": TradePlanService(db).STRATEGY_DEFAULTS,
            "stop_loss_methods": TradePlanService(db).STOP_LOSS_METHODS,
            "active_page": "trades",
            "error": str(e)
        })

    # 表单提交后重定向到列表页
    return RedirectResponse(url="/trades/", status_code=303)
