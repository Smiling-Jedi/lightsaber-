#!/bin/bash
# 光剑系统停止脚本

echo "🛑 停止光剑系统..."

# 查找并杀死 uvicorn 进程
PID=$(lsof -i :8080 | grep LISTEN | awk '{print $2}')
if [ -n "$PID" ]; then
    kill -9 $PID 2>/dev/null
    echo "✅ 服务器已停止 (PID: $PID)"
else
    echo "⚠️ 服务器未运行"
fi
