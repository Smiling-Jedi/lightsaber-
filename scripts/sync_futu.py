#!/usr/bin/env python3
"""
同步富途持仓和现金到本地数据库
从富途 OpenD 拉取最新持仓、现金、基金数据
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.services.futu_sync_service import FutuSyncService


def sync_futu():
    """执行富途同步"""
    print("🔄 初始化数据库...")
    init_db()

    db = SessionLocal()
    try:
        print("📥 连接富途 OpenD (127.0.0.1:11111)...")
        svc = FutuSyncService(db)
        result = svc.sync()

        print(f"\n{'='*50}")
        print(f"🎉 富途同步完成!")
        print(f"   持仓同步: {result['synced']} 条")
        print(f"   新建持仓: {result['created']} 条")
        print(f"   交易同步: {result.get('trades_synced', 0)} 条")

        if result.get('market_funds'):
            print(f"\n💰 账户资金:")
            for market, assets in result['market_funds'].items():
                print(f"   {market}: {assets:,.2f}")

        if result.get('errors'):
            print(f"\n⚠️  错误 ({len(result['errors'])}):")
            for e in result['errors'][:5]:
                print(f"   - {e}")

    except ConnectionError as e:
        print(f"\n❌ 连接失败: {e}")
        print("   请确认富途 OpenD 已启动 (127.0.0.1:11111)")
    except Exception as e:
        print(f"\n❌ 同步失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    sync_futu()
