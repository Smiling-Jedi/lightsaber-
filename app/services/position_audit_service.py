"""
持仓审计服务
记录持仓数据的变更历史，用于追溯和问题排查
"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from decimal import Decimal

from app.models.position import Position
from app.models.position_audit_log import PositionAuditLog

logger = logging.getLogger(__name__)


class PositionAuditService:
    """持仓审计服务"""

    def __init__(self, db: Session):
        self.db = db

    def log_change(
        self,
        position: Position,
        field_name: str,
        old_value,
        new_value,
        change_reason: str = "MANUAL",
        source: str = "USER"
    ) -> PositionAuditLog:
        """
        记录持仓变更

        Args:
            position: 持仓对象
            field_name: 变更字段名
            old_value: 原值
            new_value: 新值
            change_reason: 变更原因 (SYNC/MANUAL/TRADE)
            source: 数据来源 (FUTU/USER/SCRIPT/API)

        Returns:
            PositionAuditLog 对象
        """
        # 值转换为字符串
        old_str = str(old_value) if old_value is not None else None
        new_str = str(new_value) if new_value is not None else None

        # 如果值没有变化，不记录
        if old_str == new_str:
            return None

        audit_log = PositionAuditLog(
            position_id=position.id,
            stock_symbol=position.stock_symbol,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            change_reason=change_reason,
            source=source,
            created_at=datetime.now()
        )

        self.db.add(audit_log)
        self.db.flush()

        logger.debug(f"持仓变更记录: {position.stock_symbol} {field_name} {old_str} -> {new_str}")

        return audit_log

    def log_position_sync(
        self,
        position: Position,
        old_shares: int,
        old_cost: Decimal,
        source: str = "FUTU"
    ) -> None:
        """
        记录持仓同步变更

        Args:
            position: 持仓对象
            old_shares: 原股数
            old_cost: 原成本
            source: 数据来源
        """
        if position.total_shares != old_shares:
            self.log_change(
                position, "total_shares", old_shares, position.total_shares,
                change_reason="SYNC", source=source
            )

        if position.avg_cost != old_cost:
            self.log_change(
                position, "avg_cost", old_cost, position.avg_cost,
                change_reason="SYNC", source=source
            )

    def get_audit_history(
        self,
        stock_symbol: Optional[str] = None,
        field_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ):
        """
        查询审计历史

        Args:
            stock_symbol: 股票代码筛选
            field_name: 字段名筛选
            start_date: 开始时间
            end_date: 结束时间
            limit: 返回数量限制

        Returns:
            审计日志列表
        """
        query = self.db.query(PositionAuditLog)

        if stock_symbol:
            query = query.filter(PositionAuditLog.stock_symbol == stock_symbol)

        if field_name:
            query = query.filter(PositionAuditLog.field_name == field_name)

        if start_date:
            query = query.filter(PositionAuditLog.created_at >= start_date)

        if end_date:
            query = query.filter(PositionAuditLog.created_at <= end_date)

        return query.order_by(PositionAuditLog.created_at.desc()).limit(limit).all()

    def validate_a_shares_consistency(self) -> dict:
        """
        验证A股持仓一致性
        检查A股持仓是否从非0变为0（可能的异常）

        Returns:
            验证结果 {"is_valid": bool, "warnings": list}
        """
        warnings = []

        # 获取当前A股持仓
        a_positions = self.db.query(Position).filter(
            Position.stock_symbol.like("A:%"),
            Position.total_shares > 0
        ).all()

        # 检查是否有审计日志显示A股曾经持有但现在为0
        # 获取最近7天的A股total_shares变更记录
        from datetime import timedelta
        seven_days_ago = datetime.now() - timedelta(days=7)

        recent_a_changes = self.db.query(PositionAuditLog).filter(
            PositionAuditLog.stock_symbol.like("A:%"),
            PositionAuditLog.field_name == "total_shares",
            PositionAuditLog.created_at >= seven_days_ago
        ).order_by(PositionAuditLog.created_at.desc()).all()

        # 检查是否有异常清空
        for change in recent_a_changes:
            if change.old_value and int(change.old_value) > 0 and (
                not change.new_value or int(change.new_value) == 0
            ):
                warnings.append({
                    "symbol": change.stock_symbol,
                    "old_shares": change.old_value,
                    "new_shares": change.new_value,
                    "changed_at": change.created_at.isoformat(),
                    "source": change.source,
                    "message": f"⚠️ A股 {change.stock_symbol} 持仓从 {change.old_value} 变为 {change.new_value}，请确认是否已清仓或数据异常"
                })

        return {
            "is_valid": len(warnings) == 0,
            "current_a_positions": len(a_positions),
            "warnings": warnings
        }
