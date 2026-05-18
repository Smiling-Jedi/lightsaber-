"""
三周期共振分析服务

核心逻辑：
  1. 读取某只股票最新的日/周/月三条形态分析记录
  2. 从每条记录的形态名称提取方向（看涨/看跌/中性）
  3. 三周期方向组合 → 共振状态（规则驱动）
  4. 生成共振结论自然语言描述 + 操作建议

规则驱动，100%一致，无需LLM。
"""
import json
import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.pattern_analysis import PatternAnalysis

logger = logging.getLogger(__name__)

# ── 方向提取规则 ──
# 从形态名称提取看涨/看跌/中性方向

BULLISH_PATTERNS = [
    "双底", "w底", "头肩底", "上升通道", "矩形整理向上突破",
    "三角形整理向上突破", "杯柄", "圆弧底", "上升三角形",
    "旗形整理", "突破", "反弹", "看涨",
]

BEARISH_PATTERNS = [
    "双顶", "m顶", "头肩顶", "下降通道", "矩形整理向下突破",
    "三角形整理向下突破", "圆弧顶", "下降三角形", "看跌",
    "下跌", "破位", "断头铡刀",
]

NEUTRAL_PATTERNS = [
    "矩形整理", "三角形整理", "无明显形态", "震荡", "盘整",
    "横盘", "观望", "整理", "无形态",
]


# ── 共振状态规则表 ──
# (day_dir, week_dir, month_dir) -> (resonance_state, strength, description_template)

RESONANCE_RULES: Dict[Tuple[str, str, str], Tuple[str, int, str]] = {
    # 三周期同向 — 最强信号
    ("看涨", "看涨", "看涨"): (
        "三周期共振看涨", 5,
        "日/周/月三周期同步看涨，短中长期资金达成共识，信号最强"
    ),
    ("看跌", "看跌", "看跌"): (
        "三周期共振看跌", 5,
        "日/周/月三周期同步看跌，短中长期资金同步离场，风险最高"
    ),

    # 两周期同向 + 一周期中性 — 较强信号
    ("看涨", "看涨", "中性"): (
        "中短期共振看涨", 4,
        "日线+周线同步看涨，中期趋势确立，月线尚未确认"
    ),
    ("看涨", "中性", "看涨"): (
        "中长期共振看涨", 4,
        "日线+月线同步看涨，大周期支撑，周线正在确认"
    ),
    ("中性", "看涨", "看涨"): (
        "中长期共振看涨", 4,
        "周线+月线同步看涨，中长期趋势向好，日线处于整理"
    ),
    ("看跌", "看跌", "中性"): (
        "中短期共振看跌", 4,
        "日线+周线同步看跌，中期调整中，月线尚未确认"
    ),
    ("看跌", "中性", "看跌"): (
        "中长期共振看跌", 4,
        "日线+月线同步看跌，大周期承压，周线正在确认"
    ),
    ("中性", "看跌", "看跌"): (
        "中长期共振看跌", 4,
        "周线+月线同步看跌，中长期趋势走弱，日线处于整理"
    ),

    # 一周期看涨 + 一周期看跌 + 一周期中性 — 冲突
    ("看涨", "看跌", "中性"): (
        "周期冲突", 2,
        "日线反弹但周线承压，短期与中期矛盾，观望为主"
    ),
    ("看涨", "中性", "看跌"): (
        "周期冲突", 2,
        "日线反弹但月线仍弱，短期反弹可能受大周期压制"
    ),
    ("中性", "看涨", "看跌"): (
        "周期冲突", 2,
        "周线筑底但月线仍弱，中期好转但长期趋势未改"
    ),
    ("看跌", "看涨", "中性"): (
        "周期冲突", 2,
        "日线调整但周线向好，短期回调可能是中期买入机会"
    ),
    ("看跌", "中性", "看涨"): (
        "周期冲突", 2,
        "日线调整但月线向好，短期回调不改长期趋势"
    ),
    ("中性", "看跌", "看涨"): (
        "周期冲突", 2,
        "周线调整但月线向好，中期波动不改长期支撑"
    ),

    # 三周期中性 — 无方向
    ("中性", "中性", "中性"): (
        "三周期混沌", 1,
        "日/周/月均无明显方向，市场处于混沌整理期，等待形态明朗"
    ),
}


# ── 默认规则：未覆盖的组合 → 周期冲突 ──
DEFAULT_RULE = ("周期冲突", 2, "各周期信号不一致，方向不明，建议观望")


