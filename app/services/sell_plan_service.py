"""
卖出计划服务
"""
import logging
from decimal import Decimal
from typing import Optional, List, Dict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.sell_plan import SellPlan
from app.models.trade_plan import TradePlan
from app.models.position import Position
from app.models.stock import Stock
from app.services.position_service import PositionService

logger = logging.getLogger(__name__)


class SellPlanService:
    """卖出计划业务服务"""

    # 卖出触发方式配置
    SELL_TRIGGER_METHODS = {
        "固定比例止盈": {"param_label": "%", "param_type": "percent", "default": 10.0, "sell_type": "止盈"},
        "固定比例止损": {"param_label": "%", "param_type": "percent", "default": 7.0, "sell_type": "止损"},
        "ATR倍数止盈": {"param_label": "倍", "param_type": "atr", "default": 2.0, "sell_type": "止盈"},
        "压力位": {"param_label": "价格", "param_type": "price", "default": None, "sell_type": "止盈"},
        "移动平均线": {"param_label": "天数", "param_type": "ma", "default": 20, "sell_type": "止盈"},
    }

    def __init__(self, db: Session):
        self.db = db
        self.position_svc = PositionService(db)

    def get_plan(self, plan_id: int) -> Optional[SellPlan]:
        """获取单个卖出计划"""
        return self.db.query(SellPlan).filter(SellPlan.id == plan_id).first()

    def list_plans(self, limit: int = 100, offset: int = 0) -> List[SellPlan]:
        """获取卖出计划列表"""
        return (
            self.db.query(SellPlan)
            .order_by(SellPlan.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_plans_by_position(self, position_id: int) -> List[SellPlan]:
        """通过持仓ID获取卖出计划"""
        return (
            self.db.query(SellPlan)
            .filter(SellPlan.position_id == position_id)
            .order_by(SellPlan.created_at.desc())
            .all()
        )

    def create_plan(self, data: dict) -> SellPlan:
        """创建新卖出计划"""
        # 计算盈利指标
        position = self.position_svc.get_position_by_symbol(data["symbol"])
        current_shares = position.total_shares if position else 0

        # 获取买入成本（优先从关联的买入计划获取）
        avg_cost = self._get_avg_cost(data.get("buy_plan_id"), position)

        # 计算盈利
        planned_price = Decimal(str(data.get("planned_price", 0)))
        planned_shares = int(data["planned_shares"])

        if avg_cost > 0 and planned_price > 0:
            estimated_profit = (planned_price - avg_cost) * planned_shares
            estimated_profit_pct = round((planned_price - avg_cost) / avg_cost * 100, 2)
        else:
            estimated_profit = Decimal("0")
            estimated_profit_pct = Decimal("0")

        # 计算目标达成度
        original_target = Decimal(str(data.get("original_target_price", 0)))
        if original_target > 0 and avg_cost > 0:
            # 目标达成度 = 计划卖出价 / 原目标价
            target_achievement_pct = round(planned_price / original_target * 100, 2)
        else:
            target_achievement_pct = Decimal("0")

        # 确定卖出类型
        trigger_method = data["sell_trigger_method"]
        sell_type = self.SELL_TRIGGER_METHODS.get(trigger_method, {}).get("sell_type", "止盈")

        plan = SellPlan(
            symbol=data["symbol"],
            market=self._extract_market(data["symbol"]),
            buy_plan_id=data.get("buy_plan_id"),
            position_id=position.id if position else None,
            planned_shares=planned_shares,
            planned_price=planned_price if planned_price > 0 else None,
            original_target_price=original_target if original_target > 0 else None,
            sell_trigger_method=trigger_method,
            sell_trigger_param=Decimal(str(data["sell_trigger_param"])),
            sell_type=sell_type,
            estimated_profit=estimated_profit,
            estimated_profit_pct=estimated_profit_pct,
            target_achievement_pct=target_achievement_pct,
            sell_reason=data["sell_reason"],
            note=data.get("note"),
            status="计划中",
            created_at=datetime.now(),
        )

        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def evaluate_plan(self, data: dict) -> Dict:
        """评估卖出计划（不保存到数据库）"""
        # 计算盈利指标
        position = self.position_svc.get_position_by_symbol(data["symbol"])
        current_shares = position.total_shares if position else 0

        # 获取买入成本
        avg_cost = self._get_avg_cost(data.get("buy_plan_id"), position)

        # 计算盈利
        planned_price = Decimal(str(data.get("planned_price", 0)))
        planned_shares = int(data["planned_shares"])

        if avg_cost > 0 and planned_price > 0:
            estimated_profit = (planned_price - avg_cost) * planned_shares
            estimated_profit_pct = round((planned_price - avg_cost) / avg_cost * 100, 2)
        else:
            estimated_profit = Decimal("0")
            estimated_profit_pct = Decimal("0")

        # 计算目标达成度
        original_target = Decimal(str(data.get("original_target_price", 0)))
        if original_target > 0 and avg_cost > 0:
            target_achievement_pct = round(planned_price / original_target * 100, 2)
        else:
            target_achievement_pct = Decimal("0")

        # 计算卖出后剩余仓位
        remaining_shares = current_shares - planned_shares

        # 获取该市场总资产用于计算剩余仓位占比
        portfolio = self.position_svc.get_portfolio_summary()
        market = self._extract_market(data["symbol"])
        markets_data = portfolio.get("markets", {})
        market_data = markets_data.get(market, {})
        market_total = Decimal(str(market_data.get("total_with_cash", 0)))

        # 计算剩余仓位占比
        stock = self.db.query(Stock).filter(Stock.symbol == data["symbol"]).first()
        current_price = Decimal(str(stock.current_price)) if stock and stock.current_price else avg_cost
        remaining_value = remaining_shares * current_price
        remaining_pct = (remaining_value / market_total * 100) if market_total > 0 else Decimal("0")

        # 执行评估检查
        checks = []

        # 1. 盈利实现度检查
        profit_check = self._check_profit_achievement(estimated_profit_pct, target_achievement_pct)
        checks.append(profit_check)

        # 2. 剩余仓位检查
        position_check = self._check_remaining_position(remaining_pct)
        checks.append(position_check)

        # 3. 卖出逻辑匹配检查
        logic_check = self._check_sell_logic_match(data)
        checks.append(logic_check)

        # 综合结论
        has_fail = any(c["status"] == "fail" for c in checks)
        has_warning = any(c["status"] == "warning" for c in checks)

        if has_fail:
            overall = "不建议"
            overall_code = "red"
        elif has_warning:
            overall = "谨慎执行"
            overall_code = "yellow"
        else:
            overall = "建议执行"
            overall_code = "green"

        return {
            "plan": {
                "symbol": data["symbol"],
                "avg_cost": float(avg_cost) if avg_cost else None,
                "estimated_profit": float(estimated_profit),
                "estimated_profit_pct": float(estimated_profit_pct),
                "target_achievement_pct": float(target_achievement_pct),
                "remaining_shares": remaining_shares,
                "remaining_pct": float(remaining_pct),
            },
            "evaluation": {
                "overall": overall,
                "overall_code": overall_code,
                "checks": checks,
            }
        }

    def _get_avg_cost(self, buy_plan_id: Optional[int], position: Optional[Position]) -> Decimal:
        """获取平均成本（优先从买入计划，其次从持仓）"""
        if buy_plan_id:
            buy_plan = self.db.query(TradePlan).filter(TradePlan.id == buy_plan_id).first()
            if buy_plan and buy_plan.planned_price:
                return Decimal(str(buy_plan.planned_price))

        if position and position.total_shares > 0:
            # 从持仓计算平均成本
            return Decimal(str(position.invested_cost)) / position.total_shares if position.invested_cost else Decimal("0")

        return Decimal("0")

    def _extract_market(self, symbol: str) -> str:
        """从symbol提取市场"""
        return symbol.split(":")[0] if ":" in symbol else "A"

    def _check_profit_achievement(self, profit_pct: Decimal, achievement_pct: Decimal) -> Dict:
        """盈利实现度检查"""
        if profit_pct <= 0:
            return {
                "item": "盈利实现度",
                "status": "fail",
                "message": f"预计亏损{float(profit_pct):.1f}%，请确认是否为止损卖出"
            }
        elif achievement_pct >= 90:
            return {
                "item": "盈利实现度",
                "status": "pass",
                "message": f"目标达成{float(achievement_pct):.1f}%，合理止盈"
            }
        elif achievement_pct >= 70:
            return {
                "item": "盈利实现度",
                "status": "warning",
                "message": f"目标达成{float(achievement_pct):.1f}%，可考虑部分止盈"
            }
        else:
            return {
                "item": "盈利实现度",
                "status": "warning",
                "message": f"目标仅达成{float(achievement_pct):.1f}%，建议持有至更高位置"
            }

    def _check_remaining_position(self, remaining_pct: Decimal) -> Dict:
        """剩余仓位检查"""
        if remaining_pct > 25:
            return {
                "item": "剩余仓位",
                "status": "warning",
                "message": f"卖出后剩余仓位{float(remaining_pct):.1f}%，仍超25%红线，可考虑多卖"
            }
        elif remaining_pct > 20:
            return {
                "item": "剩余仓位",
                "status": "pass",
                "message": f"卖出后剩余仓位{float(remaining_pct):.1f}%，接近上限"
            }
        else:
            return {
                "item": "剩余仓位",
                "status": "pass",
                "message": f"卖出后剩余仓位{float(remaining_pct):.1f}%，仓位健康"
            }

    def _check_sell_logic_match(self, data: dict) -> Dict:
        """卖出逻辑匹配检查"""
        trigger_method = data.get("sell_trigger_method", "")
        sell_reason = data.get("sell_reason", "")

        # 根据触发方式检查理由中是否有关键词
        if "止盈" in trigger_method:
            keywords = ["止盈", "目标价", "利润", "盈利", "锁定"]
            has_match = any(kw in sell_reason for kw in keywords)
            if not has_match:
                return {
                    "item": "逻辑匹配",
                    "status": "warning",
                    "message": "止盈卖出建议说明利润锁定原因"
                }

        elif "止损" in trigger_method:
            keywords = ["止损", "跌破", "趋势", "风险"]
            has_match = any(kw in sell_reason for kw in keywords)
            if not has_match:
                return {
                    "item": "逻辑匹配",
                    "status": "warning",
                    "message": "止损卖出建议说明风险原因"
                }

        return {
            "item": "逻辑匹配",
            "status": "pass",
            "message": "卖出理由与触发方式匹配"
        }
