#!/bin/bash
# 光剑系统启动脚本
# 用法: ./start.sh [选项]
# 选项:
#   -d, --daemon  后台模式启动
#   -h, --help    显示帮助

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 错误: 虚拟环境不存在"
    exit 1
fi

# 解析参数
DAEMON_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--daemon)
            DAEMON_MODE=true
            shift
            ;;
        -h|--help)
            echo "光剑系统启动脚本"
            echo ""
            echo "用法: ./start.sh [选项]"
            echo ""
            echo "选项:"
            echo "  -d, --daemon  后台模式启动"
            echo "  -h, --help    显示帮助"
            echo ""
            echo "示例:"
            echo "  ./start.sh           # 前台启动"
            echo "  ./start.sh -d        # 后台启动"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 -h 查看帮助"
            exit 1
            ;;
    esac
done

# 检查端口是否被占用（只检查 LISTEN 状态）
if lsof -i :8080 2>/dev/null | grep -q "LISTEN"; then
    echo "⚠️  端口 8080 已被占用"
    echo "   可能光剑系统已在运行"
    echo "   访问: http://127.0.0.1:8080"
    exit 1
fi

echo "⚡ 启动光剑系统..."
echo "   工作目录: $SCRIPT_DIR"
echo ""

if [ "$DAEMON_MODE" = true ]; then
    # 后台模式
    nohup ./venv/bin/python run.py > logs/server.log 2>&1 &
    echo "🚀 光剑系统已在后台启动"
    echo "   访问地址: http://127.0.0.1:8080"
    echo "   日志文件: logs/server.log"
    echo "   进程ID: $!"
    echo ""
    echo "   停止命令: ./stop.sh"
else
    # 前台模式
    echo "🚀 启动中... (按 Ctrl+C 停止)"
    echo ""
    ./venv/bin/python run.py
fi
