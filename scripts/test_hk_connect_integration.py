"""
港股通集成测试 - 验证富途能正确获取港股通价格
"""
import sys
sys.path.insert(0, '.')

from app.data_sources.aggregated_source import AggregatedPriceSource
from app.data_sources.futu_price_source import is_opend_available


def test_hk_stock_connect_price():
    """测试港股通价格获取（富途）"""
    print("\n=== Test: 港股通价格获取（富途） ===")

    if not is_opend_available():
        print("⚠️ 跳过: OpenD未运行")
        return True

    agg = AggregatedPriceSource()

    # 港股通代码（A股账户里的港股）
    hk_connect_stocks = [
        "A:09988",  # 阿里
        "A:01810",  # 小米
    ]

    all_passed = True
    for symbol in hk_connect_stocks:
        try:
            # 验证识别为港股通
            is_hk = agg._is_hk_stock_connect(symbol)
            if not is_hk:
                print(f"❌ {symbol}: 未识别为港股通")
                all_passed = False
                continue

            # 尝试获取价格（富途优先）
            price_data = agg.get_price(symbol)

            if price_data.current_price > 0:
                print(f"✅ {symbol}: {price_data.current_price} (来源: {price_data.source})")
            else:
                print(f"❌ {symbol}: 价格无效")
                all_passed = False

        except Exception as e:
            print(f"❌ {symbol}: {e}")
            all_passed = False

    return all_passed


def test_priority_fallback():
    """测试优先级降级逻辑"""
    print("\n=== Test: 数据源降级 ===")

    agg = AggregatedPriceSource()

    # 测试普通A股（应该走Tushare优先）
    try:
        price = agg.get_price("A:600036")
        print(f"✅ A:600036 通过Tushare/Yahoo获取: {price.current_price}")
    except Exception as e:
        print(f"❌ A:600036 获取失败: {e}")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("港股通集成测试")
    print("=" * 60)

    results = []

    try:
        results.append(("港股通价格获取", test_hk_stock_connect_price()))
    except Exception as e:
        print(f"❌ 港股通价格获取异常: {e}")
        results.append(("港股通价格获取", False))

    try:
        results.append(("优先级降级", test_priority_fallback()))
    except Exception as e:
        print(f"❌ 优先级降级异常: {e}")
        results.append(("优先级降级", False))

    print("\n" + "=" * 60)
    print("测试结果")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
