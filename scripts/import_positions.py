#!/usr/bin/env python3
"""
持仓 CSV 导入脚本
支持从券商导出的 CSV 文件导入持仓数据

用法:
    python scripts/import_positions.py path/to/positions.csv --market US --fund 1000000
"""
import argparse
import csv
import sys
from decimal import Decimal
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.services.position_service import PositionService


def parse_args():
    parser = argparse.ArgumentParser(description="导入持仓 CSV 文件")
    parser.add_argument("csv_file", help="CSV 文件路径")
    parser.add_argument("--market", default="US", choices=["HK", "US", "A"],
                        help="市场代码 (默认: US)")
    parser.add_argument("--fund", type=float, default=1000000,
                        help="该市场总资金，用于计算仓位占比 (默认: 1000000)")
    parser.add_argument("--currency", default="USD",
                        help="币种 (默认: USD)")
    return parser.parse_args()


def detect_csv_format(headers):
    """检测 CSV 格式（支持中英文表头）"""
    # 常见的列名映射
    mappings = {
        "代码": ["代码", "Code", "Symbol", "股票代码"],
        "名称": ["名称", "Name", "股票名称"],
        "持有数量": ["持有数量", "Shares", "Quantity", "持仓数量"],
        "平均成本价": ["平均成本价", "Cost Price", "Avg Price", "成本价"],
        "现价": ["现价", "Current Price", "Price", "CurrentPrice"],
        "币种": ["币种", "Currency"],
    }

    result = {}
    for key, possible_names in mappings.items():
        for i, h in enumerate(headers):
            if h.strip() in possible_names:
                result[key] = i
                break

    return result


def import_csv(csv_path: str, market: str, currency: str, total_fund: Decimal):
    """导入 CSV 文件"""

    db = SessionLocal()
    try:
        service = PositionService(db)

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)

            col_map = detect_csv_format(headers)
            print(f"检测到列: {list(col_map.keys())}")

            if "代码" not in col_map or "持有数量" not in col_map:
                print("❌ 无法识别的 CSV 格式")
                print(f"表头: {headers}")
                return

            imported = 0
            for row in reader:
                if not row or not row[0].strip():
                    continue

                try:
                    code = row[col_map["代码"]].strip().strip('"')
                    name = row[col_map.get("名称", 1)].strip().strip('"') if "名称" in col_map else code
                    shares = int(float(row[col_map["持有数量"]].replace(",", "")))
                    avg_cost = Decimal(row[col_map["平均成本价"]].replace(",", ""))

                    # 尝试获取现价
                    current_price = None
                    if "现价" in col_map:
                        try:
                            current_price = Decimal(row[col_map["现价"]].replace(",", ""))
                        except:
                            pass

                    # 构建 symbol
                    symbol = f"{market}:{code}"

                    # 导入持仓
                    position = service.import_from_csv_row(
                        symbol=symbol,
                        name=name,
                        market=market,
                        currency=currency,
                        shares=shares,
                        avg_cost=avg_cost,
                        current_price=current_price,
                        market_total_fund=total_fund,
                    )

                    print(f"✅ {symbol} - {name}: {shares}股 @ {avg_cost}")
                    imported += 1

                except Exception as e:
                    print(f"⚠️  跳过行: {row[:3]}... - {e}")
                    continue

        print(f"\n🎉 导入完成: {imported} 只持仓")

    finally:
        db.close()


def main():
    args = parse_args()

    # 初始化数据库
    print("🗄️  初始化数据库...")
    init_db()

    # 导入 CSV
    print(f"📁 导入文件: {args.csv_file}")
    print(f"📊 市场: {args.market}, 资金: {args.fund} {args.currency}")

    import_csv(
        csv_path=args.csv_file,
        market=args.market,
        currency=args.currency,
        total_fund=Decimal(str(args.fund))
    )


if __name__ == "__main__":
    main()
