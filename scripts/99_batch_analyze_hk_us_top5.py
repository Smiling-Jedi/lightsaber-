"""
批量分析港美股前5只持仓的三周期形态

用法:
    cd lightsaber && source venv/bin/activate && python scripts/99_batch_analyze_hk_us_top5.py

范围: 港股前5只 + 美股前5只 = 10只 (+ 关注的额外标的)
按当前 positions 仓位占比排序（手动维护清单，避免每次跑全部持仓）
"""
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.core.database import SessionLocal
from app.services.pattern_analysis_service import PatternAnalysisService
from app.models.stock import Stock

# 港美股各前5只（按 mini 首页仓位占比排序）+ 额外关注标的
HK_US_TOP5_SYMBOLS = [
    # 港股前5
    "HK:00700",   # 腾讯控股 ~34%
    "HK:09988",   # 阿里巴巴-W ~17%
    "HK:00270",   # 粤海投资 ~7%
    "HK:06160",   # 百济神州 ~3.4%
    "HK:01276",   # 恒瑞医药 ~3.1%
    # 美股前5
    "US:TSLA",    # 特斯拉 ~0.9%
    "US:MSFT",    # 微软 ~0.7%
    "US:NVDA",    # 英伟达 ~0.6%
    "US:META",    # Meta ~0.5%
    "US:SOFI",    # SoFi ~0.3%
    # 额外关注（光模块产业链）
    "US:LITE",    # Lumentum
]


def main():
    print("=" * 60)
    print("批量分析港美股前5只 — 分周期独立分析")
    print("=" * 60)

    db = SessionLocal()
    try:
        service = PatternAnalysisService(db)

        total_calls = 0
        success_count = 0
        failed_symbols = []

        for symbol in HK_US_TOP5_SYMBOLS:
            stock = db.get(Stock, symbol)
            stock_name = stock.name if stock else symbol

            print(f"\n{'='*60}")
            print(f"分析: {stock_name} ({symbol})")
            print('='*60)

            try:
                results = service.analyze_single_stock(symbol, stock_name)

                if results and len(results) > 0:
                    for analysis in results:
                        print(f"  ✅ {analysis.period}: {analysis.pattern_name} ({analysis.pattern_state}) — {analysis.confidence}")
                    success_count += 1
                    total_calls += len(results)
                else:
                    print(f"  ❌ 分析失败")
                    failed_symbols.append(symbol)

            except Exception as e:
                print(f"  ❌ 异常: {e}")
                failed_symbols.append(symbol)

        print(f"\n{'='*60}")
        print("分析完成")
        print('='*60)
        print(f"成功: {success_count}/{len(HK_US_TOP5_SYMBOLS)} 只股票")
        print(f"LLM调用: {total_calls} 次")
        print(f"失败: {failed_symbols if failed_symbols else '无'}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
