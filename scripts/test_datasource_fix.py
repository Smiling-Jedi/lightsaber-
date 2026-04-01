"""
数据源适配器测试套件
测试内容：
1. FutuAdapterSource - PriceData构造
2. 港股通识别逻辑
3. Tushare ETF价格获取
4. 聚合数据源优先级
"""
import sys
sys.path.insert(0, '.')

from decimal import Decimal
from app.data_sources.base import PriceData
from app.data_sources.aggregated_source import AggregatedPriceSource, FutuAdapterSource
from app.data_sources.tushare_source import TushareSource
from config.settings import TUSHARE_TOKEN


def test_price_data_construction():
    """测试PriceData构造 - 验证所有必需字段"""
    print("\n=== Test: PriceData构造 ===")
    try:
        # 正确的构造
        pd = PriceData(
            symbol="HK:00700",
            market="HK",
            current_price=Decimal("493.4"),
            open_price=Decimal("490.0"),
            high_price=Decimal("495.0"),
            low_price=Decimal("488.0"),
            volume=1000000,
            source="test",
        )
        assert pd.symbol == "HK:00700"
        assert pd.market == "HK"
        assert pd.current_price == Decimal("493.4")
        print("✅ PriceData构造正确")
        return True
    except Exception as e:
        print(f"❌ PriceData构造失败: {e}")
        return False


def test_hk_stock_connect_recognition():
    """测试港股通识别逻辑"""
    print("\n=== Test: 港股通识别 ===")
    agg = AggregatedPriceSource()

    test_cases = [
        # (symbol, expected_is_hk_connect)
        ("A:09988", True),   # 阿里 - 港股通
        ("A:01810", True),   # 小米 - 港股通
        ("A:00700", True),   # 腾讯 - 港股通
        ("A:600036", False), # 招商银行 - A股
        ("A:000001", False), # 平安银行 - A股
        ("A:300750", False), # 宁德时代 - A股
        ("A:159949", False), # 创业板50ETF - ETF
        ("HK:00700", False), # 纯港股
        ("US:AAPL", False),  # 美股
    ]

    all_passed = True
    for symbol, expected in test_cases:
        result = agg._is_hk_stock_connect(symbol)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_passed = False
        print(f"{status} {symbol}: {'港股通' if result else '非港股通'} (预期: {'港股通' if expected else '非港股通'})")

    return all_passed


def test_tushare_etf_price():
    """测试Tushare ETF价格获取"""
    print("\n=== Test: Tushare ETF价格 ===")
    if not TUSHARE_TOKEN:
        print("⚠️ 跳过: 未配置TUSHARE_TOKEN")
        return True

    tushare = TushareSource(token=TUSHARE_TOKEN)

    test_cases = [
        "A:159949",  # 创业板50ETF
        "A:512010",  # 医药ETF
        "A:562500",  # 机器人ETF
    ]

    all_passed = True
    for symbol in test_cases:
        try:
            price_data = tushare.get_price(symbol)
            if price_data.current_price > 0:
                print(f"✅ {symbol}: {price_data.current_price}")
            else:
                print(f"❌ {symbol}: 价格无效 {price_data.current_price}")
                all_passed = False
        except Exception as e:
            print(f"❌ {symbol}: {e}")
            all_passed = False

    return all_passed


def test_tushare_normal_stock():
    """测试Tushare普通A股价格获取"""
    print("\n=== Test: Tushare普通A股 ===")
    if not TUSHARE_TOKEN:
        print("⚠️ 跳过: 未配置TUSHARE_TOKEN")
        return True

    tushare = TushareSource(token=TUSHARE_TOKEN)

    test_cases = [
        "A:600036",  # 招商银行
        "A:002594",  # 比亚迪
        "A:300750",  # 宁德时代
    ]

    all_passed = True
    for symbol in test_cases:
        try:
            price_data = tushare.get_price(symbol)
            if price_data.current_price > 0:
                print(f"✅ {symbol}: {price_data.current_price}")
            else:
                print(f"❌ {symbol}: 价格无效")
                all_passed = False
        except Exception as e:
            print(f"❌ {symbol}: {e}")
            all_passed = False

    return all_passed


def test_futu_adapter_mock():
    """测试FutuAdapterSource - 模拟数据"""
    print("\n=== Test: FutuAdapterSource (Mock) ===")
    # 由于需要OpenD连接，这里只测试代码格式转换
    futu = FutuAdapterSource()

    # 测试代码转换
    assert futu._to_futu_code("HK:00700") == "HK.00700"
    assert futu._to_futu_code("US:AAPL") == "US.AAPL"
    assert futu._to_futu_code("A:600036") == "A.600036"

    assert futu._to_internal_code("HK.00700") == "HK:00700"
    assert futu._to_internal_code("US.AAPL") == "US:AAPL"

    print("✅ 代码格式转换正确")
    return True


def test_data_source_priority():
    """测试数据源优先级配置"""
    print("\n=== Test: 数据源优先级 ===")
    agg = AggregatedPriceSource()

    # 检查各市场优先级
    hk_priority = [s.__class__.__name__ for s in agg.priority["HK"]]
    us_priority = [s.__class__.__name__ for s in agg.priority["US"]]
    a_priority = [s.__class__.__name__ for s in agg.priority["A"]]

    print(f"HK市场优先级: {hk_priority}")
    print(f"US市场优先级: {us_priority}")
    print(f"A股市场优先级: {a_priority}")

    # 验证A股Tushare优先
    assert a_priority[0] == "TushareSource", "A股应该是Tushare优先"

    # 验证港美股富途优先
    assert hk_priority[0] == "FutuAdapterSource", "港股应该是富途优先"
    assert us_priority[0] == "FutuAdapterSource", "美股应该是富途优先"

    print("✅ 数据源优先级配置正确")
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("数据源适配器测试套件")
    print("=" * 60)

    tests = [
        test_price_data_construction,
        test_hk_stock_connect_recognition,
        test_futu_adapter_mock,
        test_data_source_priority,
        test_tushare_normal_stock,
        test_tushare_etf_price,
    ]

    results = []
    for test in tests:
        try:
            passed = test()
            results.append((test.__name__, passed))
        except Exception as e:
            print(f"❌ {test.__name__} 异常: {e}")
            results.append((test.__name__, False))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    passed_count = sum(1 for _, p in results if p)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\n总计: {passed_count}/{len(results)} 通过")
    return passed_count == len(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
