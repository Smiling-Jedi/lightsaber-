#!/usr/bin/env python3
"""
导入 A 股持仓数据（从截图提取）
"""
import sys
from decimal import Decimal
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.services.position_service import PositionService

# A 股持仓数据（从截图提取，2026-03-24）
# 总资产约 555万 RMB，用于计算仓位占比
A_SHARE_HOLDINGS = [
    # 代码, 名称, 持仓数量, 成本价, 现价
    ("512010", "医药ETF易方达", 2457100, Decimal("0.3966"), Decimal("0.3570")),
    ("562500", "机器人ETF华夏", 700000, Decimal("0.9573"), Decimal("0.9200")),
    ("600030", "中信证券", 20200, Decimal("27.8337"), Decimal("24.3600")),
    ("600036", "招商银行", 2500, Decimal("39.3939"), Decimal("39.2500")),
    ("601166", "兴业银行", 5500, Decimal("18.7165"), Decimal("18.7200")),
    ("601328", "交通银行", 15000, Decimal("7.0953"), Decimal("6.8200")),
    ("002594", "比亚迪", 15000, Decimal("87.9491"), Decimal("106.6400")),
    ("300059", "东方财富", 25000, Decimal("24.9730"), Decimal("19.7700")),
    ("300274", "阳光电源", 1700, Decimal("160.5883"), Decimal("164.6800")),
    ("300750", "宁德时代", 1000, Decimal("118.3013"), Decimal("396.9900")),
]

# A 股总资产（用于计算仓位占比）
A_TOTAL_ASSETS = Decimal("5550000")  # 约 555 万 RMB


def import_a_shares():
    """导入 A 股持仓"""
    print("🗄️ 初始化数据库...")
    init_db()

    db = SessionLocal()
    try:
        service = PositionService(db)
        imported = 0

        for code, name, shares, avg_cost, current_price in A_SHARE_HOLDINGS:
            symbol = f"A:{code}"

            try:
                position = service.import_from_csv_row(
                    symbol=symbol,
                    name=name,
                    market="A",
                    currency="CNY",
                    shares=shares,
                    avg_cost=avg_cost,
                    current_price=current_price,
                    market_total_fund=A_TOTAL_ASSETS,
                )

                # 计算市值和仓位占比
                market_value = shares * current_price
                weight = float(market_value / A_TOTAL_ASSETS * 100)

                print(f"✅ {symbol} - {name}: {shares:,}股 @ ¥{avg_cost}, 市值¥{market_value:,.0f}, 仓位{weight:.2f}%")
                imported += 1

            except Exception as e:
                print(f"⚠️  导入失败 {symbol}: {e}")
                continue

        print(f"\n🎉 A 股持仓导入完成: {imported}/{len(A_SHARE_HOLDINGS)} 只")
        print(f"📊 A 股市场总资金: ¥{A_TOTAL_ASSETS:,.0f}")

    finally:
        db.close()


if __name__ == "__main__":
    import_a_shares()
