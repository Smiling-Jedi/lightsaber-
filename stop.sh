#!/bin/bash
# 光剑系统停止脚本
# 用法: ./stop.sh

set -e

echo "🛑 停止光剑系统..."

# 查找并终止 Python 进程
PIDS=$(pgrep -f "python run.py" || pgrep -f "uvicorn.*app.main:app" || true)

if [ -z "$PIDS" ]; then
    echo "   没有找到运行中的光剑系统进程"
    exit 0
fi

echo "   找到进程: $PIDS"

# 优雅终止
for PID in $PIDS; do
    kill -TERM "$PID" 2>/dev/null || true
done

# 等待进程结束
sleep 1

# 检查是否还有残留
REMAINING=$(pgrep -f "uvicorn.*app.main:app" || true)
if [ -n "$REMAINING" ]; then
    echo "   强制终止残留进程..."
    for PID in $REMAINING; do
        kill -KILL "$PID" 2>/dev/null || true
    done
fi

echo "✅ 光剑系统已停止"
