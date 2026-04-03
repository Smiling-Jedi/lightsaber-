#!/bin/bash
# 光剑系统启动脚本 - 自动清理缓存防止SQLAlchemy映射问题

echo "🚀 启动光剑系统..."

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
source venv/bin/activate

# 清理 Python 缓存（防止SQLAlchemy映射问题）
echo "🧹 清理缓存..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null

# 确保数据目录存在
mkdir -p data/kline_cache

# 启动服务器
echo "✅ 启动服务器 http://127.0.0.1:8080"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
