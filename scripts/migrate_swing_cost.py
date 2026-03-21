"""
一次性迁移：给 positions 表添加 swing_cost 字段
运行方式：cd lightsaber && python scripts/migrate_swing_cost.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine


def migrate():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE positions ADD COLUMN swing_cost NUMERIC(15,4)"))
            conn.commit()
            print("✅ swing_cost 字段添加成功")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("ℹ️  swing_cost 字段已存在，跳过")
            else:
                print(f"❌ 迁移失败: {e}")
                raise


if __name__ == "__main__":
    migrate()
