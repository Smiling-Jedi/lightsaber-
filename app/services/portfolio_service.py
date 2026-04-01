"""
组合管理服务 - 统一处理真实/模拟账户的资产计算与快照

核心功能：
1. 总资产计算（实时）- 真实/模拟隔离
2. 资产快照（每日/交易后）
3. 资金流水记录
4. 资产曲线查询
5. 对账验证
"""
import json
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.position import Position
from app.models.trade import Trade
from app.models.cash import CashBalance
from app.models.sim_position import SimPosition
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.cash_flow_log import CashFlowLog
from app.models.signal_execution import SignalExecution
from app.data_sources.exchange_rate_source import ExchangeRateSource
from app.services.position_service import PositionService

logger = logging.getLogger(__name__)


@dataclass
class AssetBreakdown:
    """资产明细数据结构"""
    stocks: Dict[str, Dict]  # symbol -> {shares, price, value, cost, profit}
    cash: Dict[str, Decimal]  # currency -> amount
    funds: Dict[str, Decimal]  # currency -> amount (货币基金)
    total_by_currency: Dict[str, Decimal]
    total_rmb: Decimal


class PortfolioService:
    """
    组合管理服务

    使用示例：
        svc = PortfolioService(db)

        # 获取实时总资产
        assets = svc.get_total_assets(account_type="REAL")

        # 拍摄快照
        snapshot = svc.take_snapshot(account_type="REAL", note="收盘快照")

        # 记录资金流水
        svc.record_cash_flow(
            account_type="SIMULATED",
            flow_type="TRADE_BUY",
            market="HK",
            currency="HKD",
            amount=Decimal("-50000"),
            trade_id=123,
            description="买入小米集团"
        )

        # 获取资产曲线
        curve = svc.get_asset_curve("REAL", days=30)
    """

    # 模拟账户的现金市场标识
    SIM_CASH_MARKETS = {
        "HKD": "SIM_HKD",
        "USD": "SIM_USD",
        "CNY": "SIM_CNY",
    }

    def __init__(self, db: Session):
        self.db = db
        self.position_svc = PositionService(db)
        self._exchange_rate = ExchangeRateSource(retry_count=1)

    # ═══════════════════════════════════════════════════════
    # 1. 总资产计算（实时）
    # ═══════════════════════════════════════════════════════

    def get_total_assets(self, account_type: str, detail: bool = False) -> Dict[str, Any]:
        """
        计算总资产（实时）

        Args:
            account_type: "REAL" 或 "SIMULATED"
            detail: 是否返回明细

        Returns:
            {
                "total_rmb": Decimal,
                "total_hkd": Decimal,
                "total_usd": Decimal,
                "total_cny": Decimal,
                "breakdown": AssetBreakdown (如果 detail=True)
            }
        """
        if account_type == "REAL":
            return self._calc_real_assets(detail)
        elif account_type == "SIMULATED":
            return self._calc_simulated_assets(detail)
        else:
            raise ValueError(f"account_type must be REAL or SIMULATED, got {account_type}")

    def _calc_real_assets(self, detail: bool = False) -> Dict[str, Any]:
        """计算真实账户总资产"""
        # 从 position_service 获取组合汇总
        portfolio = self.position_svc.get_portfolio_summary()

        # 提取各市场数据
        markets = portfolio.get("markets", {})

        total_hkd = Decimal("0")
        total_usd = Decimal("0")
        total_cny = Decimal("0")

        stocks_detail = {}

        for market, data in markets.items():
            currency = data.get("currency", "CNY")
            market_value = Decimal(str(data.get("total_market_value", 0)))
            cash = Decimal(str(data.get("cash", 0)))
            fund_hkd = Decimal(str(data.get("fund_hkd", 0)))
            fund_usd = Decimal(str(data.get("fund_usd", 0)))

            # 该市场总值 = 股票市值 + 现金 + 基金
            market_total = market_value + cash
            if market == "HK":
                market_total += fund_hkd
            elif market == "US":
                market_total += fund_usd

            if currency == "HKD":
                total_hkd += market_total
            elif currency == "USD":
                total_usd += market_total
            else:
                total_cny += market_total

            # 收集股票明细
            if detail:
                for pos in data.get("positions", []):
                    if pos.get("is_cash"):
                        continue
                    symbol = pos.get("symbol", "")
                    stocks_detail[symbol] = {
                        "shares": pos.get("total_shares", 0),
                        "price": Decimal(str(pos.get("current_price", 0))),
                        "value": Decimal(str(pos.get("market_value", 0))),
                        "cost": Decimal(str(pos.get("avg_cost", 0))) * pos.get("total_shares", 0),
                        "profit": Decimal(str(pos.get("profit", 0))),
                        "currency": currency,
                    }

        # 折算为人民币
        rates = {
            "HKD": self._get_rate("HKD"),
            "USD": self._get_rate("USD"),
            "CNY": Decimal("1"),
        }

        total_rmb = (
            total_hkd * rates["HKD"] +
            total_usd * rates["USD"] +
            total_cny * rates["CNY"]
        )

        result = {
            "total_rmb": total_rmb,
            "total_hkd": total_hkd,
            "total_usd": total_usd,
            "total_cny": total_cny,
        }

        if detail:
            result["breakdown"] = {
                "stocks": stocks_detail,
                "cash": {
                    "HKD": self._get_cash_balance("HK"),
                    "USD": self._get_cash_balance("US"),
                    "CNY": self._get_cash_balance("A"),
                },
                "funds": {
                    "HKD": self._get_cash_balance("FUND"),  # 富途API返回的基金合计
                    "USD": Decimal("0"),  # 美元基金并入FUND（HKD计）
                },
            }

        return result

    def _calc_simulated_assets(self, detail: bool = False) -> Dict[str, Any]:
        """计算模拟账户总资产"""
        # 获取所有模拟持仓
        sim_positions = self.db.query(SimPosition).all()

        total_hkd = Decimal("0")
        total_usd = Decimal("0")
        total_cny = Decimal("0")

        stocks_detail = {}

        for pos in sim_positions:
            symbol = pos.symbol
            currency = pos.currency or "HKD"
            market_value = Decimal(str(pos.market_value or 0))

            if currency == "HKD":
                total_hkd += market_value
            elif currency == "USD":
                total_usd += market_value
            else:
                total_cny += market_value

            if detail:
                stocks_detail[symbol] = {
                    "shares": pos.shares,
                    "price": Decimal(str(pos.last_price or 0)),
                    "value": market_value,
                    "cost": Decimal(str(pos.avg_cost or 0)) * pos.shares,
                    "profit": market_value - (Decimal(str(pos.avg_cost or 0)) * pos.shares),
                    "currency": currency,
                    "batch_status": pos.batch_status,
                }

        # 加上模拟现金
        sim_cash_hkd = self._get_cash_balance(self.SIM_CASH_MARKETS["HKD"])
        sim_cash_usd = self._get_cash_balance(self.SIM_CASH_MARKETS["USD"])
        sim_cash_cny = self._get_cash_balance(self.SIM_CASH_MARKETS["CNY"])

        total_hkd += sim_cash_hkd
        total_usd += sim_cash_usd
        total_cny += sim_cash_cny

        # 折算为人民币
        rates = {
            "HKD": self._get_rate("HKD"),
            "USD": self._get_rate("USD"),
            "CNY": Decimal("1"),
        }

        total_rmb = (
            total_hkd * rates["HKD"] +
            total_usd * rates["USD"] +
            total_cny * rates["CNY"]
        )

        result = {
            "total_rmb": total_rmb,
            "total_hkd": total_hkd,
            "total_usd": total_usd,
            "total_cny": total_cny,
        }

        if detail:
            result["breakdown"] = {
                "stocks": stocks_detail,
                "cash": {
                    "HKD": sim_cash_hkd,
                    "USD": sim_cash_usd,
                    "CNY": sim_cash_cny,
                },
                "funds": {"HKD": Decimal("0"), "USD": Decimal("0")},
            }

        return result

    def _get_rate(self, currency: str) -> Decimal:
        """获取汇率"""
        if currency == "CNY":
            return Decimal("1")
        try:
            return Decimal(str(self._exchange_rate.get_rate_to_cny(currency)))
        except Exception as e:
            logger.warning(f"获取汇率失败 {currency}: {e}")
            # 使用默认汇率
            defaults = {"HKD": Decimal("0.92"), "USD": Decimal("7.2")}
            return defaults.get(currency, Decimal("1"))

    def _get_cash_balance(self, market: str) -> Decimal:
        """获取指定市场的现金余额"""
        cb = self.db.query(CashBalance).filter(CashBalance.market == market).first()
        return Decimal(str(cb.amount)) if cb else Decimal("0")

    # ═══════════════════════════════════════════════════════
    # 2. 资产快照
    # ═══════════════════════════════════════════════════════

    def take_snapshot(self, account_type: str, note: str = None) -> PortfolioSnapshot:
        """
        拍摄总资产快照

        Args:
            account_type: "REAL" 或 "SIMULATED"
            note: 备注（如"收盘快照"、"交易后快照"）

        Returns:
            PortfolioSnapshot 对象
        """
        # 计算当前资产（含明细）
        assets = self.get_total_assets(account_type, detail=True)
        breakdown = assets.get("breakdown", {})

        # 检查今天是否已有快照，有则更新，无则创建
        today = date.today()
        existing = self.db.query(PortfolioSnapshot).filter(
            and_(
                PortfolioSnapshot.snapshot_date == today,
                PortfolioSnapshot.account_type == account_type
            )
        ).first()

        if existing:
            # 更新现有快照
            snapshot = existing
            snapshot.total_assets_hkd = assets["total_hkd"]
            snapshot.total_assets_usd = assets["total_usd"]
            snapshot.total_assets_cny = assets["total_cny"]
            snapshot.total_assets_rmb = assets["total_rmb"]
            snapshot.set_breakdown(breakdown)
            snapshot.note = note or snapshot.note
            snapshot.created_at = datetime.now()
        else:
            # 创建新快照
            snapshot = PortfolioSnapshot(
                snapshot_date=today,
                account_type=account_type,
                total_assets_hkd=assets["total_hkd"],
                total_assets_usd=assets["total_usd"],
                total_assets_cny=assets["total_cny"],
                total_assets_rmb=assets["total_rmb"],
                note=note,
            )
            snapshot.set_breakdown(breakdown)
            self.db.add(snapshot)

        self.db.commit()
        logger.info(f"资产快照已记录: {account_type} @ {today}, 总资产={assets['total_rmb']:.2f} RMB")
        return snapshot

    def get_latest_snapshot(self, account_type: str) -> Optional[PortfolioSnapshot]:
        """获取最新的资产快照"""
        return self.db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.account_type == account_type
        ).order_by(PortfolioSnapshot.snapshot_date.desc()).first()

    def get_asset_curve(self, account_type: str, days: int = 30) -> List[PortfolioSnapshot]:
        """
        获取资产曲线数据

        Args:
            account_type: "REAL" 或 "SIMULATED"
            days: 查询天数

        Returns:
            PortfolioSnapshot 列表（按日期升序）
        """
        start_date = date.today() - timedelta(days=days)
        return self.db.query(PortfolioSnapshot).filter(
            and_(
                PortfolioSnapshot.account_type == account_type,
                PortfolioSnapshot.snapshot_date >= start_date
            )
        ).order_by(PortfolioSnapshot.snapshot_date.asc()).all()

    # ═══════════════════════════════════════════════════════
    # 3. 资金流水记录
    # ═══════════════════════════════════════════════════════

    def record_cash_flow(
        self,
        account_type: str,
        flow_type: str,
        market: str,
        currency: str,
        amount: Decimal,
        trade_id: int = None,
        signal_log_id: int = None,
        position_id: int = None,
        description: str = "",
        trade_date: date = None,
    ) -> CashFlowLog:
        """
        记录资金流水

        Args:
            account_type: "REAL" 或 "SIMULATED"
            flow_type: DEPOSIT/WITHDRAW/TRADE_BUY/TRADE_SELL/DIVIDEND/etc
            market: HK/US/A/SIM_HKD/SIM_USD/SIM_CNY
            currency: HKD/USD/CNY
            amount: 变动金额（正数流入，负数流出）
            trade_id: 关联的交易ID
            signal_log_id: 关联的信号ID
            position_id: 关联的持仓ID
            description: 描述
            trade_date: 业务日期（默认今天）

        Returns:
            CashFlowLog 对象
        """
        # 计算变动后的余额
        current_balance = self._get_cash_balance(market)
        new_balance = current_balance + amount

        log = CashFlowLog(
            account_type=account_type,
            flow_type=flow_type,
            market=market,
            currency=currency,
            amount=amount,
            balance_after=new_balance,
            trade_id=trade_id,
            signal_log_id=signal_log_id,
            position_id=position_id,
            trade_date=trade_date or date.today(),
            description=description,
        )
        self.db.add(log)
        self.db.commit()

        logger.info(
            f"资金流水: {account_type} {flow_type} {amount} {currency} "
            f"({market}), 余额={new_balance}"
        )
        return log

    def get_cash_flows(
        self,
        account_type: str,
        start_date: date = None,
        end_date: date = None,
        market: str = None,
    ) -> List[CashFlowLog]:
        """
        查询资金流水

        Args:
            account_type: "REAL" 或 "SIMULATED"
            start_date: 开始日期
            end_date: 结束日期
            market: 筛选特定市场

        Returns:
            CashFlowLog 列表
        """
        query = self.db.query(CashFlowLog).filter(
            CashFlowLog.account_type == account_type
        )

        if start_date:
            query = query.filter(CashFlowLog.trade_date >= start_date)
        if end_date:
            query = query.filter(CashFlowLog.trade_date <= end_date)
        if market:
            query = query.filter(CashFlowLog.market == market)

        return query.order_by(CashFlowLog.created_at.desc()).all()

    def verify_balance(self, account_type: str, market: str) -> Tuple[bool, Decimal, Decimal]:
        """
        验证现金余额是否与流水一致

        Returns:
            (是否一致, 当前余额, 流水计算余额)
        """
        current_balance = self._get_cash_balance(market)

        # 计算流水的累计变动
        total_flow = self.db.query(func.sum(CashFlowLog.amount)).filter(
            and_(
                CashFlowLog.account_type == account_type,
                CashFlowLog.market == market
            )
        ).scalar() or Decimal("0")

        # 这里假设初始余额为0，实际应用中需要记录初始余额
        # 或者从第一次流水开始计算
        calculated_balance = total_flow

        is_match = abs(current_balance - calculated_balance) < Decimal("0.01")
        return is_match, current_balance, calculated_balance

    # ═══════════════════════════════════════════════════════
    # 4. 信号执行记录
    # ═══════════════════════════════════════════════════════

    def create_signal_execution(
        self,
        signal_log_id: int,
        symbol: str,
        recommended_action: str,
        recommended_shares: int,
        recommended_price: Decimal,
    ) -> SignalExecution:
        """
        创建信号执行记录（信号生成时调用）

        Args:
            signal_log_id: 关联的信号日志ID
            symbol: 股票代码
            recommended_action: BUY/SELL
            recommended_shares: 建议股数
            recommended_price: 信号触发时的价格

        Returns:
            SignalExecution 对象
        """
        execution = SignalExecution(
            signal_log_id=signal_log_id,
            symbol=symbol,
            recommended_action=recommended_action,
            recommended_shares=recommended_shares,
            recommended_price=recommended_price,
            status="PENDING",
        )
        self.db.add(execution)
        self.db.commit()
        return execution

    def record_signal_execution(
        self,
        execution_id: int,
        trade_ids: List[int],
        executed_shares: int,
        executed_price: Decimal,
        executed_at: datetime = None,
    ) -> SignalExecution:
        """
        记录信号执行结果（交易完成后调用）

        Args:
            execution_id: SignalExecution ID
            trade_ids: 产生的交易ID列表
            executed_shares: 实际执行股数
            executed_price: 实际执行均价
            executed_at: 执行时间

        Returns:
            SignalExecution 对象
        """
        execution = self.db.query(SignalExecution).get(execution_id)
        if not execution:
            raise ValueError(f"SignalExecution {execution_id} not found")

        execution.record_execution(
            trade_ids=trade_ids,
            executed_shares=executed_shares,
            executed_price=executed_price,
            executed_at=executed_at,
        )
        self.db.commit()
        return execution

    def get_signal_execution_stats(self, symbol: str = None, days: int = 30) -> Dict:
        """
        获取信号执行统计

        Returns:
            {
                "total_signals": int,
                "executed": int,
                "avg_slippage_pct": float,
                "avg_delay_minutes": float,
                "avg_fill_rate": float,
            }
        """
        start_date = date.today() - timedelta(days=days)
        query = self.db.query(SignalExecution).filter(
            SignalExecution.trade_date >= start_date
        )

        if symbol:
            query = query.filter(SignalExecution.symbol == symbol)

        executions = query.all()

        if not executions:
            return {
                "total_signals": 0,
                "executed": 0,
                "avg_slippage_pct": 0,
                "avg_delay_minutes": 0,
                "avg_fill_rate": 0,
            }

        total = len(executions)
        executed = [e for e in executions if e.status == "EXECUTED"]

        avg_slippage = sum(
            e.slippage_pct for e in executed if e.slippage_pct
        ) / len(executed) if executed else 0

        avg_delay = sum(
            e.delay_minutes for e in executed if e.delay_minutes
        ) / len(executed) if executed else 0

        avg_fill = sum(
            e.fill_rate_pct for e in executed if e.fill_rate_pct
        ) / len(executed) if executed else 0

        return {
            "total_signals": total,
            "executed": len(executed),
            "avg_slippage_pct": float(avg_slippage) if avg_slippage else 0,
            "avg_delay_minutes": float(avg_delay) if avg_delay else 0,
            "avg_fill_rate": float(avg_fill) if avg_fill else 0,
        }

    # ═══════════════════════════════════════════════════════
    # 5. 综合查询
    # ═══════════════════════════════════════════════════════

    def get_portfolio_report(self, account_type: str) -> Dict[str, Any]:
        """
        获取组合完整报告（用于展示）

        Returns:
            {
                "account_type": str,
                "timestamp": str,
                "total_assets": {
                    "rmb": Decimal,
                    "hkd": Decimal,
                    "usd": Decimal,
                    "cny": Decimal,
                },
                "breakdown": {...},
                "latest_snapshot": {...},
                "cash_flows_recent": [...],
            }
        """
        assets = self.get_total_assets(account_type, detail=True)
        latest_snapshot = self.get_latest_snapshot(account_type)

        # 最近5条资金流水
        recent_flows = self.db.query(CashFlowLog).filter(
            CashFlowLog.account_type == account_type
        ).order_by(CashFlowLog.created_at.desc()).limit(5).all()

        return {
            "account_type": account_type,
            "timestamp": datetime.now().isoformat(),
            "total_assets": {
                "rmb": float(assets["total_rmb"]),
                "hkd": float(assets["total_hkd"]),
                "usd": float(assets["total_usd"]),
                "cny": float(assets["total_cny"]),
            },
            "breakdown": assets.get("breakdown"),
            "latest_snapshot": latest_snapshot.to_dict() if latest_snapshot else None,
            "cash_flows_recent": [f.to_dict() for f in recent_flows],
        }
