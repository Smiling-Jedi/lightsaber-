"""
信号日志服务

负责：
  - 保存信号记录（BUY/SELL 才保存，WATCH/HOLD 不记录）
  - 标记入场（用户确认后调用）
  - 更新结果（止损/达标/持有期满）
  - 统计绩效（胜率/EV/盈亏比）
  - 模拟交易：自动入场/出场
"""
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict

from dateutil.relativedelta import relativedelta

from sqlalchemy.orm import Session

from app.models.signal_log import SignalLog
from app.models.sim_position import SimPosition
from app.services.signal_service import SignalResult

logger = logging.getLogger(__name__)


class SignalLogService:

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────
    # 写入
    # ─────────────────────────────────────────────────────

    def save_signal(self, result: SignalResult) -> Optional[SignalLog]:
        """
        将信号结果写入日志。
        只保存 BUY / SELL，WATCH / HOLD 不记录。
        同一只股票同一天已有记录则跳过（幂等）。
        """
        if result.action not in ("BUY", "SELL"):
            return None

        # 幂等检查：今天同一只股票同一action已有记录（只看真实信号，不与模拟信号冲突）
        today = datetime.now().date()
        exists = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.symbol == result.symbol,
                SignalLog.action == result.action,
                SignalLog.is_simulated == False,
                SignalLog.generated_at >= datetime(today.year, today.month, today.day),
            )
            .first()
        )
        if exists:
            logger.info(f"信号已存在，跳过保存: {result.symbol} {result.action}")
            return exists

        params = result.backtest_ref or {}

        # 从 TradeInstruction 提取建议股数等信息
        instruction = result.instruction
        recommended_shares = 0
        recommended_shares_second = 0
        entry_price_ref = 0.0
        position_value = 0.0
        if instruction:
            recommended_shares = getattr(instruction, 'recommended_shares', 0) or 0
            recommended_shares_second = getattr(instruction, 'recommended_shares_second', 0) or 0
            entry_price_ref = getattr(instruction, 'entry_price_reference', 0.0) or 0.0
            position_value = getattr(instruction, 'position_value_estimated', 0.0) or 0.0

        log = SignalLog(
            symbol        = result.symbol,
            name          = result.name,
            category      = result.category,
            generated_at  = datetime.now(),
            action        = result.action,
            confidence    = result.confidence,
            entry_price   = result.indicators.get("close"),
            stop_loss_pct = result.stop_loss_pct,
            target_pct    = result.target_pct_1,
            hold_months   = params.get("hold_months"),
            market_env    = result.market_env,
            wf_robust     = params.get("wf_robust"),
            triggers_json = json.dumps(result.triggers, ensure_ascii=False),
            conflicts_json= json.dumps(result.conflicts, ensure_ascii=False),
            status        = "PENDING",
            # 交易建议
            recommended_shares       = recommended_shares if recommended_shares > 0 else None,
            recommended_shares_second= recommended_shares_second if recommended_shares_second > 0 else None,
            entry_price_reference    = entry_price_ref if entry_price_ref > 0 else None,
            position_value_estimated = position_value if position_value > 0 else None,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        logger.info(f"信号已保存: {result.symbol} {result.action} id={log.id}")
        return log

    def mark_entered(self, log_id: int, entered_price: float) -> Optional[SignalLog]:
        """用户确认入场，记录实际入场价"""
        log = self.db.get(SignalLog, log_id)
        if not log:
            return None
        log.entered = True
        log.entered_at = datetime.now()
        log.entered_price = entered_price
        self.db.commit()
        return log

    def mark_exit(
        self,
        log_id: int,
        exit_price: float,
        status: str,   # HIT_TARGET / HIT_STOP / EXPIRED / CANCELLED / SKIPPED
        note: str = "",
    ) -> Optional[SignalLog]:
        """记录出场结果"""
        if status not in ("HIT_TARGET", "HIT_STOP", "EXPIRED", "CANCELLED", "SKIPPED"):
            raise ValueError(f"非法status: {status}")

        log = self.db.get(SignalLog, log_id)
        if not log:
            return None

        log.status = status
        log.exit_price = exit_price
        log.exit_date = datetime.now()
        log.actual_pct = log.compute_actual_pct()
        log.note = note
        self.db.commit()
        return log

    # ─────────────────────────────────────────────────────
    # 模拟交易
    # ─────────────────────────────────────────────────────

    def save_signal_simulated(self, result: SignalResult) -> Optional[SignalLog]:
        """
        模拟交易入场：信号触发后自动以收盘价入场。
        只处理 BUY / SELL，幂等（同股同日已有则跳过）。
        """
        if result.action not in ("BUY", "SELL"):
            return None

        today = datetime.now().date()
        exists = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.symbol == result.symbol,
                SignalLog.action == result.action,
                SignalLog.is_simulated == True,
                SignalLog.generated_at >= datetime(today.year, today.month, today.day),
            )
            .first()
        )
        if exists:
            return exists

        entry_price = result.indicators.get("close")
        params = result.backtest_ref or {}

        # 从 TradeInstruction 提取建议股数等信息
        instruction = result.instruction
        recommended_shares = 0
        recommended_shares_second = 0
        entry_price_ref = 0.0
        position_value = 0.0
        limit_price = 0.0
        if instruction:
            recommended_shares = getattr(instruction, 'recommended_shares', 0) or 0
            recommended_shares_second = getattr(instruction, 'recommended_shares_second', 0) or 0
            entry_price_ref = getattr(instruction, 'entry_price_reference', 0.0) or 0.0
            position_value = getattr(instruction, 'position_value_estimated', 0.0) or 0.0
            limit_price = getattr(instruction, 'limit_price', 0.0) or 0.0

        # 【T+1限价单模式】BUY和SELL信号都改为PENDING状态，不立即入场/出场
        is_pending = result.action in ("BUY", "SELL")

        log = SignalLog(
            symbol         = result.symbol,
            name           = result.name,
            category       = result.category,
            generated_at   = datetime.now(),
            action         = result.action,
            confidence     = result.confidence,
            entry_price    = entry_price,
            stop_loss_pct  = result.stop_loss_pct,
            target_pct     = result.target_pct_1,
            hold_months    = params.get("hold_months"),
            market_env     = result.market_env,
            wf_robust      = params.get("wf_robust"),
            triggers_json  = json.dumps(result.triggers, ensure_ascii=False),
            conflicts_json = json.dumps(result.conflicts, ensure_ascii=False),
            is_simulated   = True,
            # 【修改】BUY和SELL信号都改为PENDING，entered=False
            entered        = False if is_pending else True,
            entered_at     = None if is_pending else datetime.now(),
            entered_price  = None if is_pending else entry_price,
            status         = "PENDING",
            # T+1限价单模式新增字段
            limit_price    = limit_price if limit_price > 0 else None,
            # 交易建议
            recommended_shares       = recommended_shares if recommended_shares > 0 else None,
            recommended_shares_second= recommended_shares_second if recommended_shares_second > 0 else None,
            entry_price_reference    = entry_price_ref if entry_price_ref > 0 else None,
            position_value_estimated = position_value if position_value > 0 else None,
        )
        self.db.add(log)

        # 【修改】BUY和SELL信号都不再立即执行，等待T+1成交检查
        if is_pending:
            logger.info(f"模拟{result.action}信号待执行: {result.symbol}，条件单挂价={limit_price}")

        self.db.commit()
        self.db.refresh(log)
        logger.info(f"模拟信号已保存: {result.symbol} {result.action} id={log.id}")
        return log

    def _sim_buy(self, symbol: str, name: str, category: str,
                 entry_price: float, params: dict, instruction=None):
        """
        B+D方案：分批建仓买入

        【分批逻辑】
        - 第一批：信号日买入50%（根据sizing_model计算总仓位）
        - 第二批：等待回调3%或3天后买入剩余50%

        【股数计算优先级】
        1. 优先使用 instruction 中已计算的建议股数（recommended_shares）
           - 这是 SignalService._calculate_shares() 根据真实持仓和Kelly上限算出的
           - 第一批 = recommended_shares
           - 第二批 = recommended_shares_second（如为空，默认=第一批）

        2. 如 instruction 缺失，回退到旧逻辑（不推荐）
           - 基于$100k基数 + Kelly% 估算

        【示例】
        UNH案例：
        - Kelly上限 = 16.6%
        - 当前无持仓，可用空间 = 16.6%
        - 第一批50% = 8.3%仓位 → 46股 @ $272.28 ≈ $12,524
        - 第二批待建仓 = 46股（等待回调3%或3天后）
        """
        from datetime import date
        sim_pos = self.db.query(SimPosition).filter_by(symbol=symbol).first()

        # 优先使用 instruction 中已计算的建议股数
        if instruction and getattr(instruction, 'recommended_shares', 0) > 0:
            total_shares = getattr(instruction, 'recommended_shares', 0) + getattr(instruction, 'recommended_shares_second', 0)
            # 如果没有第二批数据，默认总股数是第一批的2倍（B+D方案）
            if getattr(instruction, 'recommended_shares_second', 0) == 0:
                total_shares = getattr(instruction, 'recommended_shares', 0) * 2
        else:
            # 回退到旧逻辑（使用$100k基数计算，不推荐）
            total_shares = self._calc_shares_by_model(symbol, entry_price, params, instruction, sim_pos)

        # 第一批：50%
        first_batch_shares = max(int(total_shares * 0.5), 1)
        second_batch_shares = total_shares - first_batch_shares

        if sim_pos:
            # 检查是否有待完成的第二批建仓
            if sim_pos.batch_status == "FIRST_FILLED" and sim_pos.second_batch_pending > 0:
                # 触发第二批建仓（回调3%或已过3天）
                self._execute_second_batch(sim_pos, entry_price, symbol, name)
            else:
                # 新信号：执行第一批建仓
                self._execute_first_batch(sim_pos, first_batch_shares, second_batch_shares,
                                          entry_price, symbol, name, category)
        else:
            # 新建持仓，执行第一批建仓
            sim_pos = SimPosition(
                symbol=symbol,
                name=name,
                category=category,
                snapshot_date=date.today(),
                shares=first_batch_shares,
                avg_cost=entry_price,
                last_price=entry_price,
                market_value=first_batch_shares * entry_price,
                initial_shares=0,
                initial_avg_cost=None,
                batch_status="FIRST_FILLED",
                first_batch_shares=first_batch_shares,
                first_batch_price=entry_price,
                first_batch_date=date.today(),
                second_batch_pending=second_batch_shares,
            )
            self.db.add(sim_pos)
            logger.info(f"分批建仓第一批: {symbol} {first_batch_shares}股 @ {entry_price}, "
                       f"待第二批: {second_batch_shares}股")
        self.db.flush()

    def _calc_shares_by_model(self, symbol: str, entry_price: float, params: dict,
                              instruction, sim_pos) -> int:
        """
        根据仓位模型计算目标股数
        支持：KELLY_HALF / FIXED_RISK / VOLATILITY_ADJUSTED
        """
        sizing_model = "KELLY_HALF"
        sizing_params = {}

        # 从instruction获取模型参数
        if instruction:
            sizing_model = instruction.sizing_model
            sizing_params = instruction.sizing_params or {}

        kelly_pct = float(params.get("kelly_pct", 10)) / 100  # 转为小数

        # 基础总资产估算
        base_fund = 100_000.0
        if sim_pos and sim_pos.shares > 0:
            base_fund = max(sim_pos.shares * entry_price, base_fund)

        if sizing_model == "KELLY_HALF":
            # 默认Kelly半仓模型
            target_value = base_fund * kelly_pct
        elif sizing_model == "FIXED_RISK":
            # 固定风险模型：1万风险金额 / (2×ATR)
            fixed_shares = sizing_params.get("fixed_risk_shares", 0)
            if fixed_shares > 0:
                return fixed_shares
            target_value = base_fund * kelly_pct
        elif sizing_model == "VOLATILITY_ADJUSTED":
            # 波动率调整：根据ATR调整仓位
            vol_factor = sizing_params.get("volatility_factor", 1.0)
            target_value = base_fund * kelly_pct * vol_factor
        else:
            target_value = base_fund * kelly_pct

        return max(int(target_value / entry_price), 1)

    def _execute_first_batch(self, sim_pos, first_shares: int, second_shares: int,
                             entry_price: float, symbol: str, name: str, category: str):
        """执行第一批建仓"""
        from datetime import date

        # 加权平均成本
        total_cost = (sim_pos.shares * (sim_pos.avg_cost or entry_price)
                      + first_shares * entry_price)
        new_total_shares = sim_pos.shares + first_shares

        sim_pos.shares = new_total_shares
        sim_pos.avg_cost = total_cost / new_total_shares
        sim_pos.last_price = entry_price
        sim_pos.market_value = new_total_shares * entry_price
        sim_pos.updated_at = datetime.now()

        # 更新分批状态
        sim_pos.batch_status = "FIRST_FILLED"
        sim_pos.first_batch_shares = first_shares
        sim_pos.first_batch_price = entry_price
        sim_pos.first_batch_date = date.today()
        sim_pos.second_batch_pending = second_shares

        logger.info(f"分批建仓第一批: {symbol} 新增{first_shares}股 @ {entry_price}, "
                   f"累计{new_total_shares}股, 待第二批: {second_shares}股")

    def _execute_second_batch(self, sim_pos, entry_price: float, symbol: str, name: str):
        """执行第二批建仓（回调3%或已过3天）"""
        from datetime import date

        second_shares = sim_pos.second_batch_pending
        if second_shares <= 0:
            return

        # 检查触发条件：回调3% 或 已过3天
        first_price = sim_pos.first_batch_price or entry_price
        first_date = sim_pos.first_batch_date
        pullback_pct = (first_price - entry_price) / first_price * 100 if first_price > 0 else 0
        days_elapsed = (date.today() - first_date).days if first_date else 0

        # 触发条件：回调>=3% 或 已过3天 或 当前价格>=第一批价格（不回调直接涨）
        should_fill = (pullback_pct >= 3) or (days_elapsed >= 3) or (entry_price >= first_price)

        if not should_fill:
            logger.debug(f"第二批建仓未触发: {symbol} 回调{pullback_pct:.1f}%, 已{days_elapsed}天")
            return

        # 执行第二批建仓
        total_cost = (sim_pos.shares * sim_pos.avg_cost) + (second_shares * entry_price)
        new_total_shares = sim_pos.shares + second_shares

        sim_pos.shares = new_total_shares
        sim_pos.avg_cost = total_cost / new_total_shares
        sim_pos.last_price = entry_price
        sim_pos.market_value = new_total_shares * entry_price
        sim_pos.updated_at = datetime.now()
        sim_pos.batch_status = "COMPLETED"
        sim_pos.second_batch_pending = 0

        logger.info(f"分批建仓第二批完成: {symbol} 新增{second_shares}股 @ {entry_price}, "
                   f"累计{new_total_shares}股, 成本{sim_pos.avg_cost:.2f}")

    def _sim_sell(self, symbol: str, log: SignalLog):
        """模拟持仓平仓（有持仓则平，没有则 log 状态改为 CANCELLED）"""
        sim_pos = self.db.query(SimPosition).filter_by(symbol=symbol).first()
        if not sim_pos or sim_pos.shares <= 0:
            log.status = "CANCELLED"
            log.note = "模拟持仓为空，SELL信号忽略"
            return

        exit_price = log.entry_price
        if not exit_price:
            log.status = "CANCELLED"
            log.note = "收盘价缺失，SELL信号取消"
            logger.warning(f"模拟SELL信号入场价缺失，已取消: {symbol}")
            return

        # 找最近一条对应的模拟 BUY 记录，用其入场价计算实际收益率
        buy_log = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.symbol == symbol,
                SignalLog.is_simulated == True,
                SignalLog.action == "BUY",
                SignalLog.entered == True,
                SignalLog.status == "PENDING",
            )
            .order_by(SignalLog.entered_at.desc())
            .first()
        )
        if buy_log and buy_log.entered_price and exit_price:
            actual_pct = round((exit_price - buy_log.entered_price) / buy_log.entered_price * 100, 2)
            log.actual_pct = actual_pct
            buy_log.status     = "HIT_TARGET"
            buy_log.exit_price = exit_price
            buy_log.exit_date  = datetime.now()
            buy_log.actual_pct = actual_pct

        log.status = "HIT_TARGET"  # 信号触发的 SELL 视为主动出场
        log.exit_price = exit_price
        log.exit_date  = datetime.now()

        sim_pos.shares = 0
        sim_pos.market_value = 0.0
        sim_pos.updated_at = datetime.now()
        self.db.flush()

    def auto_check_t1_orders(self, price_map: Dict[str, Dict]) -> dict:
        """
        T+1限价单模式：检查待执行的BUY和SELL条件单是否成交。

        BUY规则（cyclical/defensive/large_tech/biotech）：
        - 若 T+1最低价 <= limit_price：成交，成交价 = max(limit_price, 开盘价)
        - 否则：信号过期

        SELL规则（cyclical/defensive）：
        - 若 T+1最高价 >= limit_price：成交，成交价 = 触发时的价格（>=limit_price）
        - 否则：继续持有，信号过期

        SELL规则（large_tech/biotech）：
        - 若 T+1开盘价 >= limit_price：按开盘价成交
        - 若 T+1盘中最高价 >= limit_price：按limit_price成交
        - 否则：按T+1收盘价强制成交

        Args:
            price_map: {symbol: {"open": ..., "high": ..., "low": ..., "close": ...}}

        Returns:
            {"buy_executed": n, "sell_executed": n, "expired": n}
        """
        from app.models.sim_position import SimPosition

        # 获取所有待执行的PENDING信号（entered=False）
        pending = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.is_simulated == True,
                SignalLog.entered == False,
                SignalLog.status == "PENDING",
                SignalLog.action.in_(["BUY", "SELL"]),
            )
            .all()
        )

        stats = {"buy_executed": 0, "sell_executed": 0, "expired": 0}

        for log in pending:
            prices = price_map.get(log.symbol)
            if not prices or not log.limit_price:
                continue

            limit_price = float(log.limit_price)
            open_price = prices.get("open", limit_price)
            high_price = prices.get("high", limit_price)
            low_price = prices.get("low", limit_price)
            close_price = prices.get("close", limit_price)

            if log.action == "BUY":
                # BUY条件单成交判断：最低价 <= limit_price
                if low_price <= limit_price:
                    # 成交价：max(limit_price, 开盘价)
                    # 如果开盘就低于limit_price，按开盘价成交；否则按limit_price
                    executed_price = max(limit_price, open_price) if open_price <= limit_price else limit_price
                    if open_price <= limit_price:
                        executed_price = open_price  # 开盘即触发
                    else:
                        executed_price = limit_price  # 盘中触发

                    log.entered = True
                    log.entered_at = datetime.now()
                    log.entered_price = executed_price
                    log.status = "PENDING"  # 入场后仍为PENDING，等待出场条件
                    stats["buy_executed"] += 1
                    logger.info(f"T+1 BUY成交: {log.symbol} @ {executed_price}")
                else:
                    # 未触发，信号过期
                    log.status = "CANCELLED"
                    log.note = "T+1未触发条件单，信号过期"
                    stats["expired"] += 1
                    logger.info(f"T+1 BUY过期: {log.symbol}, limit={limit_price}, low={low_price}")

            elif log.action == "SELL":
                # 根据策略类型判断成交规则
                if log.category in ["cyclical", "defensive"]:
                    # cyclical/defensive：最高价 >= limit_price 则成交，否则过期
                    if high_price >= limit_price:
                        # 成交价：触发时的价格（假设为limit_price或更高）
                        executed_price = limit_price  # 简化处理，按挂价成交

                        log.entered = True
                        log.entered_at = datetime.now()
                        log.entered_price = executed_price
                        log.status = "HIT_TARGET"  # SELL成交即为主动出场
                        log.exit_price = executed_price
                        log.exit_date = datetime.now()
                        stats["sell_executed"] += 1

                        # 平仓模拟持仓
                        sim_pos = self.db.query(SimPosition).filter_by(symbol=log.symbol).first()
                        if sim_pos:
                            # 计算收益率
                            if sim_pos.avg_cost and sim_pos.avg_cost > 0:
                                actual_pct = round((executed_price - sim_pos.avg_cost) / sim_pos.avg_cost * 100, 2)
                                log.actual_pct = actual_pct
                            sim_pos.shares = 0
                            sim_pos.market_value = 0.0
                            sim_pos.updated_at = datetime.now()

                        logger.info(f"T+1 SELL成交(cyclical/defensive): {log.symbol} @ {executed_price}")
                    else:
                        # 未触发，继续持有，信号过期
                        log.status = "CANCELLED"
                        log.note = "T+1未达挂价，SELL信号过期，继续持有"
                        stats["expired"] += 1
                        logger.info(f"T+1 SELL过期: {log.symbol}, limit={limit_price}, high={high_price}")

                elif log.category in ["large_tech", "biotech"]:
                    # large_tech/biotech：确保成交
                    executed_price = None

                    if open_price >= limit_price:
                        # 开盘 >= limit_price，按开盘成交
                        executed_price = open_price
                    elif high_price >= limit_price:
                        # 盘中触发，按limit_price成交
                        executed_price = limit_price
                    else:
                        # 全天未触发，按收盘价强制成交
                        executed_price = close_price

                    log.entered = True
                    log.entered_at = datetime.now()
                    log.entered_price = executed_price
                    log.status = "HIT_TARGET"
                    log.exit_price = executed_price
                    log.exit_date = datetime.now()
                    stats["sell_executed"] += 1

                    # 平仓模拟持仓
                    sim_pos = self.db.query(SimPosition).filter_by(symbol=log.symbol).first()
                    if sim_pos:
                        if sim_pos.avg_cost and sim_pos.avg_cost > 0:
                            actual_pct = round((executed_price - sim_pos.avg_cost) / sim_pos.avg_cost * 100, 2)
                            log.actual_pct = actual_pct
                        sim_pos.shares = 0
                        sim_pos.market_value = 0.0
                        sim_pos.updated_at = datetime.now()

                    logger.info(f"T+1 SELL成交(large_tech/biotech): {log.symbol} @ {executed_price}")

        self.db.commit()
        logger.info(f"T+1条件单检查完成: BUY成交{stats['buy_executed']}, SELL成交{stats['sell_executed']}, 过期{stats['expired']}")
        return stats

    def auto_check_sim_exits(self, price_map: Dict[str, Dict]) -> int:
        """
        每日价格刷新后，检查所有持仓中的模拟信号是否触达出场条件。

        price_map: {symbol: {"high": ..., "low": ..., "close": ...}}
        优先级：止损 > 止盈 > 到期
        返回处理数量。
        """
        pending = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.is_simulated == True,
                SignalLog.entered == True,
                SignalLog.status == "PENDING",
                SignalLog.action == "BUY",
            )
            .all()
        )

        processed = 0
        for log in pending:
            prices = price_map.get(log.symbol)
            if not prices or not log.entered_price:
                continue

            high  = prices.get("high", 0)
            low   = prices.get("low", 0)

            # stop_loss_pct 约定为负数（如 -7.5），取 abs 保证止损方向正确
            stop_price   = log.entered_price * (1 - abs(log.stop_loss_pct or 7.0) / 100)
            target_price = log.entered_price * (1 + abs(log.target_pct  or 25.0) / 100)

            status = None
            if low <= stop_price:
                status = "HIT_STOP"
                exit_price = stop_price
            elif high >= target_price:
                status = "HIT_TARGET"
                exit_price = target_price
            elif log.hold_months and log.entered_at:
                expire_date = log.entered_at + relativedelta(months=log.hold_months)
                if datetime.now() >= expire_date:
                    status = "EXPIRED"
                    exit_price = prices.get("close", log.entered_price)

            if status:
                log.status     = status
                log.exit_price = exit_price
                log.exit_date  = datetime.now()
                log.actual_pct = round((exit_price - log.entered_price) / log.entered_price * 100, 2)
                processed += 1

        self.db.commit()
        logger.info(f"模拟出场检查: {processed} 条信号出场")
        return processed

    def auto_expire_stale(self) -> int:
        """
        自动将超过3个交易日仍未入场的 PENDING 信号标记为 CANCELLED。
        （信号时效性设计：3日内未入场即失效）
        返回处理数量。
        """
        cutoff = datetime.now() - timedelta(days=4)  # 3交易日（含周末约4自然日）
        stale = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.status == "PENDING",
                SignalLog.entered == False,
                SignalLog.generated_at < cutoff,
            )
            .all()
        )
        for log in stale:
            log.status = "CANCELLED"
            log.note = "超过3个交易日未入场，信号自动失效"
        self.db.commit()
        logger.info(f"自动失效信号: {len(stale)} 条")
        return len(stale)

    # ─────────────────────────────────────────────────────
    # 查询
    # ─────────────────────────────────────────────────────

    def get_pending(self) -> "list[SignalLog]":
        """获取所有待跟踪信号（已入场但未出场）"""
        return (
            self.db.query(SignalLog)
            .filter(SignalLog.status == "PENDING", SignalLog.entered == True)
            .order_by(SignalLog.generated_at.desc())
            .all()
        )

    def get_history(self, symbol: str = None, limit: int = 50) -> list[SignalLog]:
        """获取历史信号记录"""
        q = self.db.query(SignalLog).filter(
            SignalLog.status != "PENDING"
        )
        if symbol:
            q = q.filter(SignalLog.symbol == symbol)
        return q.order_by(SignalLog.generated_at.desc()).limit(limit).all()

    def get_all_actionable(self) -> list[SignalLog]:
        """获取所有待处理信号（PENDING，包含未入场的新信号）"""
        return (
            self.db.query(SignalLog)
            .filter(SignalLog.status == "PENDING")
            .order_by(SignalLog.generated_at.desc())
            .all()
        )

    # ─────────────────────────────────────────────────────
    # 绩效统计
    # ─────────────────────────────────────────────────────

    def get_performance(self, symbol: str = None, is_simulated: bool = None) -> dict:
        """
        统计已完结信号的绩效。
        is_simulated=None 表示统计全部；True=只统计模拟；False=只统计真实。
        只统计已入场且有结果的记录（HIT_TARGET / HIT_STOP / EXPIRED）。
        """
        q = self.db.query(SignalLog).filter(
            SignalLog.entered == True,
            SignalLog.actual_pct.isnot(None),
            SignalLog.status.in_(["HIT_TARGET", "HIT_STOP", "EXPIRED"]),
        )
        if symbol:
            q = q.filter(SignalLog.symbol == symbol)
        if is_simulated is not None:
            q = q.filter(SignalLog.is_simulated == is_simulated)

        logs = q.all()
        if not logs:
            label = "模拟" if is_simulated is True else ("实盘" if is_simulated is False else "全部")
            return {"message": f"暂无已完结的{label}信号记录"}

        returns = [log.actual_pct for log in logs]
        wins    = [r for r in returns if r > 0]
        losses  = [r for r in returns if r <= 0]

        win_rate    = len(wins) / len(returns)
        avg_win     = sum(wins) / len(wins) if wins else 0
        avg_loss    = sum(losses) / len(losses) if losses else 0
        ev          = win_rate * avg_win + (1 - win_rate) * avg_loss
        profit_factor = avg_win / abs(avg_loss) if avg_loss != 0 and wins else 0

        # 最大连续亏损
        max_consec = cur = 0
        for r in returns:
            cur = cur + 1 if r <= 0 else 0
            max_consec = max(max_consec, cur)

        # 按股票分组
        by_symbol = {}
        for log in logs:
            s = log.symbol
            by_symbol.setdefault(s, []).append(log.actual_pct)

        symbol_stats = {}
        for s, rets in by_symbol.items():
            w = [r for r in rets if r > 0]
            symbol_stats[s] = {
                "trades": len(rets),
                "win_rate": round(len(w) / len(rets) * 100, 0),
                "ev_pct": round(sum(rets) / len(rets), 1),
            }

        return {
            "total_trades":        len(returns),
            "win_rate":            round(win_rate * 100, 1),
            "avg_win_pct":         round(avg_win, 2),
            "avg_loss_pct":        round(avg_loss, 2),
            "ev_pct":              round(ev, 2),
            "profit_factor":       round(profit_factor, 2),
            "max_consecutive_loss": max_consec,
            "by_symbol":           symbol_stats,
        }
