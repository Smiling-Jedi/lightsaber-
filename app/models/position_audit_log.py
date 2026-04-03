"""
持仓变更审计日志模型
记录所有持仓数据的变更历史，用于追溯和问题排查
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from app.core.database import Base


class PositionAuditLog(Base):
    """持仓变更审计日志"""

    __tablename__ = 'position_audit_logs'
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联持仓
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False, index=True)

    # 股票代码（冗余存储，方便查询）
    stock_symbol = Column(String(20), nullable=False, index=True)

    # 变更字段名
    field_name = Column(String(50), nullable=False, comment='变更字段: total_shares/avg_cost/base_shares等')

    # 变更前后的值（存为字符串，支持各种类型）
    old_value = Column(String(500), nullable=True, comment='原值')
    new_value = Column(String(500), nullable=True, comment='新值')

    # 变更原因
    change_reason = Column(String(50), nullable=False, comment='SYNC-同步/MANUAL-手动录入/TRADE-交易录入')

    # 数据来源
    source = Column(String(50), nullable=False, comment='FUTU-富途同步/USER-用户操作/SCRIPT-脚本操作/API-API调用')

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    def __repr__(self):
        return f"<PositionAuditLog(id={self.id}, symbol={self.stock_symbol}, field={self.field_name})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "position_id": self.position_id,
            "stock_symbol": self.stock_symbol,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "change_reason": self.change_reason,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
