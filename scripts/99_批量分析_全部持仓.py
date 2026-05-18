"""
批量分析全部持仓的三周期形态

用法:
    cd lightsaber && source venv/bin/activate && python scripts/99_批量分析_全部持仓.py

范围: 数据库里全部 total_shares > 0 的持仓(港股 + 美股 + A 股,含港股通)
预估: ~30-60 分钟,90 次 LLM 调用(30 只 × 3 周期),Opus 4.7 成本约 $12-18

前提:
- 富途 OpenD 已启动并登录(127.0.0.1:11111)
- 环境变量 ANTHROPIC_API_KEY 已配置
"""
import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.core.database import SessionLocal
from app.services.pattern_analysis_service import PatternAnalysisService
from app.models.position import Position
from app.models.stock import Stock


def main():
    print("=" * 60)
    print("批量分析 — 全部持仓 三周期形态")
    print("=" * 60)

    db = SessionLocal()
    try:
        # 先列出待分析的持仓
        positions = (
            db.query(Position)
            .filter(Position.total_shares > 0)
            .order_by(Position.stock_symbol)
            .all()
        )
        symbols = [p.stock_symbol for p in positions]
        print(f"\n待分析持仓: {len(symbols)} 只")
        for s in symbols:
            stock = db.get(Stock, s)
            name = stock.name if stock else "(无元数据)"
            print(f"  - {s} {name}")
        print()

        service = PatternAnalysisService(db)

        start_ts = time.time()
        result = service.analyze_all_holdings()  # symbols=None → 自动读 Position 表
        elapsed = time.time() - start_ts

        print(f"\n{'=' * 60}")
        print("分析完成")
        print('=' * 60)
        print(f"总计: {result['total']} 只")
        print(f"成功: {result['success']} 只")
        print(f"失败: {result['failed']} 只")
        print(f"耗时: {elapsed:.1f} 秒 ({elapsed / 60:.1f} 分钟)")
        if result['errors']:
            print(f"\n失败明细:")
            for err in result['errors']:
                print(f"  - {err}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
