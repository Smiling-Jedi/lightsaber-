#!/usr/bin/env python3
"""
初始化数据库脚本
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import init_db


def main():
    print("正在初始化数据库...")
    init_db()
    print("✅ 数据库初始化完成！")


if __name__ == "__main__":
    main()
