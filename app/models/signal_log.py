"""
信号日志模型

记录每次生成的 BUY/SELL 信号及后续结果跟踪。
状态流转：PENDING → HIT_TARGET / HIT_STOP / EXPIRED / CANCELLED
"""
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text

from app.core.database import Base


class SignalLog(Base):
    __tablename__ = "signal_logs"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票信息
    symbol = Column(String(20), nullable=False, index=True)
    name   = Column(String(100), nullable=True)
    category = Column(String(20), nullable=True)   # large_tech / cyclical / defensive / biotech

    # 信号内容
    generated_at  = Column(DateTime, nullable=False, default=datetime.now)
    action        = Column(String(10), nullable=False)   # BUY / SELL / WATCH / HOLD
    confidence    = Column(String(10), nullable=True)    # HIGH / MEDIUM / LOW
    entry_price   = Column(Float, nullable=True)         # 信号触发时的收盘价
    stop_loss_pct = Column(Float, nullable=True)         # 止损%（负数，如-7.0）
    target_pct    = Column(Float, nullable=True)         # 第一阶段目标%（如25.0）
    hold_months   = Column(Integer, nullable=True)       # 持有上限（月）
    market_env    = Column(String(10), nullable=True)    # BULL / BEAR / NEUTRAL
    wf_robust     = Column(Boolean, nullable=True)       # 回测WF是否稳健

    # 触发原因（JSON列表）
    triggers_json  = Column(Text, nullable=True)
    conflicts_json = Column(Text, nullable=True)

    # 是否为模拟交易（True=系统自动模拟，False=真实信号跟踪）
    is_simulated = Column(Boolean, default=False, nullable=False, index=True)

    # 是否已入场（用户确认）
    entered = Column(Boolean, default=False, nullable=False)
    entered_at    = Column(DateTime, nullable=True)
    entered_price = Column(Float, nullable=True)

    # 结果跟踪
    # PENDING=待跟踪, HIT_TARGET=达到目标, HIT_STOP=止损出场,
    # EXPIRED=持有期满, CANCELLED=信号失效(3日未入场), SKIPPED=人工跳过
    status     = Column(String(20), default="PENDING", nullable=False, index=True)
    exit_price = Column(Float, nullable=True)
    exit_date  = Column(DateTime, nullable=True)
    actual_pct = Column(Float, nullable=True)   # 实际收益率%（出场价/入场价）
    note       = Column(Text, nullable=True)    # 人工备注

    # 交易建议（来自 TradeInstruction）
    recommended_shares       = Column(Integer, nullable=True)  # 第一批建议股数
    recommended_shares_second = Column(Integer, nullable=True) # 第二批建议股数
    entry_price_reference    = Column(Float, nullable=True)    # 参考入场价
    position_value_estimated = Column(Float, nullable=True)    # 预计占用资金

    # T+1限价单模式新增字段
    limit_price     = Column(Float, nullable=True, comment="条件单挂价（T+1限价单价格）")
    t1_low_price    = Column(Float, nullable=True, comment="T+1日最低价（用于成交判断）")
    t1_open_price   = Column(Float, nullable=True, comment="T+1日开盘价（用于统计滑点）")

    # ─────────────────────────────────────────────────────
    # 便捷方法
    # ─────────────────────────────────────────────────────

    @property
    def triggers(self) -> list:
        return json.loads(self.triggers_json) if self.triggers_json else []

    @property
    def conflicts(self) -> list:
        return json.loads(self.conflicts_json) if self.conflicts_json else []

    def compute_actual_pct(self) -> Optional[float]:
        """根据入场价和出场价计算实际收益率"""
        if self.entered_price and self.exit_price:
            return round((self.exit_price - self.entered_price) / self.entered_price * 100, 2)
        return None

    def is_win(self) -> Optional[bool]:
        pct = self.compute_actual_pct()
        if pct is None:
            return None
        return pct > 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "category": self.category,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "action": self.action,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "stop_loss_pct": self.stop_loss_pct,
            "target_pct": self.target_pct,
            "hold_months": self.hold_months,
            "market_env": self.market_env,
            "wf_robust": self.wf_robust,
            "triggers": self.triggers,
            "conflicts": self.conflicts,
            "is_simulated": self.is_simulated,
            "entered": self.entered,
            "entered_price": self.entered_price,
            "status": self.status,
            "exit_price": self.exit_price,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "actual_pct": self.actual_pct,
            "note": self.note,
            # 交易建议
            "recommended_shares": self.recommended_shares,
            "recommended_shares_second": self.recommended_shares_second,
            "entry_price_reference": self.entry_price_reference,
            "position_value_estimated": self.position_value_estimated,
            # T+1限价单模式新增字段
            "limit_price": self.limit_price,
            "t1_low_price": self.t1_low_price,
            "t1_open_price": self.t1_open_price,
        }
