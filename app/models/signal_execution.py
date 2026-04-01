"""
信号执行记录模型 - 连接信号与实际交易的桥梁
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
import json

from sqlalchemy import Column, Integer, String, Numeric, DateTime, Date, ForeignKey, Index
from sqlalchemy.orm import validates

from app.core.database import Base


class SignalExecution(Base):
    """
    信号执行记录

    追踪信号从生成到执行的完整链路：
    - 信号生成时间 vs 执行时间（延迟）
    - 信号建议价 vs 实际成交价（滑点）
    - 计划股数 vs 实际成交股数（执行率）

    这是"原力"系统有效性评估的核心数据
    """

    __tablename__ = "signal_executions"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联的信号
    signal_log_id = Column(Integer, ForeignKey("signal_logs.id"), nullable=False, index=True)

    # 股票代码（冗余，便于查询）
    symbol = Column(String(20), nullable=False, index=True)

    # 信号建议
    recommended_action = Column(String(10), nullable=False)  # BUY/SELL
    recommended_shares = Column(Integer, nullable=True)      # 建议股数
    recommended_price = Column(Numeric(15, 4), nullable=True)  # 信号触发时的价格

    # 执行结果
    executed_at = Column(DateTime, nullable=True)  # 实际执行时间
    executed_shares = Column(Integer, nullable=True)  # 实际执行股数
    executed_price = Column(Numeric(15, 4), nullable=True)  # 实际执行均价

    # 关联的交易记录ID列表（JSON数组，支持分批执行）
    # 例如："[123, 124, 125]"
    trade_ids_json = Column(String(500), nullable=True)

    # 执行质量分析
    # 滑点 = (实际价 - 信号价) / 信号价 * 100
    # BUY时滑点>0表示买贵了，SELL时滑点<0表示卖便宜了
    slippage_pct = Column(Numeric(5, 2), nullable=True, comment="滑点百分比")

    # 延迟（分钟）
    delay_minutes = Column(Integer, nullable=True, comment="信号到执行的延迟")

    # 执行率 = 实际股数 / 建议股数 * 100
    fill_rate_pct = Column(Numeric(5, 2), nullable=True, comment="执行率")

    # 状态
    status = Column(String(20), nullable=False, default="PENDING",
                   comment="PENDING=待执行, EXECUTED=已执行, PARTIAL=部分执行, CANCELLED=已取消, EXPIRED=已过期")

    # 原因（如果取消或失败）
    cancel_reason = Column(String(200), nullable=True)

    # 业务日期
    trade_date = Column(Date, nullable=False, default=date.today, index=True)

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # 更新时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 索引
    __table_args__ = (
        Index('ix_execution_symbol_date', 'symbol', 'trade_date'),
        Index('ix_execution_status', 'status', 'created_at'),
    )

    @validates('status')
    def validate_status(self, key, value):
        valid_statuses = ('PENDING', 'EXECUTED', 'PARTIAL', 'CANCELLED', 'EXPIRED')
        if value not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}, got {value}")
        return value

    def set_trade_ids(self, trade_ids: List[int]) -> None:
        """设置关联的交易ID列表"""
        self.trade_ids_json = json.dumps(trade_ids)

    def get_trade_ids(self) -> List[int]:
        """获取关联的交易ID列表"""
        if self.trade_ids_json:
            try:
                return json.loads(self.trade_ids_json)
            except json.JSONDecodeError:
                return []
        return []

    def calculate_slippage(self) -> Optional[Decimal]:
        """
        计算滑点百分比

        BUY:  (实际价 - 信号价) / 信号价 * 100
        SELL: (信号价 - 实际价) / 信号价 * 100  (反向，SELL时希望卖得高)

        Returns: 滑点百分比（正数表示不利滑点）
        """
        if not self.recommended_price or not self.executed_price:
            return None

        rec_price = Decimal(str(self.recommended_price))
        exe_price = Decimal(str(self.executed_price))

        if rec_price == 0:
            return None

        if self.recommended_action == "BUY":
            # BUY时，买贵了是正滑点（不利）
            slippage = (exe_price - rec_price) / rec_price * 100
        else:  # SELL
            # SELL时，卖便宜了是正滑点（不利）
            slippage = (rec_price - exe_price) / rec_price * 100

        return round(slippage, 2)

    def calculate_fill_rate(self) -> Optional[Decimal]:
        """计算执行率"""
        if not self.recommended_shares or self.recommended_shares == 0:
            return None
        if not self.executed_shares:
            return Decimal("0")

        rate = Decimal(str(self.executed_shares)) / Decimal(str(self.recommended_shares)) * 100
        return round(rate, 2)

    def record_execution(self, trade_ids: List[int], executed_shares: int,
                        executed_price: Decimal, executed_at: datetime = None) -> None:
        """
        记录执行结果

        Args:
            trade_ids: 产生的交易ID列表
            executed_shares: 实际执行股数
            executed_price: 实际执行均价
            executed_at: 执行时间（默认当前）
        """
        self.set_trade_ids(trade_ids)
        self.executed_shares = executed_shares
        self.executed_price = executed_price
        self.executed_at = executed_at or datetime.now()

        # 自动计算执行率和滑点
        self.fill_rate_pct = self.calculate_fill_rate()
        self.slippage_pct = self.calculate_slippage()

        # 计算延迟
        if self.created_at:
            delay = (self.executed_at - self.created_at).total_seconds() / 60
            self.delay_minutes = int(delay)

        # 更新状态
        if self.fill_rate_pct and self.fill_rate_pct >= 100:
            self.status = "EXECUTED"
        elif self.fill_rate_pct and self.fill_rate_pct > 0:
            self.status = "PARTIAL"
        else:
            self.status = "CANCELLED"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "signal_log_id": self.signal_log_id,
            "symbol": self.symbol,
            "recommended_action": self.recommended_action,
            "recommended_shares": self.recommended_shares,
            "recommended_price": float(self.recommended_price) if self.recommended_price else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "executed_shares": self.executed_shares,
            "executed_price": float(self.executed_price) if self.executed_price else None,
            "trade_ids": self.get_trade_ids(),
            "slippage_pct": float(self.slippage_pct) if self.slippage_pct else None,
            "delay_minutes": self.delay_minutes,
            "fill_rate_pct": float(self.fill_rate_pct) if self.fill_rate_pct else None,
            "status": self.status,
            "cancel_reason": self.cancel_reason,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
