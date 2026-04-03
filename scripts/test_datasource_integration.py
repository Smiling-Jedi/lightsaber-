#!/usr/bin/env python3
"""
光剑系统数据源整合测试
验证新的数据源优先级配置
"""

import sys
sys.path.insert(0, '/Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber')

print("=" * 70)
print("光剑系统数据源整合测试")
print("=" * 70)

# 1. 测试账户数据（富途OpenD）
print("\n【测试1】账户数据 - 富途OpenD")
print("-" * 70)

try:
    from app.services.futu_sync_service import is_opend_available
    if is_opend_available():
        print("✅ 富途OpenD 可用")
        print("   - 持仓同步: 港股/美股/货币基金")
        print("   - 现金查询: HK_CASH / US_CASH")
    else:
        print("⚠️ 富途OpenD 未启动（启动命令: start_opend）")
except Exception as e:
    print(f"❌ 富途OpenD 检查失败: {e}")

# 2. 测试实时股价（聚合源）
print("\n【测试2】实时股价 - 聚合数据源")
print("-" * 70)

try:
    from app.data_sources.aggregated_source import AggregatedPriceSource
    source = AggregatedPriceSource()

    test_stocks = [
        ("A:300274", "阳光电源(A股)"),
        ("HK:00700", "腾讯控股(港股)"),
    ]

    for symbol, name in test_stocks:
        try:
            price = source.get_price(symbol)
            print(f"✅ {name}: {price.current_price} ({price.source})")
        except Exception as e:
            print(f"⚠️ {name}: {e}")
except Exception as e:
    print(f"❌ 聚合数据源初始化失败: {e}")

# 3. 测试基本面数据（iFinD）
print("\n【测试3】基本面数据 - 同花顺iFinD")
print("-" * 70)

try:
    from app.data_sources.ifind_source import iFinDSource
    ifind = iFinDSource()

    # 测试ROE查询
    result = ifind.get_financials('0700.HK', '腾讯控股', ['ROE'], years=3)
    if result['success']:
        print("✅ iFinD 财务数据查询成功")
    else:
        print(f"⚠️ iFinD 查询失败: {result.get('error')}")

    # 测试估值查询
    result = ifind.get_valuation('300274.SZ', '阳光电源')
    if result['success']:
        print("✅ iFinD 估值数据查询成功")
    else:
        print(f"⚠️ iFinD 估值查询失败: {result.get('error')}")

except Exception as e:
    print(f"❌ iFinD 初始化失败: {e}")
    print("   请检查环境变量 IFIND_MCP_TOKEN 是否设置")

# 4. 汇总
print("\n" + "=" * 70)
print("测试完成")
print("=" * 70)
print("""
数据源优先级配置:
- 账户数据(持仓/现金): 富途OpenD (唯一来源)
- 实时股价: iFinD > 富途 > Tushare/Yahoo
- 基本面数据: iFinD (首选)
- 宏观数据: iFinD EDB (首选)

详细文档: docs/数据源优先级配置.md
""")
