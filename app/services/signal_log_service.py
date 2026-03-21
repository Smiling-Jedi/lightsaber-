"""
信号日志服务

负责：
  - 保存信号记录（BUY/SELL 才保存，WATCH/HOLD 不记录）
  - 标记入场（用户确认后调用）
  - 更新结果（止损/达标/持有期满）
  - 统计绩效（胜率/EV/盈亏比）
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.signal_log import SignalLog
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

        # 幂等检查：今天同一只股票同一action已有记录
        today = datetime.now().date()
        exists = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.symbol == result.symbol,
                SignalLog.action == result.action,
                SignalLog.generated_at >= datetime(today.year, today.month, today.day),
            )
            .first()
        )
        if exists:
            logger.info(f"信号已存在，跳过保存: {result.symbol} {result.action}")
            return exists

        params = result.backtest_ref or {}
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

    def get_performance(self, symbol: str = None) -> dict:
        """
        统计已完结信号的实盘绩效。
        只统计已入场且有结果的记录（HIT_TARGET / HIT_STOP / EXPIRED）。
        """
        q = self.db.query(SignalLog).filter(
            SignalLog.entered == True,
            SignalLog.actual_pct.isnot(None),
            SignalLog.status.in_(["HIT_TARGET", "HIT_STOP", "EXPIRED"]),
        )
        if symbol:
            q = q.filter(SignalLog.symbol == symbol)

        logs = q.all()
        if not logs:
            return {"message": "暂无已完结的实盘信号记录"}

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
