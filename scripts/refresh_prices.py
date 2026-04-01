#!/usr/bin/env python3
"""
刷新持仓股价 - 从多数据源获取最新价格
优先级：港股 Yahoo > Tushare > 东财 > Alpha，美股 Yahoo > Alpha
"""
import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.services.position_service import PositionService
from app.data_sources.aggregated_source import AggregatedPriceSource


def refresh_all_prices():
    """刷新所有持仓股票的股价"""
    print("🔄 初始化数据库...")
    init_db()

    db = SessionLocal()
    try:
        position_service = PositionService(db)
        price_source = AggregatedPriceSource()

        # 获取所有持仓
        positions = position_service.get_all_positions()
        print(f"📊 发现 {len(positions)} 只持仓股票\n")

        success_count = 0
        fail_count = 0
        failed_stocks = []

        for pos in positions:
            symbol = pos.stock_symbol
            stock = pos.stock
            if not stock:
                print(f"⚠️  {symbol}: 无股票信息，跳过")
                continue

            try:
                # 获取最新价格
                price_data = price_source.get_price(symbol)

                # 更新数据库
                stock.current_price = price_data.current_price
                stock.open_price = price_data.open_price
                stock.high_price = price_data.high_price
                stock.low_price = price_data.low_price
                stock.volume = price_data.volume
                stock.price_updated_at = datetime.now()

                db.commit()

                print(f"✅ {symbol:12} | {price_data.current_price:>10} | 来源: {price_data.source}")
                success_count += 1

            except Exception as e:
                print(f"❌ {symbol:12} | 失败: {str(e)[:50]}")
                fail_count += 1
                failed_stocks.append(symbol)

        print(f"\n{'='*50}")
        print(f"🎉 刷新完成!")
        print(f"   成功: {success_count}/{len(positions)}")
        print(f"   失败: {fail_count}")

        if failed_stocks:
            print(f"\n⚠️  失败的持仓:")
            for s in failed_stocks:
                print(f"   - {s}")

        # ── T+1条件单成交检查 ─────────────────────────────────────
        print("\n🔮 检查T+1条件单成交...")
        try:
            from app.services.signal_log_service import SignalLogService
            from app.models.stock import Stock

            # 构建价格 map
            price_map = {}
            all_stocks = db.query(Stock).all()
            for s in all_stocks:
                if s.current_price:
                    price_map[s.symbol] = {
                        "open":  float(s.open_price or s.current_price),
                        "high":  float(s.high_price or s.current_price),
                        "low":   float(s.low_price or s.current_price),
                        "close": float(s.current_price),
                    }

            log_svc = SignalLogService(db)
            stats = log_svc.auto_check_t1_orders(price_map)
            print(f"   BUY成交: {stats['buy_executed']}, SELL成交: {stats['sell_executed']}, 过期: {stats['expired']}")
        except Exception as e:
            print(f"⚠️  T+1条件单检查失败: {e}")

        # ── 持仓中信号的止损止盈检查 ─────────────────────────────────────
        print("\n🛡️  检查持仓信号止损止盈...")
        try:
            from app.services.signal_log_service import SignalLogService
            from app.models.stock import Stock

            # 构建价格 map
            price_map = {}
            all_stocks = db.query(Stock).all()
            for s in all_stocks:
                if s.current_price:
                    price_map[s.symbol] = {
                        "high":  float(s.high_price or s.current_price),
                        "low":   float(s.low_price or s.current_price),
                        "close": float(s.current_price),
                    }

            log_svc = SignalLogService(db)
            n = log_svc.auto_check_sim_exits(price_map)
            print(f"   止损/止盈出场: {n} 条")
        except Exception as e:
            print(f"⚠️  止损止盈检查失败: {e}")

        # ── 富途成交同步 ─────────────────────────────────────
        print("\n📥 同步富途历史成交...")
        try:
            from app.services.futu_deal_sync_service import FutuDealSyncService
            deal_svc = FutuDealSyncService(db)
            result = deal_svc.sync()
            print(f"   新增: {result['synced']}, 跳过: {result['skipped']}")
        except Exception as e:
            print(f"⚠️  富途成交同步失败: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    refresh_all_prices()
