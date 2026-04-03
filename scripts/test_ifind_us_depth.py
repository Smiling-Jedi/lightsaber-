#!/usr/bin/env python3
"""
同花顺 iFinD MCP - 美股数据深度测试
测试字段广度和历史深度
"""

import sys
sys.path.insert(0, '/Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber')

from services.ifind_skill import call
import json


def test_us_stock_basic(symbol, name):
    """测试美股基本资料"""
    print(f"\n{'='*70}")
    print(f"【美股】{name} ({symbol}) - 基本资料测试")
    print('='*70)

    queries = [
        ("上市信息", f"{name}上市时间、上市交易所、所属行业"),
        ("公司信息", f"{name}公司简介、主营业务、员工人数"),
        ("股本信息", f"{name}总股本、流通股、市值"),
    ]

    for test_name, query in queries:
        print(f"\n📋 {test_name}: {query}")
        result = call("stock", "get_stock_info", {"query": query})

        if result['ok']:
            content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
            try:
                data = json.loads(content)
                answer = data.get('data', {}).get('answer', '')
                lines = [l for l in answer.split('\n') if '|' in l and '---' not in l]
                print(f"✅ 成功 - 返回 {len(lines)} 行数据")
                if lines[:3]:
                    for line in lines[:3]:
                        print(f"   {line}")
            except Exception as e:
                print(f"⚠️ 解析问题: {e}")
                print(f"   原始: {content[:200]}")
        else:
            print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_us_financials(symbol, name):
    """测试美股财报数据深度"""
    print(f"\n{'='*70}")
    print(f"【美股】{name} ({symbol}) - 财报数据深度测试")
    print('='*70)

    # 测试不同年份的财报
    years = ["2024", "2023", "2022", "2021", "2020", "2015", "2010", "2005"]

    print("\n📊 测试历年净利润数据:")
    for year in years:
        query = f"{name}{year}年净利润"
        result = call("stock", "get_stock_financials", {"query": query})

        if result['ok']:
            content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
            try:
                data = json.loads(content)
                answer = data.get('data', {}).get('answer', '')
                # 检查是否有实际数据
                if '|' in answer and len(answer.split('|')) > 3:
                    print(f"  ✅ {year}年: 有数据")
                else:
                    print(f"  ⚠️ {year}年: 数据为空")
            except:
                print(f"  ⚠️ {year}年: 解析失败")
        else:
            print(f"  ❌ {year}年: 查询失败 {result.get('error', '')}")


