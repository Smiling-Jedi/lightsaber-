#!/bin/bash
# 小光剑静态页面一键部署脚本
# 用法: ./deploy_mini.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo -e "${RED}错误: 虚拟环境不存在${NC}"
    exit 1
fi

PYTHON="$SCRIPT_DIR/venv/bin/python"

show_menu() {
    clear
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  ⚡ 小光剑静态页面部署控制台 ⚡              ║"
    echo "╠══════════════════════════════════════════════╣"
    echo "║                                              ║"
    echo "║  [1] 快速更新 (同步价格 + 生成 + push)       ║"
    echo "║      ~2 分钟 | 只更新价格,不跑 LLM          ║"
    echo "║                                              ║"
    echo "║  [2] 深度更新 (全量分析 + 生成 + push)       ║"
    echo "║      ~40 分钟 | 重新跑 30 只形态分析        ║"
    echo "║                                              ║"
    echo "║  [3] 仅生成静态页 (不更新任何数据)           ║"
    echo "║      ~5 秒 | 用当前数据库生成 HTML          ║"
    echo "║                                              ║"
    echo "║  [4] 查看上次部署状态                        ║"
    echo "║                                              ║"
    echo "║  [5] 打开线上页面 (手机浏览器)               ║"
    echo "║      https://smiling-jedi.github.io/...     ║"
    echo "║                                              ║"
    echo "║  [0] 退出                                    ║"
    echo "║                                              ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
}

quick_update() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  快速更新: 同步价格 → 生成 → push${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    echo -e "${YELLOW}[1/4] 同步富途持仓与价格...${NC}"
    $PYTHON scripts/sync_futu.py || echo -e "${YELLOW}  富途同步跳过 (可能 OpenD 未启动)${NC}"

    echo ""
    echo -e "${YELLOW}[2/4] 刷新全部持仓股价...${NC}"
    $PYTHON scripts/refresh_prices.py || echo -e "${YELLOW}  价格刷新部分失败${NC}"

    echo ""
    echo -e "${YELLOW}[3/4] 生成静态 HTML...${NC}"
    $PYTHON scripts/99_静态化_导出mini.py

    echo ""
    echo -e "${YELLOW}[4/4] Git push 触发 Pages 更新...${NC}"
    git add docs/
    git commit -m "Update prices $(date +%Y-%m-%d_%H:%M)" || echo -e "${YELLOW}  无变更需提交${NC}"
    git push origin main

    echo ""
    echo -e "${GREEN}✅ 快速更新完成!${NC}"
    echo -e "${GREEN}   线上地址: https://Smiling-Jedi.github.io/lightsaber-/mini/${NC}"
    echo -e "${GREEN}   约 1-2 分钟后手机刷新可见${NC}"
}

deep_update() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  深度更新: 全量分析 → 生成 → push${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    echo -e "${YELLOW}[1/5] 同步富途持仓与价格...${NC}"
    $PYTHON scripts/sync_futu.py || echo -e "${YELLOW}  富途同步跳过${NC}"

    echo ""
    echo -e "${YELLOW}[2/5] 刷新全部持仓股价...${NC}"
    $PYTHON scripts/refresh_prices.py || true

    echo ""
    echo -e "${YELLOW}[3/5] 全量形态分析 (30 只 × 3 周期, 约 30-60 分钟)...${NC}"
    echo -e "${YELLOW}      按 Ctrl+C 可随时中断${NC}"
    $PYTHON scripts/99_批量分析_全部持仓.py

    echo ""
    echo -e "${YELLOW}[4/5] 生成静态 HTML...${NC}"
    $PYTHON scripts/99_静态化_导出mini.py

    echo ""
    echo -e "${YELLOW}[5/5] Git push 触发 Pages 更新...${NC}"
    git add docs/
    git commit -m "Update analysis $(date +%Y-%m-%d_%H:%M)"
    git push origin main

    echo ""
    echo -e "${GREEN}✅ 深度更新完成!${NC}"
    echo -e "${GREEN}   线上地址: https://Smiling-Jedi.github.io/lightsaber-/mini/${NC}"
}

generate_only() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  仅生成静态页 (不更新数据)${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    $PYTHON scripts/99_静态化_导出mini.py

    echo ""
    echo -e "${YELLOW}Git push 触发 Pages 更新...${NC}"
    git add docs/
    git commit -m "Regenerate static site $(date +%Y-%m-%d_%H:%M)" || true
    git push origin main || true

    echo ""
    echo -e "${GREEN}✅ 生成完成!${NC}"
}

show_status() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  部署状态${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    echo -e "${YELLOW}Git 状态:${NC}"
    git log --oneline -3

    echo ""
    echo -e "${YELLOW}最新部署时间:${NC}"
    git log -1 --format="%cd" --date=format:"%Y-%m-%d %H:%M" -- docs/

    echo ""
    echo -e "${YELLOW}Pages 线上地址:${NC}"
    echo "  https://Smiling-Jedi.github.io/lightsaber-/mini/"

    echo ""
    echo -e "${YELLOW}本地文件:${NC}"
    echo "  首页: docs/mini/index.html"
    echo "  详情页: docs/mini/stock/ (30 个)"
}

open_page() {
    echo "正在打开线上页面..."
    open "https://Smiling-Jedi.github.io/lightsaber-/mini/" 2>/dev/null || \
        echo "请手动访问: https://Smiling-Jedi.github.io/lightsaber-/mini/"
}

# 主循环
while true; do
    show_menu
    read -p "请选择操作 [0-5]: " choice

    case $choice in
        1)
            echo ""
            quick_update
            echo ""
            read -p "按回车键返回菜单..."
            ;;
        2)
            echo ""
            read -p "深度更新需要 30-60 分钟,确认? (y/N): " confirm
            if [[ $confirm == [yY] ]]; then
                deep_update
            else
                echo "已取消"
            fi
            echo ""
            read -p "按回车键返回菜单..."
            ;;
        3)
            echo ""
            generate_only
            echo ""
            read -p "按回车键返回菜单..."
            ;;
        4)
            echo ""
            show_status
            echo ""
            read -p "按回车键返回菜单..."
            ;;
        5)
            open_page
            echo ""
            read -p "按回车键返回菜单..."
            ;;
        0)
            echo ""
            echo "👋 再见"
            exit 0
            ;;
        *)
            echo -e "${RED}无效选项: $choice${NC}"
            sleep 1
            ;;
    esac
done
