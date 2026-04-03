#!/usr/bin/env python3
"""
同花顺 iFinD MCP 数据服务封装
官方 Skill 包 - 适配光剑系统（环境变量版）

使用方法:
    from services.ifind_skill.call import call

    # 查询股票ROE
    result = call("stock", "get_stock_financials", {"query": "阳光电源2025年ROE"})

    # 智能选股
    result = call("stock", "search_stocks", {"query": "汽车零部件行业市值大于1000亿"})

服务类型:
    - stock: 股票数据
    - fund: 基金数据
    - edb: 宏观经济/行业数据
    - news: 新闻公告
"""

import json
import os
import requests
import urllib3

# 禁用 SSL 警告（同花顺证书问题）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 从环境变量读取 Token
AUTH_TOKEN = os.getenv("IFIND_MCP_TOKEN")
if not AUTH_TOKEN:
    raise ValueError(
        "环境变量 IFIND_MCP_TOKEN 未设置\n"
        "请在 ~/.claude/settings.json 或 ~/.zshrc 中设置:\n"
        "export IFIND_MCP_TOKEN='your_token_here'"
    )

BASE = "https://api-mcp.51ifind.com:8643/ds-mcp-servers"
SERVERS = {
    "stock": f"{BASE}/hexin-ifind-ds-stock-mcp",
    "fund": f"{BASE}/hexin-ifind-ds-fund-mcp",
    "edb": f"{BASE}/hexin-ifind-ds-edb-mcp",
    "news": f"{BASE}/hexin-ifind-ds-news-mcp",
}

_sessions = {}
_req_ids = {}


def _next_id(t):
    _req_ids[t] = _req_ids.get(t, 0) + 1
    return _req_ids[t]


def _headers(t=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": AUTH_TOKEN,
    }
    if t in _sessions:
        h["Mcp-Session-Id"] = _sessions[t]
    return h


def _post(t, payload, timeout=60):
    resp = requests.post(
        SERVERS[t],
        json=payload,
        headers=_headers(t),
        verify=False,
        timeout=timeout,
    )
    data = None
    if resp.text.strip():
        try:
            data = resp.json()
        except Exception:
            data = resp.text
    return resp, data


def _init(t):
    if t in _sessions:
        return

    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(t),
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "lightsaber-client", "version": "1.0.0"},
        },
    }

    resp, data = _post(t, payload, timeout=30)
    resp.raise_for_status()

    session_id = resp.headers.get("Mcp-Session-Id")
    if not session_id:
        raise RuntimeError(f"initialize 成功但未返回 Mcp-Session-Id: {data}")

    _sessions[t] = session_id

    notify = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    requests.post(
        SERVERS[t],
        json=notify,
        headers=_headers(t),
        verify=False,
        timeout=10,
    )


def call(server_type, tool_name, params):
    """
    发起金融数据请求

    Args:
        server_type: 服务类型 - "stock"/"fund"/"edb"/"news"
        tool_name: 工具名称，如 "get_stock_financials"
        params: 请求参数字典，如 {"query": "阳光电源ROE"}

    Returns:
        {
            "ok": True/False,
            "status_code": HTTP状态码,
            "data": 成功时返回数据,
            "error": 失败时返回错误信息,
            "raw": 原始响应
        }
    """
    if server_type not in SERVERS:
        raise ValueError(f"unknown server_type: {server_type}")

    _init(server_type)

    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(server_type),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params,
        },
    }

    resp, data = _post(server_type, payload)

    if isinstance(data, dict) and "error" in data:
        return {
            "ok": False,
            "status_code": resp.status_code,
            "error": data["error"],
            "raw": data,
        }

    resp.raise_for_status()
    return {
        "ok": True,
        "status_code": resp.status_code,
        "data": data,
    }


def list_tools(server_type):
    """
    列出指定服务类型的所有可用工具

    Args:
        server_type: 服务类型 - "stock"/"fund"/"edb"/"news"

    Returns:
        工具列表
    """
    if server_type not in SERVERS:
        raise ValueError(f"unknown server_type: {server_type}")

    _init(server_type)

    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(server_type),
        "method": "tools/list",
        "params": {},
    }

    resp, data = _post(server_type, payload)

    if isinstance(data, dict) and "error" in data:
        return {
            "ok": False,
            "status_code": resp.status_code,
            "error": data["error"],
            "raw": data,
        }

    resp.raise_for_status()

    if isinstance(data, dict) and "result" in data:
        tools = data["result"].get("tools", [])
        for i, tool in enumerate(tools, 1):
            print(f"{i}. {tool.get('name', 'N/A')}: {tool.get('description', '无')[:50]}...")

    return {
        "ok": True,
        "status_code": resp.status_code,
        "data": data,
    }


if __name__ == "__main__":
    # 测试示例
    print("=" * 60)
    print("同花顺 iFinD MCP 技能测试")
    print("=" * 60)

    # 测试1: 获取股票ROE
    print("\n测试1: 获取阳光电源ROE")
    result = call("stock", "get_stock_financials", {"query": "阳光电源2025年ROE"})
    if result["ok"]:
        print(f"✅ 成功: {result['data']}")
    else:
        print(f"❌ 失败: {result['error']}")

    # 测试2: 智能选股
    print("\n测试2: 选股 - 汽车零部件行业市值前5")
    result = call("stock", "search_stocks", {"query": "汽车零部件行业市值排名前5的股票"})
    if result["ok"]:
        print(f"✅ 成功")
    else:
        print(f"❌ 失败: {result['error']}")
