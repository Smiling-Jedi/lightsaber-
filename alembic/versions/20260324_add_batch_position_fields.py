"""
B+D方案数据库迁移脚本
添加SimPosition分批建仓字段

运行方式：
    cd /Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber
    PYTHONPATH=/Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber python3 alembic/versions/20260324_add_batch_position_fields.py
"""

import sqlite3
import os

def upgrade():
    """添加分批建仓字段"""
    # 查找数据库文件
    db_paths = [
        "/Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber/lightsaber.db",
        "/Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber/data/lightsaber.db",
        "./lightsaber.db",
        "./data/lightsaber.db",
    ]

    db_path = None
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break

    if not db_path:
        print("错误：未找到数据库文件")
        return

    print(f"使用数据库: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查当前字段
    cursor.execute("PRAGMA table_info(sim_positions)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"当前字段: {columns}")

    # 添加新字段
    new_fields = [
        ("batch_status", "VARCHAR(20) DEFAULT 'IDLE' NOT NULL"),
        ("first_batch_shares", "INTEGER DEFAULT 0 NOT NULL"),
        ("first_batch_price", "FLOAT"),
        ("first_batch_date", "DATE"),
        ("second_batch_pending", "INTEGER DEFAULT 0 NOT NULL"),
    ]

    for field_name, field_type in new_fields:
        if field_name not in columns:
            try:
                cursor.execute(f"ALTER TABLE sim_positions ADD COLUMN {field_name} {field_type}")
                print(f"✓ 添加字段: {field_name}")
            except Exception as e:
                print(f"✗ 添加字段 {field_name} 失败: {e}")
        else:
            print(f"⊘ 字段已存在: {field_name}")

    conn.commit()
    conn.close()
    print("\n迁移完成！")

if __name__ == "__main__":
    upgrade()
