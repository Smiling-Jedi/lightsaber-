"""
信号执行服务

负责T+1日检查PENDING信号是否成交（T+1限价单模式）
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.signal_log import SignalLog
from app.models.stock import Stock
from app.models.sim_position import SimPosition

logger = logging.getLogger(__name__)


class SignalExecutionService:
    """
    信号执行服务 - 负责T+1日检查PENDING信号是否成交

    T+1限价单模式流程：
    1. T日盘后生成BUY信号，计算limit_price，状态=PENDING, entered=False
    2. T+1日检查最低价是否 <= limit_price
       - 是 → 条件单触发，按实际成交价执行买入，状态保持PENDING, entered=True（等待出场）
       - 否 → 信号过期，状态=EXPIRED
    """

    def __init__(self, db: Session):
        self.db = db

    def check_pending_signals(self, target_date: Optional[date] = None) -> Dict:
        """
        检查前一天的PENDING BUY信号，判断T+1是否成交
        应在每日价格刷新后调用（如富途同步完成后）

        Args:
            target_date: 指定检查哪天生成的信号（默认昨天）

        Returns:
            {
                "checked": 检查信号数,
                "executed": 成交数,
                "expired": 过期数,
                "skipped": 跳过数（无价格数据）,
                "details": [...]
            }
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        # 获取target_date生成的PENDING状态BUY信号
        pending_signals = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.action == "BUY",
                SignalLog.status == "PENDING",
                SignalLog.is_simulated == True,
                SignalLog.entered == False,
                func.date(SignalLog.generated_at) == target_date,
            )
            .all()
        )

        results = {
            "checked": len(pending_signals),
            "executed": 0,
            "expired": 0,
            "skipped": 0,
            "details": [],
        }

        for signal in pending_signals:
            try:
                detail = self._process_single_signal(signal)
                results["details"].append(detail)

                if detail["status"] == "EXECUTED":
                    results["executed"] += 1
                elif detail["status"] == "EXPIRED":
                    results["expired"] += 1
                else:
                    results["skipped"] += 1

            except Exception as e:
                logger.error(f"处理信号失败 {signal.symbol}: {e}")
                results["skipped"] += 1
                results["details"].append({
                    "symbol": signal.symbol,
                    "signal_id": signal.id,
                    "status": "ERROR",
                    "error": str(e),
                })

        self.db.commit()
        logger.info(
            f"T+1信号检查完成: 检查{results['checked']}条, "
            f"成交{results['executed']}条, 过期{results['expired']}条"
        )
        return results

    def _process_single_signal(self, signal: SignalLog) -> Dict:
        """处理单个信号的成交检查"""
        symbol = signal.symbol

        # 获取T+1日价格数据
        t1_data = self._get_t1_price_data(symbol)

        if not t1_data:
            return {
                "symbol": symbol,
                "signal_id": signal.id,
                "status": "SKIPPED",
                "reason": "无T+1价格数据",
            }

        t1_low = t1_data.get("low", 0)
        t1_open = t1_data.get("open", 0)
        t1_high = t1_data.get("high", 0)
        t1_close = t1_data.get("close", 0)

        # 记录T+1日价格
        signal.t1_low_price = t1_low
        signal.t1_open_price = t1_open

        # 检查是否有条件单挂价
        limit_price = signal.limit_price
        if not limit_price or limit_price <= 0:
            return {
                "symbol": symbol,
                "signal_id": signal.id,
                "status": "SKIPPED",
                "reason": "无有效limit_price",
            }

        # 判断成交条件：最低价 <= 条件单挂价
        if t1_low <= limit_price:
            # 成交！计算实际成交价
            execute_price = self._calculate_execute_price(
                t1_open=t1_open,
                t1_low=t1_low,
                limit_price=limit_price,
            )

            # 执行买入
            self._execute_pending_buy(signal, execute_price, t1_data)

            # 计算滑点（用于统计）
            slippage = execute_price - t1_open if t1_open > 0 else 0

            return {
                "symbol": symbol,
                "signal_id": signal.id,
                "status": "EXECUTED",
                "limit_price": limit_price,
                "execute_price": execute_price,
                "t1_open": t1_open,
                "t1_low": t1_low,
                "slippage": round(slippage, 2),
                "note": f"T+1成交，条件单挂价{limit_price}，实际成交价{execute_price}",
            }
        else:
            # 未成交，信号过期
            signal.status = "EXPIRED"
            signal.note = (
                f"T+1最低价({t1_low}) > 条件单挂价({limit_price})，未触发，信号过期"
            )

            return {
                "symbol": symbol,
                "signal_id": signal.id,
                "status": "EXPIRED",
                "limit_price": limit_price,
                "t1_low": t1_low,
                "reason": f"最低价({t1_low}) > 挂价({limit_price})",
            }

    def _get_t1_price_data(self, symbol: str) -> Optional[Dict]:
        """
        获取T+1日价格数据（最低价、开盘价等）

        优先从Stock表获取已刷新的价格数据
        """
        stock = self.db.query(Stock).filter(Stock.symbol == symbol).first()

        if not stock:
            logger.warning(f"未找到股票记录: {symbol}")
            return None

        # 检查价格是否已更新（有开盘价说明是T+1数据）
        if stock.open_price is None or stock.low_price is None:
            logger.debug(f"股票{symbol}无T+1价格数据")
            return None

        return {
            "low": float(stock.low_price),
            "open": float(stock.open_price),
            "high": float(stock.high_price) if stock.high_price else 0,
            "close": float(stock.current_price) if stock.current_price else 0,
        }

    def _calculate_execute_price(
        self,
        t1_open: float,
        t1_low: float,
        limit_price: float,
    ) -> float:
        """
        计算条件单触发时的实际成交价

        场景A：开盘直接低于limit_price → 按开盘价成交（更优价格）
        场景B：盘中跌至limit_price → 按limit_price成交

        Args:
            t1_open: T+1开盘价
            t1_low: T+1最低价
            limit_price: 条件单挂价

        Returns:
            实际成交价
        """
        # 如果开盘价就低于limit_price，开盘即触发，按开盘价成交
        if t1_open <= limit_price:
            return round(t1_open, 2)

        # 否则是盘中触发，按limit_price成交
        # 注意：实际成交价可能略优于limit_price（取决于触发时的市场价格）
        # 这里保守按limit_price计算
        return round(limit_price, 2)

    def _execute_pending_buy(
        self,
        signal: SignalLog,
        execute_price: float,
        t1_data: Dict,
    ):
        """
        执行待执行的BUY信号

        调用分批建仓逻辑（与原有_sim_buy一致）
        """
        from datetime import date as dt_date

        symbol = signal.symbol
        name = signal.name or symbol
        category = signal.category or "large_tech"

        # 获取或创建模拟持仓
        sim_pos = self.db.query(SimPosition).filter_by(symbol=symbol).first()

        # 计算股数
        if signal.recommended_shares and signal.recommended_shares > 0:
            # 使用信号生成时计算的建议股数
            first_batch_shares = signal.recommended_shares
            # 如果没有第二批数据，默认总股数是第一批的2倍（B+D方案）
            second_batch_shares = signal.recommended_shares_second or first_batch_shares
        else:
            # 回退逻辑：基于资金估算
            position_value = signal.position_value_estimated or 10000
            first_batch_shares = max(int((position_value * 0.5) / execute_price), 1)
            second_batch_shares = first_batch_shares

        # 执行第一批建仓
        if sim_pos:
            # 已有持仓：加权平均成本
            total_cost = (sim_pos.shares * (sim_pos.avg_cost or execute_price)
                          + first_batch_shares * execute_price)
            new_total_shares = sim_pos.shares + first_batch_shares

            sim_pos.shares = new_total_shares
            sim_pos.avg_cost = total_cost / new_total_shares
            sim_pos.last_price = execute_price
            sim_pos.market_value = new_total_shares * execute_price
            sim_pos.updated_at = datetime.now()

            # 更新分批状态
            sim_pos.batch_status = "FIRST_FILLED"
            sim_pos.first_batch_shares = first_batch_shares
            sim_pos.first_batch_price = execute_price
            sim_pos.first_batch_date = dt_date.today()
            sim_pos.second_batch_pending = second_batch_shares
        else:
            # 新建持仓
            sim_pos = SimPosition(
                symbol=symbol,
                name=name,
                category=category,
                snapshot_date=dt_date.today(),
                shares=first_batch_shares,
                avg_cost=execute_price,
                last_price=execute_price,
                market_value=first_batch_shares * execute_price,
                initial_shares=0,
                initial_avg_cost=None,
                batch_status="FIRST_FILLED",
                first_batch_shares=first_batch_shares,
                first_batch_price=execute_price,
                first_batch_date=dt_date.today(),
                second_batch_pending=second_batch_shares,
            )
            self.db.add(sim_pos)

        # 更新信号状态
        signal.status = "PENDING"  # 保持PENDING，等待出场
        signal.entered = True
        signal.entered_at = datetime.now()
        signal.entered_price = execute_price

        # 记录成交详情
        slippage = execute_price - t1_data.get("open", execute_price)
        signal.note = (
            f"T+1限价单成交: 条件单挂价{signal.limit_price}, "
            f"实际成交价{execute_price}, 开盘价{t1_data.get('open')}, "
            f"滑点{slippage:.2f}"
        )

        logger.info(
            f"PENDING信号成交: {symbol} @ {execute_price}, "
            f"第一批{first_batch_shares}股, 待第二批{second_batch_shares}股"
        )

    def check_and_expire_stale_signals(self) -> int:
        """
        自动将超过3个交易日仍未入场的PENDING信号标记为CANCELLED
        （信号时效性设计：3日内未入场即失效）

        Returns:
            处理的信号数量
        """
        cutoff = datetime.now() - timedelta(days=4)  # 3交易日（含周末约4自然日）

        stale_signals = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.status == "PENDING",
                SignalLog.entered == False,
                SignalLog.generated_at < cutoff,
            )
            .all()
        )

        for signal in stale_signals:
            signal.status = "CANCELLED"
            signal.note = "超过3个交易日未入场，信号自动失效"
            logger.info(f"信号自动失效: {signal.symbol} (生成于{signal.generated_at.date()})")

        self.db.commit()
        return len(stale_signals)
