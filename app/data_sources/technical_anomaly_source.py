"""
富途技术异常数据源适配器
封装 futu-technical-anomaly skill，支持日/周/月三维度查询
"""
import json
import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 脚本路径
SCRIPT_PATH = Path.home() / ".claude" / "skills" / "futu-technical-anomaly" / "scripts" / "handle_technical_anomaly.py"


@dataclass
class TechnicalAnomalyResult:
    """技术异常查询结果"""
    stock_symbol: str
    time_range: int
    timeframe_label: str  # daily / weekly / monthly
    raw_content: str
    bullish_signals: List[str] = field(default_factory=list)
    bearish_signals: List[str] = field(default_factory=list)
    neutral_signals: List[str] = field(default_factory=list)
    overall_direction: str = "neutral"  # bullish / bearish / neutral / mixed


class TechnicalAnomalySource:
    """
    富途技术异常数据源
    调用 futu-technical-anomaly skill 脚本获取日/周/月三维度技术信号
    """

    # 看涨关键词
    BULLISH_KEYWORDS = [
        "上涨", "上升", "突破", "金叉", "超卖区域", "反弹",
        "买入信号", "多头排列", "底部", "看涨", "转强",
        "进入超卖", "可能即将上涨", "价格可能上升",
    ]

    # 看跌关键词
    BEARISH_KEYWORDS = [
        "下跌", "下降", "跌破", "死叉", "超买区域", "回调",
        "卖出信号", "空头排列", "顶部", "看跌", "转弱",
        "进入超买", "可能即将下跌", "价格可能下降",
        "潜在的下跌趋势",
    ]

    def __init__(self):
        self._cache: Dict[str, Dict] = {}  # symbol -> {date: {timeframe: result}}

    def fetch_all_timeframes(self, symbol: str, max_workers: int = 3) -> Dict[str, TechnicalAnomalyResult]:
        """
        获取日/周/月三个维度的技术异常（并行查询，最多5秒）

        Args:
            symbol: 光剑格式代码，如 "HK:00700" / "US:TSLA"
            max_workers: 并行线程数

        Returns:
            {"daily": result, "weekly": result, "monthly": result}
        """
        # 检查缓存
        cache_key = f"{symbol}_{date.today()}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 转换为富途格式
        futu_symbol = self._to_futu_symbol(symbol)

        timeframes = [
            ("daily", 7, "日K"),
            ("weekly", 30, "周K"),
            ("monthly", 90, "月K"),
        ]

        results = {}
        # 并行查询三个维度
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_label = {
                executor.submit(self._fetch_single, futu_symbol, tr, label): (label, tr)
                for label, tr, _ in timeframes
            }
            for future in as_completed(future_to_label):
                label, time_range = future_to_label[future]
                try:
                    results[label] = future.result()
                except Exception as e:
                    logger.warning(f"{label}维度技术异常查询失败 {symbol}: {e}")
                    results[label] = TechnicalAnomalyResult(
                        stock_symbol=symbol,
                        time_range=time_range,
                        timeframe_label=label,
                        raw_content="",
                    )

        self._cache[cache_key] = results
        return results

    def _fetch_single(self, futu_symbol: str, time_range: int, label: str) -> TechnicalAnomalyResult:
        """单次查询"""
        if not SCRIPT_PATH.exists():
            raise FileNotFoundError(f"脚本不存在: {SCRIPT_PATH}")

        cmd = [
            "python3", str(SCRIPT_PATH),
            futu_symbol,
            "--time-range", str(time_range),
            "--json",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,  # 5秒超时，避免阻塞信号生成
        )

        if result.returncode != 0:
            raise RuntimeError(f"脚本执行失败: {result.stderr}")

        # 解析JSON（处理日志输出混杂的情况）
        output = result.stdout
        match = re.search(r'\{.*\}', output, re.DOTALL)
        if not match:
            raise ValueError(f"无法从输出中解析JSON: {output[:200]}")

        data = json.loads(match.group())
        content = data.get("data", {}).get("content", "")

        # 解析文本内容
        bullish, bearish, neutral, direction = self._parse_content(content)

        return TechnicalAnomalyResult(
            stock_symbol=futu_symbol,
            time_range=time_range,
            timeframe_label=label,
            raw_content=content,
            bullish_signals=bullish,
            bearish_signals=bearish,
            neutral_signals=neutral,
            overall_direction=direction,
        )

    def _parse_content(self, content: str) -> tuple:
        """
        解析技术异常文本内容

        Returns:
            (bullish_signals, bearish_signals, neutral_signals, overall_direction)
        """
        if not content or not content.strip():
            return [], [], [], "neutral"

        bullish = []
        bearish = []
        neutral = []

        # 按行分割
        lines = [line.strip() for line in content.split("\n") if line.strip()]

        for line in lines:
            # 去掉日期前缀（如 "05/14 "）
            text = re.sub(r'^\d{2}/\d{2}\s*', '', line)

            # 判断方向
            is_bullish = any(kw in text for kw in self.BULLISH_KEYWORDS)
            is_bearish = any(kw in text for kw in self.BEARISH_KEYWORDS)

            if is_bullish and is_bearish:
                # 矛盾信号，归入mixed但分别记录
                if "空头排列" in text or "下跌趋势" in text:
                    bearish.append(text)
                elif "多头排列" in text or "上涨趋势" in text:
                    bullish.append(text)
                else:
                    neutral.append(text)
            elif is_bullish:
                bullish.append(text)
            elif is_bearish:
                bearish.append(text)
            else:
                neutral.append(text)

        # 判断总体方向
        b_count = len(bullish)
        be_count = len(bearish)

        if b_count > 0 and be_count > 0:
            if b_count > be_count:
                direction = "mixed_bullish"
            elif be_count > b_count:
                direction = "mixed_bearish"
            else:
                direction = "mixed"
        elif b_count > 0:
            direction = "bullish"
        elif be_count > 0:
            direction = "bearish"
        else:
            direction = "neutral"

        return bullish, bearish, neutral, direction

    @staticmethod
    def _to_futu_symbol(symbol: str) -> str:
        """光剑格式 -> 富途格式: HK:00700 -> HK.00700"""
        return symbol.replace(":", ".")

    @staticmethod
    def _to_lightsaber_symbol(futu_symbol: str) -> str:
        """富途格式 -> 光剑格式: HK.00700 -> HK:00700"""
        return futu_symbol.replace(".", ":", 1)


