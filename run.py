#!/usr/bin/env python3
"""
光剑系统启动脚本
"""
import uvicorn
from app.core.database import init_db

if __name__ == "__main__":
    # 初始化数据库
    print("🗄️  初始化数据库...")
    init_db()
    print("✅ 数据库就绪")

    # 启动服务器
    print("🚀 启动光剑系统...")
    print("📍 访问地址: http://127.0.0.1:8080")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8080,
        reload=True,
        log_level="info"
    )
