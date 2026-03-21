"""
一次性初始化模拟持仓快照

从真实持仓表复制当前持仓到 sim_positions 表，作为对比起跑线。
已存在任何模拟持仓时跳过（只允许执行一次）。

运行方式：
    cd lightsaber
    python scripts/init_sim_positions.py
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.position import Position
from app.models.sim_position import SimPosition
from app.models.stock import Stock


def run():
    db = SessionLocal()
    try:
        existing_count = db.query(SimPosition).count()
        if existing_count > 0:
            print(f"模拟持仓已存在 {existing_count} 条，跳过初始化（只允许执行一次）。")
            print("如需重置，请手动清空 sim_positions 表后重新执行。")
            return

        positions = db.query(Position).all()
        if not positions:
            print("真实持仓为空，请先同步富途持仓后再执行。")
            return

        snapshot_date = date.today()
        created = 0

        for pos in positions:
            stock: Stock = db.get(Stock, pos.stock_symbol)
            last_price = float(stock.current_price) if stock and stock.current_price else None

            sim = SimPosition(
                symbol           = pos.stock_symbol,
                name             = stock.name if stock else "",
                category         = None,   # 可后续手动维护
                currency         = pos.currency,
                snapshot_date    = snapshot_date,
                initial_shares   = pos.total_shares,
                initial_avg_cost = float(pos.avg_cost) if pos.avg_cost else None,
                shares           = pos.total_shares,
                avg_cost         = float(pos.avg_cost) if pos.avg_cost else None,
                last_price       = last_price,
                market_value     = pos.total_shares * last_price if last_price else None,
            )
            db.add(sim)
            created += 1
            print(f"  + {pos.stock_symbol} | {pos.total_shares}股 | 均价 {pos.avg_cost}")

        db.commit()
        print(f"\n✓ 模拟持仓初始化完成，共 {created} 条，快照日期：{snapshot_date}")

    finally:
        db.close()


if __name__ == "__main__":
    run()
