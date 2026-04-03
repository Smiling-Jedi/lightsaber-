"""
同花顺 iFinD MCP 数据服务

使用方法:
    from services.ifind_skill import call

    result = call("stock", "get_stock_financials", {"query": "阳光电源2025年ROE"})
"""

from .call import call, list_tools

__all__ = ["call", "list_tools"]
