"""
组合快照模型 - 每日总资产记录
真实账户和模拟账户完全隔离
"""
from datetime import datetime, date
from typing import Optional, Dict, Any
import json

from sqlalchemy import Column, Integer, String, Numeric, DateTime, Date, UniqueConstraint, Index
from sqlalchemy.orm import validates

from app.core.database import Base


class PortfolioSnapshot(Base):
    """
    组合资产快照

    每日记录一次（或交易后即时记录），用于：
    - 生成资产净值曲线
    - 计算最大回撤、夏普比率等
    - 真实/模拟账户表现对比
    """

    __tablename__ = "portfolio_snapshots"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 快照日期（支持每天多次快照，以latest为准）
    snapshot_date = Column(Date, nullable=False, index=True)

    # 账户类型：真实 vs 模拟
    account_type = Column(String(20), nullable=False, index=True,
                         comment="REAL=真实账户, SIMULATED=模拟账户")

    # 各市场总资产（原始货币）
    total_assets_hkd = Column(Numeric(20, 4), default=0, comment="港元资产")
    total_assets_usd = Column(Numeric(20, 4), default=0, comment="美元资产")
    total_assets_cny = Column(Numeric(20, 4), default=0, comment="人民币资产")

    # 折算为人民币的总资产（统一口径）
    total_assets_rmb = Column(Numeric(20, 4), default=0, comment="折算人民币总资产")

    # 成分明细（JSON存储，灵活扩展）
    # 结构：{
    #   "stocks": {"HK:00700": {"shares": 100, "price": 400, "value": 40000}, ...},
    #   "cash": {"HKD": 100000, "USD": 5000, "CNY": 200000},
    #   "funds": {"HKD": 50000, "USD": 0}
    # }
    breakdown_json = Column(String, nullable=True, comment="资产明细JSON")

    # 备注（如"收盘快照"、"交易后快照"等）
    note = Column(String(200), nullable=True)

    # 创建时间
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # 约束：同一天同一账户类型只能有一个正式快照
    # 但允许多次快照，查询时取最新
    __table_args__ = (
        Index('ix_snapshot_date_type', 'snapshot_date', 'account_type'),
    )

    @validates('account_type')
    def validate_account_type(self, key, value):
        if value not in ('REAL', 'SIMULATED'):
            raise ValueError(f"account_type must be REAL or SIMULATED, got {value}")
        return value

    def get_breakdown(self) -> Optional[Dict[str, Any]]:
        """解析breakdown_json为字典"""
        if self.breakdown_json:
            try:
                return json.loads(self.breakdown_json)
            except json.JSONDecodeError:
                return None
        return None

    def set_breakdown(self, data: Dict[str, Any]) -> None:
        """将字典序列化为JSON存储"""
        self.breakdown_json = json.dumps(data, ensure_ascii=False, default=str)

    @property
    def total_by_market(self) -> Dict[str, float]:
        """获取各市场总资产"""
        return {
            "HKD": float(self.total_assets_hkd),
            "USD": float(self.total_assets_usd),
            "CNY": float(self.total_assets_cny),
            "RMB": float(self.total_assets_rmb)
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "snapshot_date": self.snapshot_date.isoformat() if self.snapshot_date else None,
            "account_type": self.account_type,
            "total_assets_hkd": float(self.total_assets_hkd),
            "total_assets_usd": float(self.total_assets_usd),
            "total_assets_cny": float(self.total_assets_cny),
            "total_assets_rmb": float(self.total_assets_rmb),
            "breakdown": self.get_breakdown(),
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
