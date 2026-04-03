#!/usr/bin/env python3
"""
导入 A 股持仓数据（持仓数量 + 成本价）

⚠️ 说明：
- 富途OpenD API不支持A股持仓同步，因此A股的持仓数量和成本价需通过本脚本手动录入
- A股的当前价格会自动从Tushare/EastMoney等接口获取，无需在此设置
- 使用方法：根据截图更新A_SHARE_HOLDINGS列表，然后运行本脚本
"""
import sys
from decimal import Decimal
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.services.position_service import PositionService

# A 股持仓数据（更新于 2026-04-03）
# 注意：A股持仓必须通过截图/口头告知更新，无API自动同步
# 总资产约 465万 RMB（仅A股持仓部分），用于计算仓位占比
A_SHARE_HOLDINGS = [
    # 代码, 名称, 持仓数量, 成本价, 现价
    ("512010", "医药ETF易方达", 2484800, Decimal("0.3962"), Decimal("0.3570")),
    ("562500", "机器人ETF华夏", 700000, Decimal("0.9573"), Decimal("0.9200")),
    ("600030", "中信证券", 3800, Decimal("28.9712"), Decimal("24.3600")),
    ("600036", "招商银行", 2500, Decimal("39.3939"), Decimal("39.2500")),
    ("601166", "兴业银行", 5500, Decimal("18.7165"), Decimal("18.7200")),
    ("601328", "交通银行", 15000, Decimal("7.0953"), Decimal("6.8200")),
    ("002594", "比亚迪", 15000, Decimal("87.9810"), Decimal("106.6400")),
    ("300274", "阳光电源", 3500, Decimal("155.9780"), Decimal("164.6800")),
    ("300750", "宁德时代", 1000, Decimal("118.3013"), Decimal("396.9900")),
    ("159949", "创业板50ETF", 60000, Decimal("1.5396"), Decimal("1.0200")),
    ("01810", "小米集团-W", 3000, Decimal("32.3424"), Decimal("58.5000")),
    ("09988", "阿里巴巴-W", 1000, Decimal("123.6066"), Decimal("125.0000")),
]

# A 股总资产（用于计算仓位占比）
A_TOTAL_ASSETS = Decimal("4650000")  # 约 465 万 RMB


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
