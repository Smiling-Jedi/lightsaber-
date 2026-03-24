"""
分析服务
处理仓位分析、风险评估、交易建议生成
"""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.position import Position
from app.services.position_service import PositionService

logger = logging.getLogger(__name__)


@dataclass
class PositionAdvice:
    """单只股票的交易建议"""
    symbol: str
    name: str
    action: str  # HOLD, BUY, SELL, REDUCE
    reason: str
    target_price_low: Optional[float] = None
    target_price_high: Optional[float] = None
    risk_level: str = "medium"  # low, medium, high


@dataclass
class PortfolioAdvice:
    """投资组合建议"""
    position_advices: List[PositionAdvice]
    sector_distribution: Dict[str, float]
    market_distribution: Dict[str, float]
    risk_warnings: List[str]
    overall_suggestion: str


class AnalysisService:
    """分析服务类"""

    # 仓位风险阈值
    SINGLE_POSITION_WARNING = 30.0  # 单票仓位超过30%警告
    SINGLE_POSITION_CRITICAL = 50.0  # 单票仓位超过50%严重警告

    def __init__(self, db: Session):
        self.db = db
        self.position_service = PositionService(db)

    def analyze_single_position(self, position: Position) -> PositionAdvice:
        """
        分析单只股票，生成交易建议
        """
        stock = position.stock
        if not stock or not stock.current_price:
            return PositionAdvice(
                symbol=position.stock_symbol,
                name=stock.name if stock else "Unknown",
                action="HOLD",
                reason="暂无股价数据，无法分析"
            )

        current_price = float(stock.current_price)
        avg_cost = float(position.avg_cost) if position.avg_cost else 0
        profit_pct = position.calculate_profit_pct(stock.current_price)
        position_weight = position.calculate_position_weight(stock.current_price)

        reasons = []
        action = "HOLD"
        target_low = None
        target_high = None
        risk_level = "medium"

        # 技术面分析
        if profit_pct <= -10:
            action = "BUY"
            reasons.append(f"跌幅较大({profit_pct:.1f}%)，可考虑加仓")
            target_low = current_price * 0.95
            target_high = avg_cost if avg_cost > 0 else current_price * 1.05
        elif profit_pct <= -5:
            action = "BUY"
            reasons.append(f"回调明显({profit_pct:.1f}%)，关注加仓机会")
            target_low = current_price * 0.97
            target_high = current_price * 1.03
        elif profit_pct >= 15:
            action = "SELL"
            reasons.append(f"盈利可观({profit_pct:.1f}%)，考虑减仓锁定利润")
            target_low = current_price * 0.95
            target_high = current_price * 1.10
        elif profit_pct >= 8:
            action = "REDUCE"
            reasons.append(f"有一定盈利({profit_pct:.1f}%)，可考虑适当减仓")
            target_low = current_price * 0.95
            target_high = current_price * 1.08
        else:
            reasons.append(f"波动不大({profit_pct:.1f}%)，建议持有观望")

        # 仓位分析
        if position_weight > self.SINGLE_POSITION_CRITICAL:
            if action not in ["SELL", "REDUCE"]:
                action = "REDUCE"
            reasons.append(f"⚠️ 仓位过重({position_weight:.1f}%)，建议减仓分散风险")
            risk_level = "high"
        elif position_weight > self.SINGLE_POSITION_WARNING:
            reasons.append(f"仓位偏高({position_weight:.1f}%)，注意控制")
            risk_level = "medium"

        # 波段仓建议
        if position.swing_shares > 0:
            swing_cost = position.get_swing_avg_cost()
            if swing_cost:
                swing_profit = (current_price - float(swing_cost)) / float(swing_cost) * 100
                if swing_profit >= 5:
                    reasons.append(f"波段仓盈利{swing_profit:.1f}%，可考虑卖出波段部分")

        return PositionAdvice(
            symbol=position.stock_symbol,
            name=stock.name,
            action=action,
            reason="；".join(reasons),
            target_price_low=round(target_low, 2) if target_low else None,
            target_price_high=round(target_high, 2) if target_high else None,
            risk_level=risk_level
        )

    def analyze_portfolio(self) -> PortfolioAdvice:
        """
        分析整个投资组合
        """
        positions = self.position_service.get_all_positions()

        # 单票建议
        position_advices = []
        for pos in positions:
            advice = self.analyze_single_position(pos)
            position_advices.append(advice)

        # 市场分布
        market_values = {}
        total_value = Decimal("0")
        for pos in positions:
            stock = pos.stock
            if stock and stock.current_price:
                value = pos.calculate_market_value(stock.current_price)
                market = stock.market
                market_values[market] = market_values.get(market, Decimal("0")) + value
                total_value += value

        market_distribution = {}
        if total_value > 0:
            for market, value in market_values.items():
                market_distribution[market] = float(value / total_value * 100)

        # 风险警告
        risk_warnings = []

        # 检查单票仓位
        for pos in positions:
            stock = pos.stock
            if stock and stock.current_price:
                weight = pos.calculate_position_weight(stock.current_price)
                if weight > self.SINGLE_POSITION_CRITICAL:
                    risk_warnings.append(
                        f"{stock.name} 仓位过高({weight:.1f}%)，建议减仓"
                    )

        # 检查市场集中度
        for market, pct in market_distribution.items():
            if pct > 70:
                risk_warnings.append(
                    f"{market}市场占比过高({pct:.1f}%)，建议分散投资"
                )

        # 整体建议
        if not position_advices:
            overall = "暂无持仓数据"
        elif len([a for a in position_advices if a.risk_level == "high"]) > 0:
            overall = "存在高风险持仓，建议优先处理仓位过重的股票"
        elif len([a for a in position_advices if a.action == "BUY"]) > len(position_advices) / 2:
            overall = "整体市场可能处于回调期，可关注加仓机会"
        elif len([a for a in position_advices if a.action in ["SELL", "REDUCE"]]) > len(position_advices) / 2:
            overall = "多只持仓盈利可观，建议分批锁定利润"
        else:
            overall = "整体持仓健康，建议继续持有观望"

        return PortfolioAdvice(
            position_advices=position_advices,
            sector_distribution={},  # 板块分布待实现
            market_distribution=market_distribution,
            risk_warnings=risk_warnings,
            overall_suggestion=overall
        )

    def get_daily_summary(self) -> Dict:
        """
        生成每日收盘总结
        """
        portfolio = self.position_service.get_portfolio_summary()
        advice = self.analyze_portfolio()

        return {
            "portfolio": portfolio,
            "advice": {
                "overall": advice.overall_suggestion,
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
            },
            "generated_at": None  # 由调用方填充
        }

    def check_position_risk(self, symbol: str) -> Dict:
        """
        检查特定持仓的风险
        """
        position = self.position_service.get_position_by_symbol(symbol)
        if not position:
            return {"error": "持仓不存在"}

        stock = position.stock
        if not stock or not stock.current_price:
            return {"error": "暂无股价数据"}

        weight = position.calculate_position_weight(stock.current_price)
        profit_pct = position.calculate_profit_pct(stock.current_price)

        risks = []
        if weight > self.SINGLE_POSITION_CRITICAL:
            risks.append("仓位严重超标")
        elif weight > self.SINGLE_POSITION_WARNING:
            risks.append("仓位偏高")

        if profit_pct < -15:
            risks.append("深度亏损")
        elif profit_pct < -8:
            risks.append("明显回撤")

        return {
            "symbol": symbol,
            "weight": weight,
            "profit_pct": profit_pct,
            "risks": risks,
            "is_safe": len(risks) == 0
        }

    def generate_health_check_report(self) -> Dict:
        """
        生成持仓体检报告（8大模块）
        """
        from app.models.cash import CashBalance

        portfolio = self.position_service.get_portfolio_summary()
        positions_data = portfolio.get("markets", {})

        # 计算总资产和现金
        total_assets = Decimal(str(portfolio.get("total_market_value_rmb", 0)))
        cash_total = Decimal("0")
        cash_by_market = {}

        for cb in self.db.query(CashBalance).all():
            amount = Decimal(str(cb.amount))
            if cb.market == "FUND":
                cash_by_market["HK"] = cash_by_market.get("HK", Decimal("0")) + amount
                cash_total += amount * Decimal("0.93")  # 港币汇率
            elif cb.market == "USD_FUND":
                cash_by_market["US"] = cash_by_market.get("US", Decimal("0")) + amount
                cash_total += amount * Decimal("7.25")  # 美元汇率
            else:
                cash_by_market[cb.market] = amount
                if cb.currency == "HKD":
                    cash_total += amount * Decimal("0.93")
                elif cb.currency == "USD":
                    cash_total += amount * Decimal("7.25")
                else:
                    cash_total += amount

        total_with_cash = total_assets + cash_total
        cash_ratio = float(cash_total / total_with_cash * 100) if total_with_cash > 0 else 0

        # 收集所有持仓
        all_positions = []
        for market, data in positions_data.items():
            for pos in data.get("positions", []):
                if not pos.get("is_cash"):
                    all_positions.append(pos)

        # 按市值排序
        all_positions.sort(key=lambda x: x.get("market_value") or 0, reverse=True)

        # 计算集中度
        top3_value = sum(p.get("market_value", 0) for p in all_positions[:3])
        top3_ratio = (top3_value / float(total_assets) * 100) if total_assets > 0 else 0

        max_single = all_positions[0] if all_positions else None
        max_single_ratio = max_single.get("position_weight", 0) if max_single else 0

        # 计算预期收益（简化版）
        expected_return = self._calculate_expected_return(all_positions)

        # 板块分布
        sector_dist = self._calculate_sector_distribution(all_positions)

        # 生成建议
        actions = self._generate_action_plan(all_positions, cash_total)

        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "summary": {
                "total_assets": float(total_with_cash),
                "stock_value": float(total_assets),
                "cash_value": float(cash_total),
                "cash_ratio": cash_ratio,
                "single_max_ratio": max_single_ratio,
                "top3_ratio": top3_ratio,
                "expected_return": expected_return,
                "health_score": self._calculate_health_score(cash_ratio, max_single_ratio, top3_ratio, expected_return),
                "position_count": len(all_positions),
            },
            "market_distribution": {
                m: d.get("weight_pct", 0) for m, d in positions_data.items()
            },
            "sector_distribution": sector_dist,
            "top_positions": all_positions[:5],
            "risk_warnings": self._generate_risk_warnings(all_positions, max_single_ratio, top3_ratio, cash_ratio),
            "actions": actions,
            "discipline_checks": self._generate_discipline_checks(all_positions),
        }

    def _calculate_expected_return(self, positions: List[Dict]) -> float:
        """计算组合预期收益（简化模型）"""
        # 基于盈亏和仓位计算加权预期
        total_weight = 0
        weighted_return = 0

        for pos in positions:
            weight = pos.get("position_weight", 0)
            profit_pct = pos.get("profit_pct", 0)

            # 根据当前盈亏调整预期
            if profit_pct > 50:
                expected = 15  # 已大涨，预期收益降低
            elif profit_pct > 20:
                expected = 20
            elif profit_pct > 0:
                expected = 25
            elif profit_pct > -10:
                expected = 30  # 回调中，潜在收益高
            else:
                expected = 20  # 深度回调，谨慎预期

            weighted_return += expected * weight
            total_weight += weight

        return round(weighted_return / 100, 1) if total_weight > 0 else 0

    def _calculate_sector_distribution(self, positions: List[Dict]) -> Dict[str, float]:
        """计算板块分布"""
        sectors = {
            "新能源": ["宁德", "比亚迪", "阳光电源", "300750", "002594", "300274"],
            "科技": ["腾讯", "阿里", "美团", "小米", "00700", "09988", "03690", "01810"],
            "金融": ["中信", "东财", "招行", "兴业", "交行", "600030", "300059"],
            "医药": ["医药ETF", "百济", "恒瑞", "512010", "06160", "01276"],
            "其他": []
        }

        sector_values = {k: 0 for k in sectors}
        total = 0

        for pos in positions:
            name = pos.get("name", "")
            symbol = pos.get("symbol", "")
            value = pos.get("market_value", 0)
            total += value

            assigned = False
            for sector, keywords in sectors.items():
                if sector == "其他":
                    continue
                for kw in keywords:
                    if kw in name or kw in symbol:
                        sector_values[sector] += value
                        assigned = True
                        break
                if assigned:
                    break

            if not assigned:
                sector_values["其他"] += value

        return {k: round(v / total * 100, 1) if total > 0 else 0 for k, v in sector_values.items()}

    def _calculate_health_score(self, cash_ratio: float, max_single: float, top3: float, expected_return: float) -> int:
        """计算健康度评分"""
        score = 100

        # 现金扣分
        if cash_ratio > 20:
            score -= 10
        elif cash_ratio > 15:
            score -= 5

        # 集中度扣分
        if max_single > 30:
            score -= 15
        elif max_single > 25:
            score -= 10

        if top3 > 60:
            score -= 15
        elif top3 > 50:
            score -= 10

        # 收益预期扣分
        if expected_return < 20:
            score -= 15
        elif expected_return < 25:
            score -= 10

        return max(0, score)

    def _generate_risk_warnings(self, positions: List[Dict], max_single: float, top3: float, cash_ratio: float) -> List[Dict]:
        """生成风险警告"""
        warnings = []

        if max_single > 25:
            top_pos = positions[0] if positions else None
            warnings.append({
                "level": "high" if max_single > 30 else "medium",
                "title": "单票集中度风险",
                "message": f"{top_pos.get('name', '持仓')}占比{max_single:.1f}%，建议减仓至25%以内"
            })

        if top3 > 50:
            warnings.append({
                "level": "high" if top3 > 60 else "medium",
                "title": "TOP3集中度风险",
                "message": f"前三大持仓占比{top3:.1f}%，分散度不足"
            })

        # 检查波段被套
        for pos in positions:
            if pos.get("swing_cost"):
                swing_cost = float(pos.get("swing_cost", 0))
                current = pos.get("current_price", 0)
                if swing_cost > current * 1.1:  # 被套超过10%
                    warnings.append({
                        "level": "medium",
                        "title": f"{pos.get('name')}波段被套",
                        "message": f"波段成本{swing_cost:.2f}，现价{current:.2f}，被套{((swing_cost-current)/swing_cost*100):.0f}%"
                    })

        return warnings

    def _generate_action_plan(self, positions: List[Dict], cash: Decimal) -> List[Dict]:
        """生成行动计划"""
        actions = []

        # P0: 必须处理
        for pos in positions:
            name = pos.get("name", "")
            weight = pos.get("position_weight", 0)

            # 腾讯减仓建议
            if "腾讯" in name and weight > 25:
                actions.append({
                    "priority": "P0",
                    "action": "减仓",
                    "symbol": pos.get("symbol"),
                    "name": name,
                    "quantity": "2,000股",
                    "trigger": "立即",
                    "reason": f"仓位{weight:.1f}%过高，需降至25%以内",
                    "estimated_value": "约HK$103万"
                })

            # 券商清仓
            if "中信" in name or "东财" in name or "东方财富" in name:
                actions.append({
                    "priority": "P0",
                    "action": "清仓",
                    "symbol": pos.get("symbol"),
                    "name": name,
                    "quantity": f"{pos.get('total_shares', 0):,}股",
                    "trigger": "立即",
                    "reason": "券商板块2026年预期增速仅6%，收益黑洞",
                    "estimated_value": f"约¥{pos.get('market_value', 0)/10000:.1f}万"
                })

        # P1: 条件触发
        actions.append({
            "priority": "P1",
            "action": "加仓",
            "symbol": "300274",
            "name": "阳光电源",
            "quantity": "3,000股",
            "trigger": "股价≤¥155",
            "reason": "年报前布局储能+AIDC，目标价¥200",
            "estimated_value": "约¥46.5万"
        })

        actions.append({
            "priority": "P1",
            "action": "加仓",
            "symbol": "09988",
            "name": "阿里巴巴",
            "quantity": "6,000股",
            "trigger": "港股通，股价≤HK$120",
            "reason": "AI叙事+估值修复，分散腾讯集中度",
            "estimated_value": "约HK$72万"
        })

        return actions

    def _generate_discipline_checks(self, positions: List[Dict]) -> List[Dict]:
        """生成纪律检查项"""
        checks = []

        # 检查止损纪律
        losing_positions = [p for p in positions if p.get("profit_pct", 0) < -15]
        if losing_positions:
            checks.append({
                "type": "止损纪律",
                "status": "warning",
                "message": f"有{len(losing_positions)}只持仓亏损超15%，需检查是否设置止损",
                "positions": [p.get("name") for p in losing_positions]
            })

        # 检查波段成本
        high_swing_cost = []
        for pos in positions:
            if pos.get("swing_cost") and pos.get("avg_cost"):
                if float(pos.get("swing_cost", 0)) > float(pos.get("avg_cost", 0)) * 1.1:
                    high_swing_cost.append(pos.get("name"))

        if high_swing_cost:
            checks.append({
                "type": "加仓纪律",
                "status": "warning",
                "message": "以下持仓波段成本高于底仓10%以上，存在追高行为",
                "positions": high_swing_cost
            })

        # 检查集中度
        high_concentration = [p for p in positions if p.get("position_weight", 0) > 25]
        if high_concentration:
            checks.append({
                "type": "集中度纪律",
                "status": "danger",
                "message": "单票仓位超过25%，触发再平衡线",
                "positions": [p.get("name") for p in high_concentration]
            })

        return checks