class ResonanceService:
    """三周期共振分析服务"""

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────
    # 共振分析入口
    # ─────────────────────────────────────────────────────

    def analyze_resonance(self, symbol: str) -> Optional[Dict]:
        """
        分析某只股票的三周期共振状态。

        Args:
            symbol: 股票代码（如 HK:00700）

        Returns:
            共振分析结果字典，或 None（数据不足）
        """
        today = date.today()

        # 1. 读取最新的日/周/月三条分析记录
        analyses = self._fetch_latest_analyses(symbol, today)
        if len(analyses) < 3:
            logger.warning(f"{symbol} 分析数据不足（{len(analyses)}/3），无法计算共振")
            return None

        # 2. 提取每个周期的方向
        day_dir = self._extract_direction(analyses["day"])
        week_dir = self._extract_direction(analyses["week"])
        month_dir = self._extract_direction(analyses["month"])

        # 3. 计算共振状态
        resonance_state, strength, description = self._calculate_resonance(
            day_dir, week_dir, month_dir
        )

        # 4. 生成操作建议
        actionable = self._generate_actionable(
            resonance_state, strength, analyses
        )

        # 5. 组装结果
        result = {
            "symbol": symbol,
            "analysis_date": str(today),
            "day": {
                "pattern": analyses["day"].pattern_name,
                "state": analyses["day"].pattern_state,
                "direction": day_dir,
                "summary": analyses["day"].summary,
            },
            "week": {
                "pattern": analyses["week"].pattern_name,
                "state": analyses["week"].pattern_state,
                "direction": week_dir,
                "summary": analyses["week"].summary,
            },
            "month": {
                "pattern": analyses["month"].pattern_name,
                "state": analyses["month"].pattern_state,
                "direction": month_dir,
                "summary": analyses["month"].summary,
            },
            "resonance": {
                "state": resonance_state,
                "strength": strength,
                "description": description,
            },
            "actionable": actionable,
        }

        logger.info(
            f"{symbol} 共振分析: {day_dir}/{week_dir}/{month_dir} → "
            f"{resonance_state} (强度{strength})"
        )
        return result

    def analyze_all_resonances(self) -> List[Dict]:
        """批量计算全部持仓的共振状态"""
        # 获取有分析数据的所有股票
        from app.models.position import Position

        positions = (
            self.db.query(Position)
            .filter(Position.total_shares > 0)
            .all()
        )

        results = []
        for pos in positions:
            result = self.analyze_resonance(pos.stock_symbol)
            if result:
                results.append(result)

        return results

    # ─────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────

    def _fetch_latest_analyses(
        self, symbol: str, analysis_date: date
    ) -> Dict[str, PatternAnalysis]:
        """读取某只股票最新的日/周/月分析记录"""
        analyses = {}
        for period in ["day", "week", "month"]:
            record = (
                self.db.query(PatternAnalysis)
                .filter_by(stock_symbol=symbol, period=period)
                .order_by(PatternAnalysis.analysis_date.desc())
                .first()
            )
            if record:
                analyses[period] = record
        return analyses

    def _extract_direction(self, analysis: PatternAnalysis) -> str:
        """从形态分析记录提取方向（看涨/看跌/中性）"""
        pattern_name = (analysis.pattern_name or "").lower()

        # 先匹配看跌（更严格的关键词）
        for keyword in BEARISH_PATTERNS:
            if keyword in pattern_name:
                return "看跌"

        # 再匹配看涨
        for keyword in BULLISH_PATTERNS:
            if keyword in pattern_name:
                return "看涨"

        # 再匹配中性
        for keyword in NEUTRAL_PATTERNS:
            if keyword in pattern_name:
                return "中性"

        # 默认：根据pattern_state判断
        state = (analysis.pattern_state or "").lower()
        if "失效" in state or "跌破" in state:
            return "看跌"
        elif "确认" in state or "突破" in state:
            return "看涨"

        # 最终默认
        return "中性"

    def _calculate_resonance(
        self, day_dir: str, week_dir: str, month_dir: str
    ) -> Tuple[str, int, str]:
        """计算共振状态"""
        key = (day_dir, week_dir, month_dir)
        return RESONANCE_RULES.get(key, DEFAULT_RULE)

    def _generate_actionable(
        self, resonance_state: str, strength: int,
        analyses: Dict[str, PatternAnalysis]
    ) -> Dict[str, str]:
        """基于共振状态生成操作建议"""

        # 提取各周期的止损位（取最严格的）
        stop_losses = []
        for period in ["day", "week", "month"]:
            if period in analyses and analyses[period].stop_loss:
                stop_losses.append(float(analyses[period].stop_loss))

        strictest_stop = min(stop_losses) if stop_losses else None

        # 基于共振状态生成建议
        if "三周期共振看涨" in resonance_state:
            return {
                "base_position": "继续持有，三周期共振支撑长期逻辑",
                "swing_position": "可积极加仓，共振信号最强",
                "stop_loss_rule": f"统一止损 {strictest_stop:.2f}" if strictest_stop else "设结构止损",
                "targets": "分批止盈，先看第一目标",
                "risk_level": "低",
            }

        elif "共振看涨" in resonance_state:
            return {
                "base_position": "继续持有",
                "swing_position": "可谨慎加仓，等待第三周期确认",
                "stop_loss_rule": f"统一止损 {strictest_stop:.2f}" if strictest_stop else "设结构止损",
                "targets": "分批止盈",
                "risk_level": "中",
            }

        elif "三周期共振看跌" in resonance_state:
            return {
                "base_position": "考虑减仓，三周期同步走弱",
                "swing_position": "清仓或暂停加仓",
                "stop_loss_rule": f"跌破 {strictest_stop:.2f} 严格止损" if strictest_stop else "跌破关键支撑止损",
                "targets": "观望，等待筑底信号",
                "risk_level": "高",
            }

        elif "共振看跌" in resonance_state:
            return {
                "base_position": "减仓观望",
                "swing_position": "不操作或轻仓试探",
                "stop_loss_rule": f"跌破 {strictest_stop:.2f} 止损" if strictest_stop else "设止损",
                "targets": "观望",
                "risk_level": "中高",
            }

        elif "周期冲突" in resonance_state:
            return {
                "base_position": "继续持有，不改长期逻辑",
                "swing_position": "观望，等待方向明朗",
                "stop_loss_rule": "严格止损，防止假突破",
                "targets": "不追高，不抄底",
                "risk_level": "中",
            }

        else:  # 三周期混沌
            return {
                "base_position": "持有不动",
                "swing_position": "不操作",
                "stop_loss_rule": "设好止损，防止方向突变",
                "targets": "等待形态明朗",
                "risk_level": "中",
            }
