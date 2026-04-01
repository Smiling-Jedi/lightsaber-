"""
资金流水日志模型 - 每一笔资金变动都有迹可循
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Integer, String, Numeric, DateTime, Date, ForeignKey, Index
from sqlalchemy.orm import validates

from app.core.database import Base


class CashFlowLog(Base):
    """
    资金流水日志

    记录每一笔资金的来龙去脉，支持：
    - 对账：总资产 = sum(流水)
    - 审计：追踪异常资金变动
    - 归因：分析盈亏来源
    """

    __tablename__ = "cash_flow_logs"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 账户类型
    account_type = Column(String(20), nullable=False, index=True,
                         comment="REAL=真实账户, SIMULATED=模拟账户")

    # 流水类型
    flow_type = Column(String(30), nullable=False, index=True,
                      comment="DEPOSIT=入金, WITHDRAW=出金, TRADE_BUY=买入, TRADE_SELL=卖出, DIVIDEND=分红, TRANSFER=转账, FUND_INTEREST=基金收益, ADJUSTMENT=调整")

    # 市场
    market = Column(String(10), nullable=False, index=True,
                   comment="HK/US/A/SIM_HKD/SIM_USD/SIM_CNY")

    # 币种
    currency = Column(String(10), nullable=False, comment="HKD/USD/CNY")

    # 金额（正数流入，负数流出）
    amount = Column(Numeric(20, 4), nullable=False, comment="正数流入，负数流出")

    # 余额（记录当时余额，便于对账）
    balance_after = Column(Numeric(20, 4), nullable=True, comment="变动后余额")

    # 关联的交易记录（如果是交易产生的）
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True, index=True)

    # 关联的信号（如果是模拟交易产生的）
    signal_log_id = Column(Integer, ForeignKey("signal_logs.id"), nullable=True, index=True)

    # 关联的持仓（便于追踪某只股票的现金流）
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True, index=True)

    # 交易日期（业务日期）
    trade_date = Column(Date, nullable=False, default=date.today, index=True)

    # 描述
    description = Column(String(500), nullable=True)

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # 索引优化查询
    __table_args__ = (
        Index('ix_cashflow_account_date', 'account_type', 'trade_date'),
        Index('ix_cashflow_market_currency', 'market', 'currency'),
    )

    @validates('account_type')
    def validate_account_type(self, key, value):
        if value not in ('REAL', 'SIMULATED'):
            raise ValueError(f"account_type must be REAL or SIMULATED, got {value}")
        return value

    @validates('flow_type')
    def validate_flow_type(self, key, value):
        valid_types = (
            'DEPOSIT', 'WITHDRAW', 'TRADE_BUY', 'TRADE_SELL',
            'DIVIDEND', 'TRANSFER', 'FUND_INTEREST', 'ADJUSTMENT'
        )
        if value not in valid_types:
            raise ValueError(f"flow_type must be one of {valid_types}, got {value}")
        return value

    @property
    def is_inflow(self) -> bool:
        """是否为流入"""
        return self.amount > 0 if self.amount else False

    @property
    def is_outflow(self) -> bool:
        """是否为流出"""
        return self.amount < 0 if self.amount else False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_type": self.account_type,
            "flow_type": self.flow_type,
            "market": self.market,
            "currency": self.currency,
            "amount": float(self.amount),
            "balance_after": float(self.balance_after) if self.balance_after else None,
            "trade_id": self.trade_id,
            "signal_log_id": self.signal_log_id,
            "position_id": self.position_id,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
