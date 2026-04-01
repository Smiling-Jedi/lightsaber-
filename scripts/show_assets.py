#!/usr/bin/env python3
"""查询资产明细"""
import sys
sys.path.insert(0, '.')

from app.core.database import SessionLocal
from app.services.portfolio_service import PortfolioService

db = SessionLocal()
svc = PortfolioService(db)

print('=' * 60)
print('光剑系统 - 资产明细报告')
print('=' * 60)

# 真实账户
print('\n📊 真实账户 (REAL)')
print('-' * 40)
try:
    real_assets = svc.get_total_assets('REAL', detail=True)
    print(f"总资产 (RMB): ¥{float(real_assets['total_rmb']):,.2f}")
    print(f"  ├── HKD: ${float(real_assets['total_hkd']):,.2f}")
    print(f"  ├── USD: ${float(real_assets['total_usd']):,.2f}")
    print(f"  └── CNY: ¥{float(real_assets['total_cny']):,.2f}")

    if 'breakdown' in real_assets and real_assets['breakdown']:
        breakdown = real_assets['breakdown']
        print(f"\n持仓明细:")
        if 'stocks' in breakdown and breakdown['stocks']:
            for symbol, info in breakdown['stocks'].items():
                print(f"  {symbol}: {info.get('shares', 0)}股 @ ¥{float(info.get('price', 0)):.2f} = ¥{float(info.get('value', 0)):,.2f}")
        else:
            print("  (无股票持仓)")

        print(f"\n现金余额:")
        for currency, amount in breakdown.get('cash', {}).items():
            print(f"  {currency}: ${float(amount):,.2f}")
except Exception as e:
    print(f'获取真实账户数据失败: {e}')

# 模拟账户
print('\n📈 模拟账户 (SIMULATED)')
print('-' * 40)
try:
    sim_assets = svc.get_total_assets('SIMULATED', detail=True)
    print(f"总资产 (RMB): ¥{float(sim_assets['total_rmb']):,.2f}")
    print(f"  ├── HKD: ${float(sim_assets['total_hkd']):,.2f}")
    print(f"  ├── USD: ${float(sim_assets['total_usd']):,.2f}")
    print(f"  └── CNY: ¥{float(sim_assets['total_cny']):,.2f}")

    if 'breakdown' in sim_assets and sim_assets['breakdown']:
        breakdown = sim_assets['breakdown']
        print(f"\n持仓明细:")
        if 'stocks' in breakdown and breakdown['stocks']:
            for symbol, info in breakdown['stocks'].items():
                batch = info.get('batch_status', '')
                batch_str = f"[{batch}]" if batch else ""
                print(f"  {symbol} {batch_str}: {info.get('shares', 0)}股 @ ¥{float(info.get('price', 0)):.2f}")
        else:
            print("  (无股票持仓)")

        print(f"\n现金余额:")
        for currency, amount in breakdown.get('cash', {}).items():
            print(f"  {currency}: ${float(amount):,.2f}")
except Exception as e:
    print(f'获取模拟账户数据失败: {e}')

# 最新快照
print('\n📸 最新资产快照')
print('-' * 40)
try:
    real_snap = svc.get_latest_snapshot('REAL')
    if real_snap:
        print(f"真实账户: ¥{float(real_snap.total_assets_rmb):,.2f} ({real_snap.snapshot_date})")
    else:
        print("真实账户: 无快照记录")

    sim_snap = svc.get_latest_snapshot('SIMULATED')
    if sim_snap:
        print(f"模拟账户: ¥{float(sim_snap.total_assets_rmb):,.2f} ({sim_snap.snapshot_date})")
    else:
        print("模拟账户: 无快照记录")
except Exception as e:
    print(f'获取快照失败: {e}')

print('\n' + '=' * 60)
db.close()
