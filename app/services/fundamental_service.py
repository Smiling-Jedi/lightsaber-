"""
基本面数据服务 v2 — 估值历史百分位 (3年/5年/10年)

通过 iFinD MCP 获取股票 PE/PB 当前值及历史月度数据，
计算当前估值在 3年/5年/10年 历史区间中的百分位。
支持港股/美股/A股，自动处理不同市场代码格式。
"""
import json
import logging
from typing import Optional

from app.data_sources.ifind_source import iFinDSource, DataSourceError
from services.ifind_skill import call

logger = logging.getLogger(__name__)

# 计算百分位需要的历史窗口（年）
PERCENTILE_WINDOWS = [3, 5, 10]


class FundamentalService:
    """基本面数据服务"""

    def __init__(self):
        self.source = iFinDSource()

    def get_snapshot(self, symbol: str, name: str) -> Optional[dict]:
        """
        获取股票基本面快照（PE/PB 当前值 + 历史百分位 + ROE）

        Args:
            symbol: 股票代码（如 HK:00700, US:NVDA, A:300750）
            name:   股票中文/英文名称

        Returns:
            dict: 包含 PE/PB 当前值、各窗口百分位、ROE
                  或 None（查询失败/未配置）
        """
        if not self.source._is_available():
            return None

        try:
            snapshot = {}

            # ── 1. 当前估值指标 ──
            val_result = call("stock", "get_stock_financials",
                              {"query": f"{name}市盈率PE(TTM)、市净率PB"})
            if val_result.get("ok"):
                val_raw = val_result["data"].get("result", {}).get("content", [{}])[0].get("text", "")
                val_data = self._parse_markdown_table(val_raw)
                if val_data:
                    snapshot.update({k: v for k, v in val_data.items() if v is not None})

            # ── 2. 各窗口历史百分位 ──
            pe = snapshot.get("pe")
            pb = snapshot.get("pb")

            if pe is not None:
                snapshot["pe_percentiles"] = self._get_all_percentiles(name, "市盈率PE(TTM)", pe)

            if pb is not None:
                snapshot["pb_percentiles"] = self._get_all_percentiles(name, "市净率PB", pb)

            # ── 3. ROE ──
            roe_result = call("stock", "get_stock_financials",
                              {"query": f"{name}净资产收益率ROE"})
            if roe_result.get("ok"):
                roe_raw = roe_result["data"].get("result", {}).get("content", [{}])[0].get("text", "")
                roe_data = self._parse_markdown_table(roe_raw)
                if roe_data and roe_data.get("roe") is not None:
                    snapshot["roe"] = roe_data["roe"]

            # 过滤掉全 None 的情况
            if not snapshot or all(v is None for k, v in snapshot.items()
                                   if k not in ("pe_percentiles", "pb_percentiles")):
                return None

            return snapshot

        except DataSourceError:
            logger.warning(f"iFinD未配置，跳过基本面 {symbol}")
            return None
        except Exception as e:
            logger.warning(f"基本面查询异常 {symbol}: {e}")
            return None

    def _get_all_percentiles(self, name: str, metric_name: str, current: float) -> dict:
        """
        获取指定指标在 3年/5年/10年 窗口的历史百分位

        Returns:
            {3: {"percentile": 23, "years": 2.5}, 5: {...}, 10: {...}}
            years 表示实际拿到的数据覆盖了多少年（可能不足请求值）
        """
        result = {}
        for years in PERCENTILE_WINDOWS:
            pct = self._get_percentile(name, metric_name, current, years)
            if pct:
                result[years] = pct
        return result

    def _get_percentile(self, name: str, metric_name: str, current: float, years: int) -> Optional[dict]:
        """
        拉取指定年数的月度历史数据，计算当前值在历史中的百分位

        Returns:
            {"percentile": int, "years": float} 或 None
        """
        try:
            result = call("stock", "get_stock_financials",
                          {"query": f"{name}近{years}年{metric_name}月度数据"})
            if not result.get("ok"):
                return None

            raw = result["data"].get("result", {}).get("content", [{}])[0].get("text", "")
            history = self._parse_history_values(raw, metric_name)
            if not history or len(history) < 6:
                return None

            # 加入当前值后排序计算百分位
            all_values = sorted(history + [current])
            idx = all_values.index(current)
            percentile = round(idx / (len(all_values) - 1) * 100)

            # 计算实际数据覆盖了多少年
            actual_years = round(len(history) / 12, 1)

            return {
                "percentile": percentile,
                "years": actual_years,
            }
        except Exception as e:
            logger.warning(f"百分位计算异常 ({name} {metric_name} {years}年): {e}")
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

        # 报告期（保留兼容，虽然不再用于显示）
        snapshot["report_date"] = row.get("日期", row.get("报告期", ""))

        # 过滤掉全None的情况
        if all(v is None for k, v in snapshot.items() if k not in ("report_date",)):
            return None

        return snapshot

    @staticmethod
    def _parse_history_values(raw: str, metric_key: str) -> list:
        """
        从历史数据表格中提取数值列表

        Args:
            raw: iFinD 返回的原始文本（含 Markdown 表格）
            metric_key: 指标名称，用于匹配表头列

        Returns:
            float 列表（历史数值，不含当前值）
        """
        if not raw:
            return []

        # 先尝试从 JSON 中提取 answer
        answer = raw
        try:
            parsed = json.loads(raw)
            answer = parsed.get("data", {}).get("answer", raw)
        except json.JSONDecodeError:
            pass

        lines = [l.strip() for l in answer.split("\n") if l.strip().startswith("|")]
        if len(lines) < 3:
            return []

        # 找指标所在列
        headers = [h.strip() for h in lines[0].split("|") if h.strip()]
        col_idx = None
        for i, h in enumerate(headers):
            # 匹配指标列：PE(TTM) / 市净率(PB) / 市盈率PE(TTM) 等
            if metric_key in h or "PE" in h or "PB" in h or "市盈率" in h or "市净率" in h:
                col_idx = i
                break

        if col_idx is None:
            return []

        values = []
        for line in lines[2:]:
            if "---" in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if col_idx < len(cells):
                v = _to_float(cells[col_idx])
                if v is not None:
                    values.append(v)
        return values


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
