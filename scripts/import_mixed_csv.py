#!/usr/bin/env python3
"""
导入混合持仓 CSV（港股+美股）
"""
import csv
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.services.position_service import PositionService

CSV_FILE = "/Users/jediyang/ClaudeCode/Project-Makemoney/港:美股持仓-20260319-231320.csv"


def main():
    # 初始化数据库
    print("🗄️  初始化数据库...")
    init_db()

    db = SessionLocal()
    service = PositionService(db)

    hk_positions = []
    us_positions = []

    # 读取 CSV
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)

        for row in reader:
            if not row or not row[0].strip():
                continue

            code = row[0].strip().strip('"')
            name = row[1].strip().strip('"')
            shares = int(float(row[2].replace(",", "")))
            current_price = Decimal(row[4].replace(",", ""))
            avg_cost = Decimal(row[5].replace(",", ""))
            market_value = Decimal(row[6].replace(",", ""))
            currency = row[16].strip().strip('"')

            # 跳过已清仓的
            if shares == 0:
                print(f"⏭️  跳过 {code} ({name}): 已清仓")
                continue

            data = {
                "code": code,
                "name": name,
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "market_value": market_value,
                "currency": currency,
            }

            if currency == "HKD":
                hk_positions.append(data)
            elif currency == "USD":
                us_positions.append(data)

    # 计算各市场总资金
    hk_total = sum(p["market_value"] for p in hk_positions)
    us_total = sum(p["market_value"] for p in us_positions)

    print(f"\n📊 发现 {len(hk_positions)} 只港股，总市值: {hk_total:,.0f} HKD")
    print(f"📊 发现 {len(us_positions)} 只美股，总市值: {us_total:,.0f} USD\n")

    # 导入港股
    print("🇭🇰 导入港股...")
    for p in hk_positions:
        symbol = f"HK:{p['code']}"
        service.import_from_csv_row(
            symbol=symbol,
            name=p["name"],
            market="HK",
            currency="HKD",
            shares=p["shares"],
            avg_cost=p["avg_cost"],
            current_price=p["current_price"],
            market_total_fund=hk_total,
        )
        print(f"  ✅ {symbol} - {p['name']}: {p['shares']}股 @ {p['avg_cost']}")

    # 导入美股
    print("\n🇺🇸 导入美股...")
    for p in us_positions:
        symbol = f"US:{p['code']}"
        service.import_from_csv_row(
            symbol=symbol,
            name=p["name"],
            market="US",
            currency="USD",
            shares=p["shares"],
            avg_cost=p["avg_cost"],
            current_price=p["current_price"],
            market_total_fund=us_total,
        )
        print(f"  ✅ {symbol} - {p['name']}: {p['shares']}股 @ {p['avg_cost']}")

    db.close()
    print(f"\n🎉 导入完成！")
    print(f"   港股: {len(hk_positions)} 只")
    print(f"   美股: {len(us_positions)} 只")


if __name__ == "__main__":
    main()
