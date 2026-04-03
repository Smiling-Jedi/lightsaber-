"""
同花顺 iFinD MCP 数据源适配器

用途：查询市场公开数据（股价、财报、基本面、宏观数据）

⚠️ 重要区分：
- iFinD 只能查询市场公开数据，不能获取你的个人账户数据
- 账户数据（持仓/现金）必须通过富途OpenD或你手动录入

适用场景：
- 查某只股票的历史ROE
- 查某只股票的PE/PB估值
- 查宏观经济指标
- 智能选股

不适用场景：
- 查你账户里有多少股腾讯（这是持仓同步，用富途）
- 查你的成本价（这是持仓同步，用富途）

详细配置：docs/数据源优先级配置.md
"""
import json
import logging
import os
from decimal import Decimal
from typing import List, Optional

from app.data_sources.base import BaseDataSource, DataSourceError
from services.ifind_skill import call

logger = logging.getLogger(__name__)


class iFinDSource:
    """
    同花顺 iFinD MCP 数据源
    适用于：基本面数据、历史行情、财报数据、宏观数据
    不适用于：实时股价（有延迟）、账户数据
    """

    def __init__(self):
        self.token = os.getenv("IFIND_MCP_TOKEN")
        if not self.token:
            logger.warning("环境变量 IFIND_MCP_TOKEN 未设置，iFinD 数据源不可用")

    def _is_available(self) -> bool:
        """检查 iFinD 是否可用"""
        return bool(self.token)

    def get_stock_summary(self, symbol: str, name: str) -> dict:
        """
        获取股票摘要信息（财务、估值、行情）

        Args:
            symbol: 股票代码（如 300274.SZ, 0700.HK, AAPL.O）
            name: 股票中文/英文名称

        Returns:
            dict: 包含财务、估值、行情摘要
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        result = call("stock", "get_stock_summary", {"query": f"{name}财务状况"})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_financials(self, symbol: str, name: str, metrics: List[str], years: int = 5) -> dict:
        """
        获取财务报表数据

        Args:
            symbol: 股票代码
            name: 股票名称
            metrics: 指标列表，如 ["ROE", "净利润", "营业收入"]
            years: 查询年数

        Returns:
            dict: 财务数据
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        metrics_str = ",".join(metrics)
        query = f"{name}近{years}年{metrics_str}"

        result = call("stock", "get_stock_financials", {"query": query})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_valuation(self, symbol: str, name: str) -> dict:
        """
        获取估值数据（PE/PB/PS）

        Args:
            symbol: 股票代码
            name: 股票名称

        Returns:
            dict: 当前及历史估值数据
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        query = f"{name}当前PE、PB、PS及近5年估值走势"

        result = call("stock", "get_stock_financials", {"query": query})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_historical_price(self, symbol: str, name: str, period: str = "1年") -> dict:
        """
        获取历史行情数据

        Args:
            symbol: 股票代码
            name: 股票名称
            period: 时间周期（1个月/6个月/1年/5年/10年）

        Returns:
            dict: 历史价格数据
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        query = f"{name}近{period}月收盘价"

        result = call("stock", "get_stock_performance", {"query": query})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_shareholders(self, symbol: str, name: str) -> dict:
        """
        获取股东结构数据

        Args:
            symbol: 股票代码
            name: 股票名称

        Returns:
            dict: 股东结构数据
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        query = f"{name}前10大股东及机构持股比例"

        result = call("stock", "get_stock_shareholders", {"query": query})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_risk_indicators(self, symbol: str, name: str) -> dict:
        """
        获取风险指标（Beta、波动率、夏普比率、VaR）

        Args:
            symbol: 股票代码
            name: 股票名称

        Returns:
            dict: 风险指标数据
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        query = f"{name}Beta系数、年化波动率、夏普比率、VaR"

        result = call("stock", "get_risk_indicators", {"query": query})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def search_stocks(self, criteria: str) -> dict:
        """
        智能选股

        Args:
            criteria: 选股条件，如"汽车零部件行业市值大于1000亿"

        Returns:
            dict: 选股结果
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        result = call("stock", "search_stocks", {"query": criteria})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_macro_data(self, query: str) -> dict:
        """
        获取宏观经济/行业数据

        Args:
            query: 查询语句，如"CPI 202401-202412"

        Returns:
            dict: 宏观数据
        """
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        result = call("edb", "get_edb_data", {"query": query})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def _parse_response(self, data: dict) -> dict:
        """解析 iFinD 响应数据"""
        try:
            content = data.get("result", {}).get("content", [{}])[0].get("text", "")
            parsed = json.loads(content)
            return {
                "success": True,
                "code": parsed.get("code"),
                "message": parsed.get("msg"),
                "data": parsed.get("data", {}),
                "raw": content,
            }
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            return {
                "success": False,
                "error": f"解析失败: {e}",
                "raw": str(data)[:500],
            }


class iFinDFundSource:
    """
    同花顺 iFinD 基金数据源
    """

    def __init__(self):
        self.token = os.getenv("IFIND_MCP_TOKEN")

    def _is_available(self) -> bool:
        return bool(self.token)

    def search_funds(self, criteria: str) -> dict:
        """基金搜索"""
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        result = call("fund", "search_funds", {"query": criteria})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_fund_profile(self, fund_name: str) -> dict:
        """基金基本资料"""
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        result = call("fund", "get_fund_profile", {"query": f"{fund_name}基本资料"})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def get_fund_portfolio(self, fund_name: str) -> dict:
        """基金持仓明细"""
        if not self._is_available():
            raise DataSourceError("iFinD 未配置")

        result = call("fund", "get_fund_portfolio", {"query": f"{fund_name}持仓明细"})
        if not result["ok"]:
            raise DataSourceError(f"iFinD 查询失败: {result.get('error')}")

        return self._parse_response(result["data"])

    def _parse_response(self, data: dict) -> dict:
        """解析响应"""
        try:
            content = data.get("result", {}).get("content", [{}])[0].get("text", "")
            parsed = json.loads(content)
            return {
                "success": True,
                "code": parsed.get("code"),
                "message": parsed.get("msg"),
                "data": parsed.get("data", {}),
                "raw": content,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"解析失败: {e}",
                "raw": str(data)[:500],
            }
