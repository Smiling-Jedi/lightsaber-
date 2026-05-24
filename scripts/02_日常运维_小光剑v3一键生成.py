#!/usr/bin/env python3
"""
小光剑 v3 一键生成脚本

用法:
    cd lightsaber && source venv/bin/activate && python scripts/02_日常运维_小光剑v3一键生成.py

默认流程（快速）:
    1. 刷新持仓股价
    2. 静态化导出 v3
    3. 推送到 GitHub Pages

加 --analyze 则插入第2步：三周期形态分析（~30-60分钟, $12-18）

前置检查:
    - 富途 OpenD 已启动 (127.0.0.1:11111)
    - 环境变量 ANTHROPIC_API_KEY 已配置（形态分析时需要）
    - Git 工作区干净（脚本会自动检查）
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


# ────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────

def run_cmd(cmd: list, cwd: str = None, check: bool = True) -> subprocess.CompletedProcess:
    """运行shell命令，打印输出"""
    print(f"  \n$ {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd or project_root,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    if result.stderr and "warning" not in result.stderr.lower():
        for line in result.stderr.strip().split("\n"):
            if line.strip():
                print(f"    [stderr] {line}")
    if check and result.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)} (exit={result.returncode})")
    return result


def check_git_clean() -> bool:
    """检查Git工作区是否干净"""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == ""


def print_banner(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_step(step: int, total: int, title: str):
    print(f"\n{'─' * 60}")
    print(f"  Step {step}/{total}: {title}")
    print(f"{'─' * 60}")


# ────────────────────────────────────────────────
# 各阶段函数
# ────────────────────────────────────────────────

def step_refresh_prices():
    """Step 1: 刷新股价"""
    from app.core.database import SessionLocal, init_db
    from app.services.position_service import PositionService
    from app.data_sources.aggregated_source import AggregatedPriceSource
    from datetime import datetime

    init_db()
    db = SessionLocal()
    try:
        position_service = PositionService(db)
        price_source = AggregatedPriceSource()

        positions = position_service.get_all_positions()
        print(f"  持仓数量: {len(positions)} 只\n")

        success = 0
        failed = []
        for pos in positions:
            symbol = pos.stock_symbol
            stock = pos.stock
            if not stock:
                print(f"  ⚠️  {symbol}: 无股票信息，跳过")
                continue
            try:
                price_data = price_source.get_price(symbol)
                stock.current_price = price_data.current_price
                stock.open_price = price_data.open_price
                stock.high_price = price_data.high_price
                stock.low_price = price_data.low_price
                stock.volume = price_data.volume
                stock.price_updated_at = datetime.now()
                db.commit()
                print(f"  ✅ {symbol:12} | {price_data.current_price:>10} | {price_data.source}")
                success += 1
            except Exception as e:
                print(f"  ❌ {symbol:12} | 失败: {str(e)[:50]}")
                failed.append(symbol)

        print(f"\n  刷新结果: 成功 {success}/{len(positions)}, 失败 {len(failed)}")

        # T+1 条件单检查
        print("\n  🔮 检查 T+1 条件单...")
        try:
            from app.services.signal_log_service import SignalLogService
            price_map = {}
            all_stocks = db.query(__import__("app.models.stock", fromlist=["Stock"]).Stock).all()
            for s in all_stocks:
                if s.current_price:
                    price_map[s.symbol] = {
                        "open": float(s.open_price or s.current_price),
                        "high": float(s.high_price or s.current_price),
                        "low": float(s.low_price or s.current_price),
                        "close": float(s.current_price),
                    }
            log_svc = SignalLogService(db)
            stats = log_svc.auto_check_t1_orders(price_map)
            print(f"     BUY成交: {stats['buy_executed']}, SELL成交: {stats['sell_executed']}, 过期: {stats['expired']}")
        except Exception as e:
            print(f"     ⚠️  跳过: {e}")

        # 止损止盈检查
        print("\n  🛡️  检查止损止盈...")
        try:
            from app.services.signal_log_service import SignalLogService
            price_map = {}
            all_stocks = db.query(__import__("app.models.stock", fromlist=["Stock"]).Stock).all()
            for s in all_stocks:
                if s.current_price:
                    price_map[s.symbol] = {
                        "high": float(s.high_price or s.current_price),
                        "low": float(s.low_price or s.current_price),
                        "close": float(s.current_price),
                    }
            log_svc = SignalLogService(db)
            n = log_svc.auto_check_sim_exits(price_map)
            print(f"     止损/止盈出场: {n} 条")
        except Exception as e:
            print(f"     ⚠️  跳过: {e}")

        # 富途成交同步
        print("\n  📥 同步富途成交...")
        try:
            from app.services.futu_deal_sync_service import FutuDealSyncService
            deal_svc = FutuDealSyncService(db)
            result = deal_svc.sync()
            print(f"     新增: {result['synced']}, 跳过: {result['skipped']}")
        except Exception as e:
            print(f"     ⚠️  跳过: {e}")

    finally:
        db.close()


def step_pattern_analysis():
    """Step 2 (可选): 三周期形态分析 — 完整的批量分析"""
    import time
    from app.core.database import SessionLocal
    from app.services.pattern_analysis_service import PatternAnalysisService
    from app.models.position import Position
    from app.models.stock import Stock

    db = SessionLocal()
    try:
        # 1. 列出待分析持仓
        positions = (
            db.query(Position)
            .filter(Position.total_shares > 0)
            .order_by(Position.stock_symbol)
            .all()
        )
        symbols = [p.stock_symbol for p in positions]

        print(f"\n  待分析持仓: {len(symbols)} 只")
        for s in symbols:
            stock = db.get(Stock, s)
            name = stock.name if stock else "(无元数据)"
            print(f"    - {s} {name}")

        # 2. 显示预估
        n_symbols = len(symbols)
        print(f"\n  预估: ~{n_symbols * 3} 次 LLM 调用 ({n_symbols}只 × 3周期)")
        print(f"       模型: claude-opus-4-7, 成本约 ${n_symbols * 0.4:.1f}-${n_symbols * 0.6:.1f}")
        print(f"       耗时: 约 {n_symbols}-{(n_symbols * 2)} 分钟\n")

        # 3. 执行分析
        service = PatternAnalysisService(db)
        start_ts = time.time()
        result = service.analyze_all_holdings()
        elapsed = time.time() - start_ts

        # 4. 结果汇总
        print(f"\n  {'='*50}")
        print(f"  形态分析完成")
        print(f"  {'='*50}")
        print(f"  总计: {result['total']} 只")
        print(f"  成功: {result['success']} 只")
        print(f"  失败: {result['failed']} 只")
        print(f"  耗时: {elapsed:.0f} 秒 ({elapsed/60:.1f} 分钟)")

        if result['errors']:
            print(f"\n  失败明细:")
            for err in result['errors'][:10]:
                print(f"    - {err}")
            if len(result['errors']) > 10:
                print(f"    ... 共 {len(result['errors'])} 条失败")

        # 5. 最新分析结果速览
        print(f"\n  最新分析速览:")
        from app.models.pattern_analysis import PatternAnalysis
        for symbol in symbols[:5]:
            for period in ["day", "week", "month"]:
                pa = (
                    db.query(PatternAnalysis)
                    .filter_by(stock_symbol=symbol, period=period)
                    .order_by(PatternAnalysis.analysis_date.desc())
                    .first()
                )
                if pa:
                    state_emoji = {"已确认": "✅", "构筑中": "🔨", "突破待确认": "⏳", "失效": "❌"}.get(pa.pattern_state, "•")
                    print(f"    {symbol:12} {period:4} | {state_emoji} {pa.pattern_name} ({pa.pattern_state})")
        if len(symbols) > 5:
            print(f"    ... 共 {len(symbols)} 只，详见数据库")

    finally:
        db.close()


def step_static_export():
    """Step 3: 静态化导出"""
    import shutil
    import re

    from starlette.testclient import TestClient
    from app.main import app
    from app.core.database import SessionLocal
    from app.models.position import Position

    OUT_DIR = Path(project_root) / "docs" / "mini-v3"

    # 清理旧输出
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    (OUT_DIR / "stock").mkdir()

    client = TestClient(app)

    # 导出首页
    print("\n  导出首页...")
    resp = client.get("/mini/v3/")
    if resp.status_code != 200:
        raise RuntimeError(f"首页导出失败: status={resp.status_code}")

    home_html = re.sub(
        r'\./stock/([A-Z]+):(\w+)\.html',
        lambda m: f'stock/{m.group(1)}_{m.group(2)}.html',
        resp.text,
    )
    (OUT_DIR / "index.html").write_text(home_html, encoding="utf-8")
    print(f"  ✅ index.html ({len(home_html)} chars)")

    # 导出详情页
    db = SessionLocal()
    try:
        positions = db.query(Position).filter(Position.total_shares > 0).order_by(Position.stock_symbol).all()
        symbols = [p.stock_symbol for p in positions]
    finally:
        db.close()

    print(f"\n  导出 {len(symbols)} 个详情页...")
    success = 0
    failed = []
    for symbol in symbols:
        try:
            resp = client.get(f"/mini/v3/stock/{symbol}")
            if resp.status_code != 200:
                failed.append(f"{symbol} (status={resp.status_code})")
                continue
            html = resp.text.replace('href="/mini/v3/"', 'href="../index.html"')
            html = html.replace("href='/mini/v3/'", "href='../index.html'")
            filename = f"{symbol.replace(':', '_')}.html"
            (OUT_DIR / "stock" / filename).write_text(html, encoding="utf-8")
            print(f"  ✅ {filename}")
            success += 1
        except Exception as e:
            failed.append(f"{symbol}: {e}")
            print(f"  ❌ {symbol}: {e}")

    print(f"\n  导出完成: {success}/{len(symbols)}")
    if failed:
        print(f"  失败: {failed}")
    return success == len(symbols)


def step_git_push():
    """Step 4: GitHub Push"""
    # 检查是否有变更
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() == "":
        print("\n  ⚠️ 无变更需要提交")
        return True

    # add + commit
    run_cmd(["git", "add", "-A"])

    timestamp = time.strftime("%Y%m%d_%H%M")
    commit_msg = f"chore: v3 自动更新 {timestamp}"
    run_cmd(["git", "commit", "-m", commit_msg])

    # push
    run_cmd(["git", "push"])
    print(f"\n  ✅ 已推送至 GitHub Pages")
    return True


# ────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="小光剑 v3 一键生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/02_日常运维_小光剑v3一键生成.py        # 快速: 刷新价格 + 静态化 + push
  python scripts/02_日常运维_小光剑v3一键生成.py --analyze  # 完整: + 形态分析
  python scripts/02_日常运维_小光剑v3一键生成.py --no-push   # 本地: 不推送到 GitHub
        """,
    )
    parser.add_argument(
        "--analyze", "-a",
        action="store_true",
        help="执行三周期形态分析（耗时 ~30-60min, 成本 ~$12-18）",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="静态化后不推送到 GitHub",
    )
    args = parser.parse_args()

    print_banner("小光剑 v3 一键生成")
    print(f"  模式: {'完整（含形态分析）' if args.analyze else '快速'}")
    print(f"  Push: {'否' if args.no_push else '是'}")
    print(f"  开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Git 工作区检查
    if not check_git_clean():
        print("\n⚠️  Git 工作区有未提交变更，请先处理:")
        subprocess.run(["git", "status", "--short"], cwd=project_root)
        print("\n  提示: git add + git commit 后重试，或用 --no-push 跳过 push 步骤")
        sys.exit(1)

    total_steps = 3 + (1 if args.analyze else 0)
    step = 0
    start_all = time.time()

    try:
        # Step 1: 刷新价格
        step += 1
        print_step(step, total_steps, "刷新持仓股价")
        step_refresh_prices()

        # Step 2 (可选): 形态分析
        if args.analyze:
            step += 1
            print_step(step, total_steps, "三周期形态分析")
            if not os.getenv("ANTHROPIC_API_KEY"):
                print("  ❌ 环境变量 ANTHROPIC_API_KEY 未设置，跳过形态分析")
            else:
                step_pattern_analysis()

        # Step 3: 静态化导出
        step += 1
        print_step(step, total_steps, "静态化导出 v3")
        ok = step_static_export()
        if not ok:
            print("\n  ⚠️ 部分页面导出失败，继续推送已成功页面")

        # Step 4: GitHub Push
        if not args.no_push:
            step += 1
            print_step(step, total_steps, "推送到 GitHub Pages")
            step_git_push()
        else:
            print(f"\n{'─' * 60}")
            print("  已跳过 GitHub Push（--no-push）")
            print(f"{'─' * 60}")

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"  ❌ 执行失败: {e}")
        print(f"{'=' * 60}")
        sys.exit(1)

    elapsed = time.time() - start_all
    print(f"\n{'=' * 60}")
    print(f"  ✅ 全部完成")
    print(f"  总耗时: {elapsed:.0f} 秒 ({elapsed / 60:.1f} 分钟)")
    print(f"  线上地址: https://smiling-jedi.github.io/lightsaber-/mini-v3/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