def summarize_patterns(results: Dict[str, TechnicalAnomalyResult]) -> Dict:
    """
    汇总三个维度的K线形态分析结果

    Returns:
        {
            "daily": {"direction": "bullish", "signals": [...], "raw": "..."},
            "weekly": {...},
            "monthly": {...},
            "resonance": "strong_bullish",  # 共振判断
            "summary": "三级共振看涨",
        }
    """
    summary = {}
    directions = {}

    for label in ["daily", "weekly", "monthly"]:
        if label in results:
            r = results[label]
            summary[label] = {
                "direction": r.overall_direction,
                "bullish_count": len(r.bullish_signals),
                "bearish_count": len(r.bearish_signals),
                "signals": r.bullish_signals + r.bearish_signals,
                "raw": r.raw_content,
            }
            directions[label] = r.overall_direction
        else:
            summary[label] = {"direction": "neutral", "signals": [], "raw": ""}
            directions[label] = "neutral"

    # 共振判断
    d, w, m = directions.get("daily", "neutral"), directions.get("weekly", "neutral"), directions.get("monthly", "neutral")

    # 标准化方向（mixed_bullish -> bullish, mixed_bearish -> bearish）
    def normalize(d):
        if "bullish" in d:
            return "bullish"
        if "bearish" in d:
            return "bearish"
        return "neutral"

    nd, nw, nm = normalize(d), normalize(w), normalize(m)

    if nd == "bullish" and nw == "bullish" and nm == "bullish":
        resonance = "strong_bullish"
        resonance_text = "三级共振看涨"
    elif nd == "bearish" and nw == "bearish" and nm == "bearish":
        resonance = "strong_bearish"
        resonance_text = "三级共振看跌"
    elif nd == "bullish" and nw == "bullish":
        resonance = "medium_bullish"
        resonance_text = "日周共振看涨"
    elif nd == "bearish" and nw == "bearish":
        resonance = "medium_bearish"
        resonance_text = "日周共振看跌"
    elif nd == "bullish":
        resonance = "weak_bullish"
        resonance_text = "日线看涨"
    elif nd == "bearish":
        resonance = "weak_bearish"
        resonance_text = "日线看跌"
    else:
        resonance = "none"
        resonance_text = "无明显形态"

    summary["resonance"] = resonance
    summary["summary"] = resonance_text

    return summary
