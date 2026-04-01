#!/bin/bash
# 光剑系统状态检查脚本
# 用法: ./status.sh

echo "🔍 光剑系统状态检查"
echo ""

# 检查进程 (匹配 run.py 启动方式)
PIDS=$(pgrep -f "python run.py" || pgrep -f "uvicorn.*app.main:app" || true)

if [ -z "$PIDS" ]; then
    echo "❌ 状态: 未运行"
    echo ""
    echo "   启动命令: ./start.sh"
else
    echo "✅ 状态: 运行中"
    echo ""
    echo "   进程详情:"
    for PID in $PIDS; do
        ps -p "$PID" -o pid,cpu,mem,etime,command 2>/dev/null | tail -1 | sed 's/^/   /'
    done
    echo ""
    echo "   访问地址: http://127.0.0.1:8080"
    echo "   停止命令: ./stop.sh"
fi

echo ""
echo "📊 端口占用情况:"
if lsof -i :8080 2>/dev/null | grep -q "LISTEN"; then
    lsof -i :8080 | grep "LISTEN" | awk '{print "   " $1 " (PID: " $2 ")"}'
else
    echo "   端口 8080 未被监听"
fi

# 检查磁盘空间
echo ""
echo "💾 磁盘空间:"
df -h . | tail -1 | awk '{print "   可用: " $4 " / 总计: " $2 " (" $5 " 已用)"}'

# 检查日志
echo ""
echo "📝 最近日志:"
if [ -f "logs/server.log" ]; then
    tail -3 logs/server.log | sed 's/^/   /'
else
    echo "   暂无日志文件"
fi
