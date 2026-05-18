"""
A 股补跑 — 上次全量分析时富途 A 股权限不足导致失败的 9 只

用法:
    cd lightsaber && python scripts/99_批量分析_A股补跑.py

9 只 A 股(含 ETF):
    A:002594, A:300274, A:300750, A:512010, A:562500,
    A:600030, A:600036, A:601166, A:601328
"""
import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.core.database import SessionLocal
from app.services.pattern_analysis_service import PatternAnalysisService

A_STOCKS = [
    "A:002594",   # 比亚迪
    "A:300274",   # 阳光电源
    "A:300750",   # 宁德时代
    "A:512010",   # 医药ETF易方达
    "A:562500",   # 机器人ETF华夏
    "A:600030",   # 中信证券
    "A:600036",   # 招商银行
    "A:601166",   # 兴业银行
    "A:601328",   # 交通银行
]


def main():
    print("=" * 60)
    print("A 股补跑 — 上次富途 A 股 K 线失败的 9 只")
    print("=" * 60)

    db = SessionLocal()
    try:
        service = PatternAnalysisService(db)
        start_ts = time.time()
        result = service.analyze_all_holdings(symbols=A_STOCKS)
        elapsed = time.time() - start_ts

        print(f"\n{'=' * 60}")
        print("补跑完成")
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
