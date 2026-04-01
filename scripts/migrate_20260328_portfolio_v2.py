"""
数据库迁移脚本 - 2026-03-28
创建组合管理V2所需的表

运行方式:
    cd /Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber
    python scripts/migrate_20260328_portfolio_v2.py
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.core.database import DATABASE_URL, Base
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.cash_flow_log import CashFlowLog
from app.models.signal_execution import SignalExecution


def migrate():
    """执行迁移"""
    print("=" * 60)
    print("数据库迁移: 组合管理V2")
    print("=" * 60)

    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    )

    # 检查表是否存在
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        existing_tables = {row[0] for row in result}

    print(f"\n现有表: {existing_tables}")

    # 要创建的表
    new_tables = [
        ("portfolio_snapshots", PortfolioSnapshot),
        ("cash_flow_logs", CashFlowLog),
        ("signal_executions", SignalExecution),
    ]

    created = []
    skipped = []

    for table_name, model_class in new_tables:
        if table_name in existing_tables:
            print(f"\n⚠️ 表 {table_name} 已存在，跳过")
            skipped.append(table_name)
        else:
            print(f"\n✅ 创建表 {table_name}...")
            model_class.__table__.create(engine)
            created.append(table_name)

    # 验证
    print("\n" + "=" * 60)
    print("迁移结果")
    print("=" * 60)

    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        all_tables = {row[0] for row in result}

    for table_name, _ in new_tables:
        status = "✅ 已创建" if table_name in all_tables else "❌ 失败"
        print(f"  {table_name}: {status}")

    print(f"\n总计: 创建 {len(created)} 个表, 跳过 {len(skipped)} 个表")

    # 创建索引优化提示
    print("\n" + "=" * 60)
    print("索引信息")
    print("=" * 60)

    with engine.connect() as conn:
        for table_name, _ in new_tables:
            if table_name in all_tables:
                result = conn.execute(text(f"PRAGMA index_list({table_name})"))
                indexes = [row[1] for row in result]
                print(f"\n{table_name} 索引:")
                for idx in indexes:
                    print(f"  - {idx}")

    print("\n" + "=" * 60)
    print("迁移完成")
    print("=" * 60)


def verify_migration():
    """验证迁移结果"""
    print("\n验证迁移...")

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        # 测试创建记录
        from datetime import date
        from decimal import Decimal
        from app.models.signal_log import SignalLog

        # 先创建一条 signal_log 记录用于外键关联
        signal_log = SignalLog(
            symbol="HK:00700",
            action="BUY",
        )
        db.add(signal_log)
        db.flush()  # 获取 ID

        # 测试 PortfolioSnapshot
        snapshot = PortfolioSnapshot(
            snapshot_date=date.today(),
            account_type="REAL",
            total_assets_hkd=Decimal("100000"),
            total_assets_rmb=Decimal("92000"),
        )
        snapshot.set_breakdown({
            "stocks": {"HK:00700": {"shares": 100, "value": 40000}},
            "cash": {"HKD": 60000}
        })
        db.add(snapshot)

        # 测试 CashFlowLog
        flow = CashFlowLog(
            account_type="SIMULATED",
            flow_type="TRADE_BUY",
            market="SIM_HKD",
            currency="HKD",
            amount=Decimal("-50000"),
            description="测试流水",
        )
        db.add(flow)

        # 测试 SignalExecution
        execution = SignalExecution(
            signal_log_id=signal_log.id,
            symbol="HK:00700",
            recommended_action="BUY",
            recommended_shares=1000,
            recommended_price=Decimal("400.00"),
            status="PENDING",
        )
        db.add(execution)

        db.commit()

        print("✅ 测试记录创建成功")

        # 清理测试数据
        db.delete(execution)
        db.delete(flow)
        db.delete(snapshot)
        db.delete(signal_log)
        db.commit()

        print("✅ 测试数据已清理")
        print("✅ 验证通过！")

    except Exception as e:
        print(f"❌ 验证失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
    verify_migration()
