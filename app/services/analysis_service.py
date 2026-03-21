"""
分析服务
处理仓位分析、风险评估、交易建议生成
"""
import logging
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