def test_us_valuation(symbol, name):
    """测试美股估值数据"""
    print(f"\n{'='*70}")
    print(f"【美股】{name} ({symbol}) - 估值数据测试")
    print('='*70)

    queries = [
        ("当前估值", f"{name}当前PE、PB、PS"),
        ("历史PE", f"{name}近5年PE走势"),
        ("历史PB", f"{name}近5年PB走势"),
    ]

    for test_name, query in queries:
        print(f"\n📈 {test_name}: {query}")
        result = call("stock", "get_stock_financials", {"query": query})

        if result['ok']:
            content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
            try:
                data = json.loads(content)
                answer = data.get('data', {}).get('answer', '')
                lines = [l for l in answer.split('\n') if '|' in l and '---' not in l]
                print(f"✅ 成功 - 返回 {len(lines)} 行数据")
                if lines:
                    print(f"   最新: {lines[0]}")
            except Exception as e:
                print(f"⚠️ 解析问题: {e}")
        else:
            print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_us_historical_price(symbol, name):
    """测试美股历史行情深度"""
    print(f"\n{'='*70}")
    print(f"【美股】{name} ({symbol}) - 历史行情深度测试")
    print('='*70)

    periods = [
        ("1个月", f"{name}近1个月日收盘价"),
        ("6个月", f"{name}近6个月日收盘价"),
        ("1年", f"{name}近1年月收盘价"),
        ("5年", f"{name}近5年月收盘价"),
        ("10年", f"{name}近10年月收盘价"),
        ("最大", f"{name}上市至今月收盘价"),
    ]

    for period_name, query in periods:
        print(f"\n📊 {period_name}: {query}")
        result = call("stock", "get_stock_performance", {"query": query})

        if result['ok']:
            content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
            try:
                data = json.loads(content)
                answer = data.get('data', {}).get('answer', '')
                lines = [l for l in answer.split('\n') if '|' in l and '---' not in l and '证券代码' not in l]
                print(f"✅ 成功 - 返回 {len(lines)} 个数据点")
                if len(lines) > 1:
                    print(f"   最早: {lines[-1]}")
                    print(f"   最新: {lines[0]}")
            except Exception as e:
                print(f"⚠️ 解析问题: {e}")
        else:
            print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_us_shareholders(symbol, name):
    """测试美股股东数据"""
    print(f"\n{'='*70}")
    print(f"【美股】{name} ({symbol}) - 股东结构测试")
    print('='*70)

    queries = [
        ("大股东", f"{name}前10大股东"),
        ("机构持股", f"{name}机构持股比例"),
        (" insider持股", f"{name}内部人持股"),
    ]

    for test_name, query in queries:
        print(f"\n👥 {test_name}: {query}")
        result = call("stock", "get_stock_shareholders", {"query": query})

        if result['ok']:
            content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
            try:
                data = json.loads(content)
                answer = data.get('data', {}).get('answer', '')
                has_data = '|' in answer and len(answer) > 100
                print(f"✅ 成功" if has_data else f"⚠️ 返回空数据")
                if has_data:
                    print(f"   片段: {answer[:200]}...")
            except Exception as e:
                print(f"⚠️ 解析问题: {e}")
        else:
            print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_us_risk(symbol, name):
    """测试美股风险指标"""
    print(f"\n{'='*70}")
    print(f"【美股】{name} ({symbol}) - 风险指标测试")
    print('='*70)

    queries = [
        ("Beta", f"{name}Beta系数"),
        ("波动率", f"{name}年化波动率"),
        ("夏普比率", f"{name}夏普比率"),
        ("VaR", f"{name}风险价值VaR"),
    ]

    for test_name, query in queries:
        print(f"\n⚡ {test_name}: {query}")
        result = call("stock", "get_risk_indicators", {"query": query})

        if result['ok']:
            content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
            try:
                data = json.loads(content)
                answer = data.get('data', {}).get('answer', '')
                has_data = '|' in answer and len(answer) > 100
                print(f"✅ 成功" if has_data else f"⚠️ 返回空数据")
                if has_data:
                    print(f"   片段: {answer[:200]}...")
            except Exception as e:
                print(f"⚠️ 解析问题: {e}")
        else:
            print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_us_stock_screening():
    """测试美股智能选股"""
    print(f"\n{'='*70}")
    print(f"【美股】智能选股功能测试")
    print('='*70)

    queries = [
        "美股科技行业市值排名前10",
        "美股PE小于20的成长股",
        "美股近一年涨幅超过50%的股票",
    ]

    for query in queries:
        print(f"\n🔍 {query}")
        result = call("stock", "search_stocks", {"query": query})

        if result['ok']:
            content = result['data'].get('result', {}).get('content', [{}])[0].get('text', '')
            try:
                data = json.loads(content)
                answer = data.get('data', {}).get('answer', '')
                lines = [l for l in answer.split('\n') if '|' in l and '---' not in l]
                print(f"✅ 成功 - 返回 {len(lines)} 只股票")
                if lines[:3]:
                    for line in lines[:3]:
                        print(f"   {line}")
            except Exception as e:
                print(f"⚠️ 解析问题: {e}")
        else:
            print(f"❌ 失败: {result.get('error', '未知错误')}")


def main():
    """主测试函数"""
    print("\n" + "="*70)
    print("同花顺 iFinD MCP - 美股数据深度测试")
    print("="*70)

    # 测试多个美股标的
    us_stocks = [
        ("AAPL", "苹果"),
        ("NVDA", "英伟达"),
        ("MSFT", "微软"),
    ]

    for symbol, name in us_stocks:
        print(f"\n\n{'#'*70}")
        print(f"# 开始测试: {name} ({symbol})")
        print('#'*70)

        test_us_stock_basic(symbol, name)
        test_us_financials(symbol, name)
        test_us_valuation(symbol, name)
        test_us_historical_price(symbol, name)
        test_us_shareholders(symbol, name)
        test_us_risk(symbol, name)

    # 选股功能测试
    test_us_stock_screening()

    print("\n\n" + "="*70)
    print("美股数据深度测试完成")
    print("="*70)


if __name__ == "__main__":
    main()
