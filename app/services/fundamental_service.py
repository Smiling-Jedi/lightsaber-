"""
基本面数据服务

通过 iFinD MCP 获取股票基本面快照（PE/PB/ROE/营收/净利润增长）
支持港股/美股/A股，自动处理不同市场代码格式
"""
import json
import logging
from typing import Optional

from app.data_sources.ifind_source import iFinDSource, DataSourceError
from services.ifind_skill import call

logger = logging.getLogger(__name__)


class FundamentalService:
    """基本面数据服务"""

    def __init__(self):
        self.source = iFinDSource()

    def get_snapshot(self, symbol: str, name: str) -> Optional[dict]:
        """
        获取股票基本面快照

        Args:
            symbol: 股票代码（如 HK:00700, US:NVDA, A:300750）
            name:   股票中文名称

        Returns:
            dict: 包含关键基本面指标，或 None（查询失败/未配置）
        """
        if not self.source._is_available():
            return None

        try:
            snapshot = {}

            # 1. 查询估值指标
            val_result = call("stock", "get_stock_financials", {"query": f"{name}市盈率PE、市净率PB、净资产收益率ROE"})
            if val_result.get("ok"):
                val_raw = val_result["data"].get("result", {}).get("content", [{}])[0].get("text", "")
                val_data = self._parse_markdown_table(val_raw)
                if val_data:
                    snapshot.update({k: v for k, v in val_data.items() if v is not None})

            # 2. 查询成长指标（只合并非None值，避免覆盖估值数据）
            growth_result = call("stock", "get_stock_financials", {"query": f"{name}营业收入同比增长率、净利润同比增长率、毛利率"})
            if growth_result.get("ok"):
                growth_raw = growth_result["data"].get("result", {}).get("content", [{}])[0].get("text", "")
                growth_data = self._parse_markdown_table(growth_raw)
                if growth_data:
                    snapshot.update({k: v for k, v in growth_data.items() if v is not None})

            # 过滤掉全 None 的情况
            if not snapshot or all(v is None for k, v in snapshot.items() if k != "report_date"):
                return None

            return snapshot

        except DataSourceError as e:
            logger.warning(f"iFinD未配置，跳过基本面 {symbol}")
            return None
        except Exception as e:
            logger.warning(f"基本面查询异常 {symbol}: {e}")
            return None

    @staticmethod
    def _parse_markdown_table(raw: str) -> Optional[dict]:
        """
        解析 iFinD 返回的 Markdown 表格，提取最新一期数据

        iFinD 返回格式（raw 是 JSON 字符串，answer 字段内含 Markdown 表格）：
        {"code":1, ..., "data":{"answer":"|证券代码|...\n|---|---|---|\n|...|...|\n"}}
        """
        if not raw:
            return None

        # 先尝试从 JSON 中提取 answer 字段
        answer = raw
        try:
            parsed = json.loads(raw)
            answer = parsed.get("data", {}).get("answer", raw)
        except json.JSONDecodeError:
            pass  # raw 本身就是 Markdown，直接用

        # 提取表格部分（Markdown表格行）
        lines = [l.strip() for l in answer.split("\n") if l.strip().startswith("|")]
        if len(lines) < 3:
            return None

        # 第一行是表头，第二行是分隔符，第三行开始是数据
        header_line = lines[0]
        data_lines = [l for l in lines[2:] if l.startswith("|") and "---" not in l]

        if not data_lines:
            return None

        # 解析表头（去掉首位的空字符串）
        headers = [h.strip() for h in header_line.split("|") if h.strip()]

        # 取最新一期数据（第一行数据，iFinD按日期倒序排列）
        first_data = data_lines[0]
        # split后过滤掉首位的空字符串，但保留中间的空白单元格
        all_cells = first_data.split("|")
        cells = [c.strip() for c in all_cells[1:-1]]  # 去掉首尾空元素

        # 表头和数据对齐（处理空单元格）
        row = {}
        for i, h in enumerate(headers):
            val = cells[i] if i < len(cells) else ""
            row[h] = val if val else None

        # 提取关键指标（支持多种可能的列名）
        snapshot = {}

        # PE
        pe = _find_value(row, ["市盈率PE(TTM)", "市盈率PE", "PE(TTM)", "PE", "市盈率"])
        snapshot["pe"] = _to_float(pe)

        # PB
        pb = _find_value(row, ["市净率PB(最新)", "市净率PB", "PB", "市净率"])
        snapshot["pb"] = _to_float(pb)

        # ROE
        roe = _find_value(row, ["净资产收益率ROE", "ROE", "净资产收益率"])
        snapshot["roe"] = _to_float(roe)

        # 营收增长
        rev_growth = _find_value(row, [
            "营业收入同比增长率",
            "营业收入增长率",
            "营收同比增长",
            "营收增长率",
            "营业总收入同比增长率",
        ])
        snapshot["revenue_growth"] = _to_float(rev_growth)

        # 净利润增长
        profit_growth = _find_value(row, [
            "净利润同比增长率",
            "净利润增长率",
            "归母净利润同比增长率",
            "净利润(同比增长率)",
        ])
        snapshot["profit_growth"] = _to_float(profit_growth)

        # 毛利率
        margin = _find_value(row, [
            "毛利率",
            "销售毛利率",
            "销售毛利率(TTM)",
        ])
        snapshot["gross_margin"] = _to_float(margin)

        # 报告期
        snapshot["report_date"] = row.get("日期", row.get("报告期", ""))

        # 过滤掉全None的情况
        if all(v is None for k, v in snapshot.items() if k not in ("report_date",)):
            return None

        return snapshot


# ── 工具函数 ──────────────────────────────────────────

def _find_value(row: dict, keys: list) -> Optional[str]:
    """在row中按候选key查找值，支持部分匹配（表头可能带单位后缀）"""
    # 先精确匹配
    for k in keys:
        if k in row and row[k]:
            return row[k]
    # 再部分匹配（表头如 "净利润(同比增长率)（单位：%）"）
    for k in keys:
        for row_key in row:
            if k in row_key and row[row_key]:
                return row[row_key]
    return None


def _to_float(val: Optional[str]) -> Optional[float]:
    """将字符串转为float，处理空值和特殊字符"""
    if not val:
        return None
    # 清理：去掉百分号、逗号、制表符
    cleaned = val.replace("%", "").replace(",", "").replace("\t", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
