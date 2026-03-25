"""
持仓管理服务
处理持仓的增删改查、成本计算、盈亏统计
"""
import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.position import Position
from app.models.trade import Trade
from app.models.cash import CashBalance

logger = logging.getLogger(__name__)


class PositionService:
    """持仓管理服务类"""

    def __init__(self, db: Session):
        self.db = db

    def get_all_positions(self) -> List[Position]:
        """获取所有持仓记录"""
        return self.db.query(Position).all()

    def get_position_by_symbol(self, symbol: str) -> Optional[Position]:
        """根据股票代码获取持仓"""
        return self.db.query(Position).filter(Position.stock_symbol == symbol).first()

    def get_positions_by_market(self, market: str) -> List[Position]:
        """按市场获取持仓列表"""
        return (
            self.db.query(Position)
            .join(Stock)
            .filter(Stock.market == market)
            .all()
        )

    def create_position(
        self,
        symbol: str,
        name: str,
        market: str,
        currency: str,
        total_shares: int,
        avg_cost: Decimal,
        base_shares: int = 0,
        base_cost: Optional[Decimal] = None,
        market_total_fund: Decimal = Decimal("1000000"),
        trading_cost: Decimal = Decimal("0"),
        notes: str = "",
    ) -> Position:
        """
        创建新的持仓记录

        Args:
            symbol: 股票代码（如 US:TSLA）
            name: 股票名称
            market: 市场（HK/US/A）
            currency: 币种
            total_shares: 总持仓股数
            avg_cost: 加权平均成本
            base_shares: 底仓股数（默认0）
            base_cost: 底仓成本（可选）
            market_total_fund: 该市场总资金（用于计算仓位占比）
            trading_cost: 交易成本
            notes: 备注
        """
        # 先创建或获取股票记录
        stock = self.db.query(Stock).filter(Stock.symbol == symbol).first()
        if not stock:
            stock = Stock(
                symbol=symbol,
                name=name,
                market=market,
                currency=currency,
            )
            self.db.add(stock)
            self.db.flush()

        # 创建持仓记录
        position = Position(
            stock_symbol=symbol,
            total_shares=total_shares,
            base_shares=base_shares,
            base_cost=base_cost or avg_cost,
            avg_cost=avg_cost,
            trading_cost=trading_cost,
            market_total_fund=market_total_fund,
            currency=currency,
            notes=notes,
        )
        self.db.add(position)
        self.db.commit()
        self.db.refresh(position)

        logger.info(f"创建持仓: {symbol} {total_shares}股 @ {avg_cost}")
        return position

    def import_from_csv_row(
        self,
        symbol: str,
        name: str,
        market: str,
        currency: str,
        shares: int,
        avg_cost: Decimal,
        current_price: Optional[Decimal] = None,
        market_total_fund: Decimal = Decimal("1000000"),
    ) -> Position:
        """
        从 CSV 导入持仓
        这是简化版导入，不区分底仓和波段仓
        """
        # 创建或更新股票记录
        stock = self.db.query(Stock).filter(Stock.symbol == symbol).first()
        if not stock:
            stock = Stock(
                symbol=symbol,
                name=name,
                market=market,
                currency=currency,
                current_price=current_price,
                price_updated_at=datetime.now() if current_price else None,
            )
            self.db.add(stock)
        elif current_price:
            stock.current_price = current_price
            stock.price_updated_at = datetime.now()

        self.db.flush()

        # 检查是否已有持仓
        position = self.get_position_by_symbol(symbol)
        if position:
            # 更新现有持仓
            position.total_shares = shares
            position.avg_cost = avg_cost
            position.market_total_fund = market_total_fund
            position.updated_at = datetime.now()
        else:
            # 创建新持仓
            position = Position(
                stock_symbol=symbol,
                total_shares=shares,
                base_shares=0,  # 默认没有底仓
                base_cost=avg_cost,
                avg_cost=avg_cost,
                market_total_fund=market_total_fund,
                currency=currency,
            )
            self.db.add(position)

        self.db.commit()
        self.db.refresh(position)
        return position

    def add_trade(
        self,
        position_id: int,
        trade_type: str,  # BUY or SELL
        shares: int,
        price: Decimal,
        trading_cost: Decimal = Decimal("0"),
        target_sell_price: Optional[Decimal] = None,
    ) -> Trade:
        """
        添加交易记录
        """
        position = self.db.query(Position).filter(Position.id == position_id).first()
        if not position:
            raise ValueError(f"持仓不存在: ID={position_id}")

        trade = Trade(
            position_id=position_id,
            trade_type=trade_type,
            shares=shares,
            price=price,
            trading_cost=trading_cost,
            target_sell_price=target_sell_price,
            remaining_shares=shares if trade_type == "BUY" else 0,
            is_swing=target_sell_price is not None,
        )
        self.db.add(trade)

        # 更新持仓
        if trade_type == "BUY":
            position.total_shares += shares
        else:  # SELL
            if shares > position.total_shares:
                raise ValueError(f"卖出股数({shares})超过持仓({position.total_shares})")
            position.total_shares -= shares

        position.updated_at = datetime.now()

        self.db.commit()
        self.db.refresh(trade)
        return trade

    def get_position_summary(self, position: Position) -> Dict:
        """
        获取持仓汇总信息（用于前端展示）
        """
        stock = position.stock
        current_price = stock.current_price if stock else None

        result = {
            "symbol": position.stock_symbol,
            "name": stock.name if stock else "",
            "market": stock.market if stock else "",
            "currency": position.currency,
            "total_shares": position.total_shares,
            "base_shares": position.base_shares,
            "swing_shares": position.swing_shares,
            "avg_cost": float(position.avg_cost) if position.avg_cost else 0,
            "base_cost": float(position.base_cost) if position.base_cost else 0,
            "swing_cost": float(position.swing_cost) if position.swing_cost else None,
            "current_price": float(current_price) if current_price else None,
            "market_value": None,
            "profit": None,
            "profit_pct": None,
            "position_weight": None,
            "price_change_pct": stock.price_change_pct if stock else 0,
            # 新增字段
            "advice": None,
            "monitor_targets": [],
            "support_price": None,
            "resistance_price": None,
            "latest_news": None,
            "latest_news_url": None,
            "latest_news_source": None,
            "today_profit_amount": 0.0,
            "swing_plan": None,
            "swing_alert": None,
        }

        if current_price:
            result["market_value"] = float(
                position.calculate_market_value(current_price)
            )
            result["profit"] = float(position.calculate_profit(current_price))
            result["profit_pct"] = position.calculate_profit_pct(current_price)
            result["position_weight"] = position.calculate_position_weight(current_price)

            # 汇率转换：将盈亏和市值转换为RMB显示
            from app.data_sources.exchange_rate_source import ExchangeRateSource
            er = ExchangeRateSource(retry_count=1)
            currency = position.currency or "CNY"
            rate = float(er.get_rate_to_cny(currency)) if currency != "CNY" else 1.0

            result["profit_rmb"] = result["profit"] * rate if result["profit"] is not None else None
            result["market_value_rmb"] = result["market_value"] * rate if result["market_value"] is not None else None
            result["currency_display"] = "CNY"

            # 今日盈亏：(现价 - 昨日收盘价) × 股数
            if stock and stock.prev_close_price and stock.prev_close_price > 0:
                result["today_profit_amount"] = float(
                    (current_price - stock.prev_close_price) * position.total_shares
                )
                # 今日涨跌幅（基于昨日收盘价）
                result["price_change_pct"] = float(
                    (current_price - stock.prev_close_price) / stock.prev_close_price * 100
                )

            # 今日盈亏RMB（在today_profit_amount计算后）
            result["today_profit_rmb"] = result["today_profit_amount"] * rate if result["today_profit_amount"] else 0.0

            # 波段退出计划 + 价格区间提醒
            result["swing_plan"], result["swing_alert"] = self._parse_swing_plan(
                position, float(current_price)
            )

            # 生成交易建议
            result["advice"] = self._generate_advice(position, current_price, result["profit_pct"])

            # 生成监控目标价（基于波段交易）
            result["monitor_targets"] = self._generate_monitor_targets(position, current_price)

            # 计算支撑位和阻力位（简化版：基于成本价和当前价）
            avg_cost = float(position.avg_cost) if position.avg_cost else 0
            result["support_price"] = avg_cost * 0.95 if avg_cost > 0 else None
            result["resistance_price"] = avg_cost * 1.15 if avg_cost > 0 else None

            # 获取最新资讯
            from app.services.news_service import NewsService
            news_service = NewsService(self.db)
            latest_news = news_service.get_stock_news(position.stock_symbol, limit=1)
            if latest_news:
                result["latest_news"] = latest_news[0].title
                result["latest_news_url"] = latest_news[0].url
                result["latest_news_source"] = latest_news[0].source

        return result

    def _generate_advice(self, position: Position, current_price: Decimal, profit_pct: float) -> Dict:
        """生成交易建议"""
        avg_cost = float(position.avg_cost) if position.avg_cost else 0
        weight = position.calculate_position_weight(current_price)

        # 负成本持仓（历史卖出已回收全部成本），profit_pct 无参考意义，直接持有
        if avg_cost < 0:
            action = "HOLD"
            reason = "负成本持仓（成本已完全回收），继续持有即可"
        elif profit_pct >= 15:
            action = "SELL"
            reason = f"盈利可观({profit_pct:.1f}%)，考虑减仓锁定利润"
        elif profit_pct >= 8:
            action = "REDUCE"
            reason = f"有一定盈利({profit_pct:.1f}%)，可考虑适当减仓"
        elif profit_pct <= -10:
            action = "BUY"
            reason = f"跌幅较大({profit_pct:.1f}%)，可考虑加仓"
        elif profit_pct <= -5:
            action = "BUY"
            reason = f"回调明显({profit_pct:.1f}%)，关注加仓机会"
        else:
            action = "HOLD"
            reason = f"波动不大({profit_pct:.1f}%)，建议持有观望"

        # 仓位风险警告
        if weight > 50:
            action = "REDUCE"
            reason += f"；⚠️ 仓位过重({weight:.1f}%)，建议减仓分散风险"
        elif weight > 30:
            reason += f"；仓位偏高({weight:.1f}%)，注意控制"

        return {
            "action": action,
            "reason": reason
        }

    def _generate_monitor_targets(self, position: Position, current_price: Decimal) -> List[Dict]:
        """生成监控目标价"""
        targets = []
        avg_cost = float(position.avg_cost) if position.avg_cost else 0

        if avg_cost > 0:
            # 第一目标：成本价+10%
            target1 = avg_cost * 1.10
            targets.append({
                "label": "目标价1",
                "price": target1,
                "reached": float(current_price) >= target1
            })

            # 第二目标：成本价+20%
            target2 = avg_cost * 1.20
            targets.append({
                "label": "目标价2",
                "price": target2,
                "reached": float(current_price) >= target2
            })

        return targets

    def get_portfolio_summary(self) -> Dict:
        """
        获取投资组合汇总
        """
        positions = self.get_all_positions()

        # 汇率（实时，失败则用默认值，不阻塞页面）
        from app.data_sources.exchange_rate_source import ExchangeRateSource
        er = ExchangeRateSource(retry_count=1)
        exchange_rates = {
            "HKD": er.get_rate_to_cny("HKD"),
            "USD": er.get_rate_to_cny("USD"),
            "CNY": Decimal("1.0"),
        }

        # 加载现金余额
        cash_map = {cb.market: cb for cb in self.db.query(CashBalance).all()}

        # 按市场分组统计（先算股票市值）
        market_summary = {}
        total_cost = Decimal("0")

        for pos in positions:
            stock = pos.stock
            if not stock or not stock.current_price:
                continue

            market = stock.market
            if market not in market_summary:
                market_summary[market] = {
                    "positions": [],
                    "total_market_value": Decimal("0"),
                    "total_cost": Decimal("0"),
                    "cash": Decimal("0"),
                    "fund_hkd": Decimal("0"),
                    "currency": pos.currency,
                }

            market_value = pos.calculate_market_value(stock.current_price)
            cost = pos.invested_cost

            market_summary[market]["total_market_value"] += market_value
            market_summary[market]["total_cost"] += cost
            if cost > 0:
                market_summary[market].setdefault("positive_cost", Decimal("0"))
                market_summary[market]["positive_cost"] += cost
            total_cost += cost

        # 注入现金余额和基金余额
        # HKD_FUND = 港元基金（由港股交易自动更新）
        # USD_FUND = 美元基金（由美股交易自动更新）
        # FUND = 富途API返回的合计值，仅用于核对展示
        hkd_fund = Decimal("0")
        usd_fund = Decimal("0")
        fund_assets_hkd = Decimal("0")  # 富途API合计，用于返回给前端展示

        for market, cb in cash_map.items():
            if market == "HKD_FUND":
                hkd_fund = Decimal(str(cb.amount))
                continue
            if market == "USD_FUND":
                usd_fund = Decimal(str(cb.amount))
                continue
            if market == "FUND":
                fund_assets_hkd = Decimal(str(cb.amount))
                continue
            if market not in market_summary:
                currency_map = {"HK": "HKD", "US": "USD", "A": "CNY"}
                market_summary[market] = {
                    "positions": [],
                    "total_market_value": Decimal("0"),
                    "total_cost": Decimal("0"),
                    "cash": Decimal("0"),
                    "fund_hkd": Decimal("0"),
                    "fund_usd": Decimal("0"),
                    "currency": currency_map.get(market, cb.currency),
                }
            market_summary[market]["cash"] = Decimal(str(cb.amount))

        # 确保HK和US市场都有初始化
        for mkt in ["HK", "US"]:
            if mkt not in market_summary:
                market_summary[mkt] = {
                    "positions": [], "total_market_value": Decimal("0"),
                    "total_cost": Decimal("0"), "cash": Decimal("0"),
                    "fund_hkd": Decimal("0"), "fund_usd": Decimal("0"),
                    "currency": "HKD" if mkt == "HK" else "USD",
                }

        # 设置各市场的基金余额
        market_summary["HK"]["fund_hkd"] = hkd_fund
        market_summary["US"]["fund_usd"] = usd_fund

        # 每个市场的 total_with_cash = 股票市值 + 现金 + 基金（各市场独立货币）
        for market, data in market_summary.items():
            if market == "HK":
                data["total_with_cash"] = (
                    data["total_market_value"] + data["cash"] + data.get("fund_hkd", Decimal("0"))
                )
            elif market == "US":
                data["total_with_cash"] = (
                    data["total_market_value"] + data["cash"] + data.get("fund_usd", Decimal("0"))
                )
            else:
                data["total_with_cash"] = data["total_market_value"] + data["cash"]

        # 用 total_with_cash 重新计算各持仓的仓位占比，再加入 positions 列表
        for pos in positions:
            stock = pos.stock
            if not stock or not stock.current_price:
                continue
            market = stock.market
            pos_summary = self.get_position_summary(pos)
            # 用市场总资金（含现金）重新计算权重
            market_total = market_summary[market]["total_with_cash"]
            if market_total > 0 and pos_summary.get("market_value"):
                pos_summary["position_weight"] = float(
                    Decimal(str(pos_summary["market_value"])) / market_total * 100
                )
            market_summary[market]["positions"].append(pos_summary)

        # 计算 RMB 总资产（基金已并入 HK 的 total_with_cash）
        total_market_value_rmb = Decimal("0")
        total_market_value = Decimal("0")
        for market, data in market_summary.items():
            rate = exchange_rates.get(data["currency"], Decimal("1.0"))
            total_market_value_rmb += data["total_with_cash"] * rate
            total_market_value += data["total_market_value"]

        # 计算各市场占总资产比例（含现金，基于RMB）
        for market, data in market_summary.items():
            rate = exchange_rates.get(data["currency"], Decimal("1.0"))
            market_rmb = data["total_with_cash"] * rate
            data["weight_pct"] = float(market_rmb / total_market_value_rmb * 100) if total_market_value_rmb > 0 else 0
            if data["total_cost"] > 0:
                data["profit_pct"] = float(
                    (data["total_market_value"] - data["total_cost"]) / data["total_cost"] * 100
                )
            else:
                data["profit_pct"] = 0
            data["total_market_value"] = float(data["total_market_value"])
            data["total_cost"] = float(data["total_cost"])
            data["cash"] = float(data["cash"])
            data["fund_hkd"] = float(data.get("fund_hkd", 0))
            data["fund_usd"] = float(data.get("fund_usd", 0))
            data["total_with_cash"] = float(data["total_with_cash"])

            # 计算该市场的股票仓位占比和现金仓位占比（现金包含基金）
            total_with_cash = data["total_with_cash"]
            stock_value = data["total_market_value"]
            # 现金仓位 = 普通现金 + 基金
            if market == "HK":
                cash_value = data["cash"] + data.get("fund_hkd", 0)
            elif market == "US":
                cash_value = data["cash"] + data.get("fund_usd", 0)
            else:
                cash_value = data["cash"]
            if total_with_cash > 0:
                data["stock_position_pct"] = float(stock_value / total_with_cash * 100)
                data["cash_position_pct"] = float(cash_value / total_with_cash * 100)
            else:
                data["stock_position_pct"] = 0.0
                data["cash_position_pct"] = 0.0

        # 持仓盈亏（换算为人民币）
        total_profit_rmb = Decimal("0")
        total_cost_rmb = Decimal("0")
        for market, data in market_summary.items():
            rate = exchange_rates.get(data["currency"], Decimal("1.0"))
            mv = Decimal(str(data["total_market_value"]))
            cost = Decimal(str(data["total_cost"]))
            total_profit_rmb += (mv - cost) * rate
            total_cost_rmb += cost * rate

        total_profit = total_profit_rmb
        # 负成本仓位（成本已回收）不计入分母，避免总盈亏%虚高
        total_positive_cost_rmb = Decimal("0")
        for market, data in market_summary.items():
            rate = exchange_rates.get(data["currency"], Decimal("1.0"))
            total_positive_cost_rmb += data.get("positive_cost", Decimal("0")) * rate
        total_profit_pct = float(total_profit_rmb / total_positive_cost_rmb * 100) if total_positive_cost_rmb > 0 else 0

        # 今日盈亏：(现价 - 昨日收盘价) × 股数，换算为人民币
        today_profit = Decimal("0")
        for market, data in market_summary.items():
            rate = exchange_rates.get(data["currency"], Decimal("1.0"))
            for pos in data["positions"]:
                today_profit += Decimal(str(pos.get("today_profit_amount", 0))) * rate

        today_profit_pct = float(today_profit / total_market_value_rmb * 100) if total_market_value_rmb > 0 else 0

        # 把现金作为独立条目注入各市场 positions（供模板展示）
        for market, data in market_summary.items():
            cash = data.get("cash", 0)
            if cash > 0:
                total_with_cash = data.get("total_with_cash", 0)
                cash_weight = cash / total_with_cash * 100 if total_with_cash > 0 else 0
                data["cash_position"] = {
                    "is_cash": True,
                    "market": market,
                    "currency": data["currency"],
                    "amount": cash,
                    "position_weight": cash_weight,
                }

        # 各市场内按仓位占比降序排列（信号排序在路由层处理以避免循环导入）
        for market, data in market_summary.items():
            data["positions"].sort(key=lambda p: p.get("position_weight") or 0, reverse=True)

        return {
            "markets": market_summary,
            "total_positions": len(positions),
            "total_market_value": float(total_market_value),
            "total_market_value_rmb": float(total_market_value_rmb),
            "total_cost": float(total_cost),
            "total_profit": float(total_profit),
            "total_profit_pct": total_profit_pct,
            "today_profit": float(today_profit),
            "fund_assets_hkd": float(fund_assets_hkd),   # 活期基金（港元合计，已归入HK市场）
            "today_profit_pct": today_profit_pct,
        }

    def delete_position(self, position_id: int) -> bool:
        """删除持仓（谨慎使用）"""
        position = self.db.query(Position).filter(Position.id == position_id).first()
        if position:
            self.db.delete(position)
            self.db.commit()
            return True
        return False

    def _parse_swing_plan(self, position: Position, current_price: float):
        """
        解析波段退出计划，返回 (plan, alert)。
        alert: 若当前价格在某个目标区间内，返回该目标信息；否则 None。
        """
        import json
        # 安全访问 swing_plan_json 字段（可能不存在于旧数据库）
        swing_plan_json = getattr(position, 'swing_plan_json', None)
        if not swing_plan_json:
            return None, None

        try:
            plan = json.loads(swing_plan_json)
        except Exception:
            return None, None

        alert = None
        for exit_level in plan.get("exits", []):
            low  = exit_level.get("price_low", 0)
            high = exit_level.get("price_high", 0)
            if low <= current_price <= high:
                alert = {
                    "price_low":  low,
                    "price_high": high,
                    "shares":     exit_level.get("shares"),
                    "note":       exit_level.get("note", ""),
                }
                break

        return plan, alert
