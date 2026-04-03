#!/usr/bin/env python3
"""
同花顺 iFinD MCP - 港股/美股数据测试
测试数据覆盖范围和历史深度
"""

import sys
sys.path.insert(0, '/Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber')

from services.ifind_skill import call
import json


def test_stock_info(market, name, code):
    """测试获取股票基本信息"""
    print(f"\n{'='*60}")
    print(f"【{market}】{name} ({code}) - 基本信息")
    print('='*60)

    query = f"{name}上市时间、所属行业、主营业务"
    result = call("stock", "get_stock_info", {"query": query})

    if result['ok']:
        content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
        print(f"✅ 成功")
        # 提取关键信息展示
        if 'answer' in content:
            data = json.loads(content)
            print(f"数据: {data.get('data', {}).get('answer', content[:300])}")
        else:
            print(f"数据: {content[:500]}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")
    return result['ok']


def test_financials(market, name, code):
    """测试获取财务数据"""
    print(f"\n{'='*60}")
    print(f"【{market}】{name} ({code}) - 最新财务数据")
    print('='*60)

    query = f"{name}最近财年营业收入、净利润、ROE"
    result = call("stock", "get_stock_financials", {"query": query})

    if result['ok']:
        content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
        print(f"✅ 成功")
        try:
            data = json.loads(content)
            answer = data.get('data', {}).get('answer', '')
            print(f"财务数据:\n{answer[:800]}")
        except:
            print(f"数据: {content[:500]}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")
    return result['ok']


def test_historical_depth(market, name, code):
    """测试历史数据深度"""
    print(f"\n{'='*60}")
    print(f"【{market}】{name} ({code}) - 历史数据深度测试")
    print('='*60)

    # 测试1: 能拉多久的股价历史
    print("\n📈 测试1: 月收盘价历史范围")
    query = f"{name}近10年月收盘价"
    result = call("stock", "get_stock_performance", {"query": query})

    if result['ok']:
        content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
        try:
            data = json.loads(content)
            answer = data.get('data', {}).get('answer', '')
            # 统计行数估算数据点
            lines = answer.split('\n')
            data_lines = [l for l in lines if '|' in l and '证券代码' not in l and '---' not in l]
            print(f"✅ 成功 - 获取到约 {len(data_lines)} 个月度数据点")
            if data_lines:
                print(f"最早数据: {data_lines[-1] if len(data_lines) > 1 else data_lines[0]}")
                print(f"最新数据: {data_lines[0]}")
        except Exception as e:
            print(f"数据解析问题: {e}")
            print(f"原始: {content[:300]}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")

    # 测试2: 历史财报年份
    print("\n📊 测试2: 历史财报年份范围")
    query = f"{name}近15年每年的净利润"
    result = call("stock", "get_stock_financials", {"query": query})

    if result['ok']:
        content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
        try:
            data = json.loads(content)
            answer = data.get('data', {}).get('answer', '')
            lines = answer.split('\n')
            data_lines = [l for l in lines if '|' in l and '证券代码' not in l and '---' not in l]
            print(f"✅ 成功 - 获取到 {len(data_lines)} 个年度财报数据")
            if len(data_lines) >= 2:
                print(f"年份范围: {data_lines[-1].split('|')[2] if len(data_lines[-1].split('|')) > 2 else 'N/A'} "
                      f"至 {data_lines[0].split('|')[2] if len(data_lines[0].split('|')) > 2 else 'N/A'}")
        except Exception as e:
            print(f"数据: {content[:500]}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_valuation(market, name, code):
    """测试估值数据"""
    print(f"\n{'='*60}")
    print(f"【{market}】{name} ({code}) - 估值数据")
    print('='*60)

    query = f"{name}当前PE、PB估值"
    result = call("stock", "get_stock_financials", {"query": query})

    if result['ok']:
        content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
        print(f"✅ 成功")
        try:
            data = json.loads(content)
            answer = data.get('data', {}).get('answer', '')
            print(f"估值数据:\n{answer}")
        except:
            print(f"数据: {content[:500]}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_shareholders(market, name, code):
    """测试股东数据"""
    print(f"\n{'='*60}")
    print(f"【{market}】{name} ({code}) - 股东结构")
    print('='*60)

    query = f"{name}前10大股东"
    result = call("stock", "get_stock_shareholders", {"query": query})

    if result['ok']:
        content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
        print(f"✅ 成功")
        try:
            data = json.loads(content)
            answer = data.get('data', {}).get('answer', '')
            print(f"股东数据:\n{answer[:1000]}")
        except:
            print(f"数据: {content[:500]}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_risk_indicators(market, name, code):
    """测试风险指标"""
    print(f"\n{'='*60}")
    print(f"【{market}】{name} ({code}) - 风险指标(Beta/波动率)")
    print('='*60)

    query = f"{name}近一年的Beta系数和年化波动率"
    result = call("stock", "get_risk_indicators", {"query": query})

    if result['ok']:
        content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
        print(f"✅ 成功")
        try:
            data = json.loads(content)
            answer = data.get('data', {}).get('answer', '')
            print(f"风险指标:\n{answer}")
        except:
            print(f"数据: {content[:500]}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")


def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("同花顺 iFinD MCP - 港股/美股数据覆盖测试")
    print("="*60)

    # 测试标的
    test_stocks = [
        ("港股", "腾讯控股", "00700"),
        ("港股", "阿里巴巴-SW", "09988"),
        ("美股", "苹果", "AAPL"),
        ("美股", "英伟达", "NVDA"),
    ]

    results = {}

    for market, name, code in test_stocks:
        print(f"\n\n{'#'*60}")
        print(f"# 开始测试: {market} - {name} ({code})")
        print('#'*60)

        results[f"{market}_{code}"] = {
            "basic": test_stock_info(market, name, code),
            "financials": test_financials(market, name, code),
            "valuation": test_valuation(market, name, code),
        }

        # 历史深度测试（只测前两个，避免太慢）
        if market == "港股" and code == "00700":
            test_historical_depth(market, name, code)
            test_shareholders(market, name, code)
            test_risk_indicators(market, name, code)

    # 汇总
    print("\n\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    for key, tests in results.items():
        print(f"\n{key}:")
        for test_name, success in tests.items():
            status = "✅" if success else "❌"
            print(f"  {status} {test_name}")

    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == "__main__":
    main()
