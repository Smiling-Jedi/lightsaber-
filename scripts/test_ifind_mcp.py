#!/usr/bin/env python3
"""
同花顺 iFinD MCP 数据接口测试脚本
用于验证 MCP 连接和数据获取
"""

import os
import json
import requests
from datetime import datetime

# MCP 服务配置
MCP_SERVERS = {
    "stock": {
        "url": "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp",
        "description": "股票数据服务"
    },
    "fund": {
        "url": "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-fund-mcp",
        "description": "基金数据服务"
    },
    "edb": {
        "url": "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-edb-mcp",
        "description": "经济数据服务"
    },
    "news": {
        "url": "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-news-mcp",
        "description": "新闻数据服务"
    }
}


def get_auth_token():
    """从环境变量获取认证 Token"""
    token = os.getenv("IFIND_MCP_TOKEN")
    if not token:
        raise ValueError("环境变量 IFIND_MCP_TOKEN 未设置")
    return token


def test_mcp_connection(server_name, server_config):
    """测试单个 MCP 服务器的连接"""
    print(f"\n{'='*60}")
    print(f"测试服务: {server_name} - {server_config['description']}")
    print(f"URL: {server_config['url']}")
    print(f"{'='*60}")

    token = get_auth_token()
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        # 发送一个简单的 POST 请求到 MCP 端点
        # MCP 协议通常需要发送特定的 JSON-RPC 格式请求
        response = requests.post(
            server_config['url'],
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {},
                "id": 1
            },
            timeout=10
        )

        print(f"状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")

        if response.status_code == 200:
            try:
                data = response.json()
                print(f"响应数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
                return True
            except json.JSONDecodeError:
                print(f"原始响应: {response.text[:500]}")
                return False
        else:
            print(f"错误响应: {response.text[:500]}")
            return False

    except requests.exceptions.Timeout:
        print("❌ 连接超时")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 连接错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def list_available_tools(server_name="stock"):
    """列出 MCP 服务器上可用的工具"""
    print(f"\n{'='*60}")
    print(f"获取 {server_name} 服务的可用工具列表")
    print(f"{'='*60}")

    token = get_auth_token()
    server = MCP_SERVERS[server_name]

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    # 获取工具列表的请求
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": 3
    }

    try:
        response = requests.post(
            server['url'],
            headers=headers,
            json=payload,
            timeout=15
        )

        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if "result" in data and "tools" in data["result"]:
                tools = data["result"]["tools"]
                print(f"\n找到 {len(tools)} 个工具:\n")
                for i, tool in enumerate(tools, 1):
                    print(f"{i}. {tool.get('name', 'N/A')}")
                    print(f"   描述: {tool.get('description', '无')}")
                    if 'inputSchema' in tool:
                        print(f"   参数: {json.dumps(tool['inputSchema'], indent=2, ensure_ascii=False)}")
                    print()
                return tools
            else:
                print(f"响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
                return []
        else:
            print(f"错误: {response.text[:500]}")
            return []

    except Exception as e:
        print(f"❌ 获取工具列表失败: {e}")
        return []


def call_tool(server_name, tool_name, arguments):
    """调用指定的 MCP 工具"""
    print(f"\n{'='*60}")
    print(f"调用工具: {tool_name}")
    print(f"参数: {json.dumps(arguments, ensure_ascii=False)}")
    print(f"{'='*60}")

    token = get_auth_token()
    server = MCP_SERVERS[server_name]

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        },
        "id": 4
    }

    try:
        response = requests.post(
            server['url'],
            headers=headers,
            json=payload,
            timeout=15
        )

        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"结果:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
            return data
        else:
            print(f"错误: {response.text[:500]}")
            return None

    except Exception as e:
        print(f"❌ 调用失败: {e}")
        return None


def main():
    """主函数：运行所有测试"""
    print("\n" + "="*60)
    print(f"同花顺 iFinD MCP 接口测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # 检查环境变量
    try:
        token = get_auth_token()
        print(f"\n✅ Token 已配置 (长度: {len(token)})")
    except ValueError as e:
        print(f"\n❌ {e}")
        print("请设置环境变量: export IFIND_MCP_TOKEN='your_token_here'")
        return

    # 测试所有 MCP 服务连接
    results = {}
    for name, config in MCP_SERVERS.items():
        results[name] = test_mcp_connection(name, config)

    # 汇总结果
    print(f"\n{'='*60}")
    print("测试结果汇总")
    print("="*60)
    for name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{name:10} {status}")

    # 如果股票服务可用，获取可用工具列表
    if results.get("stock"):
        print("\n" + "="*60)
        print("获取股票服务的可用工具列表")
        print("="*60)
        tools = list_available_tools("stock")

        # 测试1: 获取股票摘要信息
        print(f"\n{'='*60}")
        print("测试1: 获取 300274 阳光电源 摘要信息")
        print(f"{'='*60}")
        call_tool("stock", "get_stock_summary", {"query": "阳光电源财务状况"})

        # 测试2: 获取多年历史财报数据
        print(f"\n{'='*60}")
        print("测试2: 获取阳光电源近10年历史ROE数据")
        print(f"{'='*60}")
        call_tool("stock", "get_stock_financials", {"query": "阳光电源2015年到2025年每年的ROE"})

        # 测试3: 获取历史行情数据（尽可能久远）
        print(f"\n{'='*60}")
        print("测试3: 获取阳光电源历史行情（看能拉多久）")
        print(f"{'='*60}")
        call_tool("stock", "get_stock_performance", {"query": "阳光电源上市至今的月收益率"})

        # 测试4: 获取完整财务报表
        print(f"\n{'='*60}")
        print("测试4: 获取阳光电源最新完整财务报表")
        print(f"{'='*60}")
        call_tool("stock", "get_stock_financials", {"query": "阳光电源2024年年报资产负债表、利润表、现金流量表"})

        # 测试5: 获取基本面历史数据
        print(f"\n{'='*60}")
        print("测试5: 获取阳光电源历史估值数据（PE/PB）")
        print(f"{'='*60}")
        call_tool("stock", "get_stock_financials", {"query": "阳光电源近5年每个季度的PE、PB估值"})

    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == "__main__":
    main()
