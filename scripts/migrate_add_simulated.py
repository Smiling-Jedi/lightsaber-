"""
数据库迁移：加入模拟交易相关字段和表

变更内容：
1. signal_logs 表加 is_simulated 字段
2. trades 表加 futu_order_id 字段
3. 创建 sim_positions 表（模拟持仓）

运行方式：
    cd lightsaber
    python scripts/migrate_add_simulated.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, Base

# 导入所有模型，确保 metadata 中包含新表
from app.models import Stock, Position, Trade, News, CashBalance, SimPosition  # noqa
from app.models.signal_log import SignalLog  # noqa


def run():
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    with engine.connect() as conn:
        # ── 1. signal_logs.is_simulated ──────────────────────
        if "signal_logs" in existing_tables:
            cols = [c["name"] for c in inspector.get_columns("signal_logs")]
            if "is_simulated" not in cols:
                conn.execute(text(
                    "ALTER TABLE signal_logs ADD COLUMN is_simulated BOOLEAN NOT NULL DEFAULT 0"
                ))
                print("✓ signal_logs.is_simulated 已添加")
            else:
                print("- signal_logs.is_simulated 已存在，跳过")

        # ── 2. trades.futu_order_id ───────────────────────────
        if "trades" in existing_tables:
            cols = [c["name"] for c in inspector.get_columns("trades")]
            if "futu_order_id" not in cols:
                conn.execute(text(
                    "ALTER TABLE trades ADD COLUMN futu_order_id VARCHAR(50)"
                ))
                print("✓ trades.futu_order_id 已添加")
            else:
                print("- trades.futu_order_id 已存在，跳过")

        conn.commit()

    # ── 3. 创建 sim_positions 表（通过 SQLAlchemy metadata）──
    if "sim_positions" not in existing_tables:
        Base.metadata.tables["sim_positions"].create(bind=engine)
        print("✓ sim_positions 表已创建")
    else:
        print("- sim_positions 表已存在，跳过")

    print("\n迁移完成。")


if __name__ == "__main__":
    run()
