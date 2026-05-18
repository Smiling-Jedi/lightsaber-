"""
形态分析服务

核心流程：
  1. 读取持仓列表
  2. 拉取日K/周K/月K数据
  3. 格式化K线数据为文本
  4. 调用 Claude API（Opus 4.7）进行形态分析
  5. 解析JSON响应
  6. 写入 pattern_analyses 表

模型：claude-opus-4-7（经测试形态分析最精确）
temperature: 0.2（低温度保证一致性）
"""
import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.pattern_analysis import PatternAnalysis
from app.models.position import Position
from app.models.stock import Stock
from app.services.futu_kline_service import FutuKlineService

logger = logging.getLogger(__name__)

# Claude API 配置
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-opus-4-7"

# K线数据量配置
KLINES_CONFIG = {
    "day": {"count": 120, "label": "交易日", "period": "day"},
    "week": {"count": 60, "label": "周", "period": "week"},
    "month": {"count": 36, "label": "月", "period": "month"},
}


class PatternAnalysisService:
    """形态分析服务"""

    def __init__(self, db: Session):
        self.db = db
        self.kline_service = FutuKlineService()

    # ─────────────────────────────────────────────────────
    # 批量分析入口
    # ─────────────────────────────────────────────────────

    def analyze_all_holdings(
        self, symbols: Optional[List[str]] = None
    ) -> Dict:
        """
        批量分析全部持仓（或指定股票）。

        Args:
            symbols: 指定分析的股票代码列表，None则分析全部持仓

        Returns:
            {"total": N, "success": N, "failed": N, "errors": [...]}
        """
        if symbols is None:
            # 读取全部有持仓的股票
            positions = (
                self.db.query(Position)
                .filter(Position.total_shares > 0)
                .all()
            )
            symbols = [p.stock_symbol for p in positions]
        else:
            # 只分析指定的股票
            positions = {
                p.stock_symbol: p
                for p in self.db.query(Position)
                .filter(Position.stock_symbol.in_(symbols))
                .all()
            }

        total = len(symbols)
        success = 0
        failed = 0
        errors = []

        logger.info(f"开始批量形态分析，共 {total} 只股票")

        for symbol in symbols:
            try:
                position = (
                    positions[symbol]
                    if isinstance(positions, dict)
                    else next(
                        (p for p in positions if p.stock_symbol == symbol), None
                    )
                )
                stock = self.db.get(Stock, symbol)
                stock_name = stock.name if stock else symbol

                result = self.analyze_single_stock(
                    symbol, stock_name, position
                )
                if result:
                    success += 1
                else:
                    failed += 1
                    errors.append(f"{symbol}: 分析返回空结果")

            except Exception as e:
                failed += 1
                error_msg = f"{symbol}: {e}"
                errors.append(error_msg)
                logger.error(f"形态分析失败: {error_msg}")

        logger.info(
            f"批量形态分析完成: 总计{total}, 成功{success}, 失败{failed}"
        )
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "errors": errors,
        }

    # ─────────────────────────────────────────────────────
    # 单只股票分析
    # ─────────────────────────────────────────────────────

    def analyze_single_stock(
        self, symbol: str, stock_name: str,
        position: Optional[Position] = None
    ) -> List[PatternAnalysis]:
        """
        分析单只股票的形态（分周期独立分析）。

        Args:
            symbol: 股票代码（如 HK:00700）
            stock_name: 股票名称
            position: 持仓信息（可选）

        Returns:
            PatternAnalysis 对象列表（day/week/month各一条），或空列表（分析失败）
        """
        today = date.today()
        logger.info(f"分析形态: {symbol} ({stock_name})")

        # 1. 拉取三种周期的K线数据
        klines = {}
        for ktype, config in KLINES_CONFIG.items():
            rows = self.kline_service.get_kline(
                symbol, count=config["count"], ktype_str=ktype
            )
            if not rows:
                logger.warning(
                    f"{symbol} 拉取{ktype}K线失败，跳过分析"
                )
                return []
            klines[ktype] = rows

        # 2. 获取当前价格（从日K）
        current_price = self._get_current_price(klines["day"])

        # 3. 构建持仓信息文本
        position_info = self._build_position_info(position, current_price)

        # 4. 分周期独立分析（每只持仓3次LLM调用）
        results = []
        for ktype, config in KLINES_CONFIG.items():
            try:
                analysis = self._analyze_single_period(
                    symbol, stock_name, ktype, klines[ktype],
                    position_info, current_price, today
                )
                if analysis:
                    results.append(analysis)
            except Exception as e:
                logger.error(
                    f"{symbol} {ktype}K分析失败: {e}"
                )

        logger.info(
            f"{symbol} 形态分析完成: {len(results)}/3 个周期"
        )
        return results

    def _analyze_single_period(
        self, symbol: str, stock_name: str,
        ktype: str, kline_rows: List[Dict],
        position_info: str, current_price: float,
        analysis_date: date
    ) -> Optional[PatternAnalysis]:
        """分析单个周期"""
        config = KLINES_CONFIG[ktype]

        # 格式化单周期K线数据
        kline_text = self._format_single_period(
            ktype, config["label"], kline_rows, stock_name, current_price
        )

        # 构建Prompt并调用Claude API
        prompt = self._build_period_prompt(
            stock_name, symbol, ktype, kline_text, position_info
        )

        raw_response = self._call_claude_api(prompt, max_tokens=2000)
        if not raw_response:
            logger.error(f"{symbol} {ktype}K Claude API 调用失败")
            return None

        # 解析JSON
        parsed = self._parse_json_response(raw_response)

        # 保存到数据库
        analysis = self._save_analysis(
            symbol, analysis_date, ktype, parsed, raw_response
        )

        logger.info(
            f"{symbol} {ktype}K: {parsed.get('pattern_name', '未知')} "
            f"({parsed.get('confidence', 'unknown')})"
        )
        return analysis

    # ─────────────────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────────────────

    def _get_current_price(self, day_klines: List[Dict]) -> float:
        """从日K数据获取最新收盘价"""
        if day_klines:
            return day_klines[-1]["close"]
        return 0.0

    def _build_position_info(
        self, position: Optional[Position], current_price: float
    ) -> str:
        """构建持仓信息文本"""
        if not position:
            return "当前无持仓记录。"

        lines = []
        # 底仓
        if position.base_shares and position.base_shares > 0:
            base_cost = (
                float(position.base_cost)
                if position.base_cost else 0
            )
            lines.append(
                f"- 底仓: {position.base_shares}股 "
                f"@ {base_cost:.2f}"
            )

        # 波段仓
        swing_shares = position.swing_shares
        if swing_shares and swing_shares > 0:
            swing_cost = (
                float(position.swing_cost)
                if position.swing_cost else 0
            )
            lines.append(
                f"- 波段: {swing_shares}股 "
                f"@ {swing_cost:.2f}"
            )

        # 盈亏
        if position.avg_cost and position.avg_cost > 0:
            avg_cost = float(position.avg_cost)
            pl_pct = (
                (current_price - avg_cost) / avg_cost * 100
            )
            lines.append(
                f"- 总成本: {avg_cost:.2f} "
                f"(现价{current_price:.2f}, 盈亏{pl_pct:+.1f}%)"
            )

        return "\n".join(lines) if lines else "当前无持仓记录。"

    def _format_single_period(
        self, ktype: str, label: str, rows: List[Dict],
        stock_name: str, current_price: float
    ) -> str:
        """将单个周期的K线数据格式化为文本表格"""
        parts = [f"股票: {stock_name}  当前价格: {current_price:.2f}"]

        parts.append(f"\n【{ktype}K数据】(最近{len(rows)}个{label})")
        parts.append(
            "日期       | 开盘    | 最高    | 最低    | 收盘    | 成交量(万)"
        )
        parts.append("-" * 65)

        for row in rows:
            date_str = row["date"]
            vol_wan = int(row["volume"] / 10000)
            parts.append(
                f"{date_str} | {row['open']:7.2f} | "
                f"{row['high']:7.2f} | {row['low']:7.2f} | "
                f"{row['close']:7.2f} | {vol_wan:8,}"
            )

        # 关键价格统计
        closes = [r["close"] for r in rows]
        highs = [r["high"] for r in rows]
        lows = [r["low"] for r in rows]

        high_n = max(highs)
        low_n = min(lows)

        parts.append(f"\n【{ktype}K关键价格】")
        parts.append(f"当前价格: {closes[-1]:.2f}")
        parts.append(f"区间高点: {high_n:.2f}")
        parts.append(f"区间低点: {low_n:.2f}")
        parts.append(f"区间振幅: {(high_n - low_n) / low_n * 100:.1f}%")

        return "\n".join(parts)

    def _build_period_prompt(
        self, stock_name: str, symbol: str,
        ktype: str, kline_text: str, position_info: str
    ) -> str:
        """构建单周期 Claude API Prompt"""
        period_name = {"day": "日K", "week": "周K", "month": "月K"}.get(
            ktype, ktype
        )

        return f"""你是一位资深技术分析专家。请基于以下{stock_name}({symbol})的{period_name}数据，分析{period_name}级别的形态。

{kline_text}

【当前持仓信息】
{position_info}

【形态识别规则——严格遵守】
1. 优先识别经典形态（双底W底、头肩底、上升通道、下降通道、三角形整理、矩形整理）
2. 如果价格在两个相近低点后反弹，且反弹幅度超过5%，优先识别为"双底"
3. 如果价格在三个低点形成（左低-更低-右低），优先识别为"头肩底"
4. 如果价格无明显低点结构，只是在区间内震荡，识别为"矩形整理"或"无明显形态"
5. 不要同时给出多个可能的形态，只选择最可能的一种
6. 不要给出具体仓位百分比（如"加仓30%"），只给方向性建议（如"可分批加仓"/"继续持有"/"观望"）
7. 不要臆测数据范围外的结论；如不确定某项请用"数据不足以判断"
8. 关键价位要精确到具体数字
9. 不要主观估算 PE/PB 等估值数据（K线数据不含估值信息）
10. 【非常重要】summary 必须包含具体价位数字，禁止只写"上轨压力线"、"区间低点"这种模糊表述。
    例如错误："下降通道已确认，当前价位于通道下沿，距上轨压力约-28%"
    正确："下降通道已确认，当前456.4位于通道下沿448.7（+1.7%），距颈线633.7约-28%"

请只分析{period_name}级别，不要考虑其他周期。

按以下JSON格式输出：
{{
  "pattern_name": "形态名称（只能选一个：双底/头肩底/上升通道/下降通道/矩形整理/三角形整理/无明显形态）",
  "pattern_state": "构筑中/突破待确认/已确认/失效",
  "summary": "一句话结论，必须包含具体价位数字。例：'头肩底已确认，当前X.XX，距颈线Y.YY约+Z.Z%'",
  "key_levels": {{
    "support": "强支撑位（具体数字）",
    "resistance": "关键阻力位/颈线（具体数字）",
    "current_vs_key_pct": "当前价距关键位%"
  }},
  "targets": {{
    "target_1": "第一目标价（具体数字）",
    "target_2": "第二目标价（具体数字）",
    "stop_loss": "止损位（具体数字）"
  }},
  "validation": {{
    "volume": "成交量特征（仅基于K线volume判断）",
    "volatility": "波动特征（基于K线高低价计算ATR）",
    "cross_period_hint": "如果{period_name}是日K则给短期/反弹观点；周K则给中期/筑底观点；月K则给大周期/整体趋势观点"
  }},
  "actionable": {{
    "base_position": "对底仓的方向性建议",
    "swing_position": "对波段仓的方向性建议（含具体触发价和止损价数字）",
    "stop_loss_rule": "止损规则（含具体数字）",
    "targets": "持有目标（含具体数字）",
    "risk_level": "风险等级（高/中/低）"
  }},
  "confidence": "总评：high/medium/low",
  "confidence_scores": {{
    "form_completeness": "形态完整度评分（0-10分，看左右底/颈线/突破等要素是否齐全）",
    "volume_match": "量能配合度评分（0-10分，看量价配合是否符合该形态的特征）",
    "key_level_distance": "关键位距离评分（0-10分，价格越靠近触发位分数越高；离信号位太远=低分）"
  }},
  "confidence_upgrade_hint": "用一句话说明：满足什么条件可以让置信度从当前等级升到下一级（如：'价格突破颈线675并放量则升为高置信'）"
}}

请确保JSON格式正确，可以直接被程序解析。"""

    def _call_claude_api(self, prompt: str, max_tokens: int = 4000) -> Optional[str]:
        """调用 Claude API"""
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Claude API 调用异常: {e}")
            return None

    def _parse_json_response(self, raw_text: str) -> Dict:
        """解析LLM返回的JSON"""
        # 尝试从文本中提取JSON（可能包裹在 ```json ... ``` 中）
        text = raw_text.strip()

        # 去除代码块标记
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找第一个 { 和最后一个 }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass

            logger.error(f"JSON解析失败，原始响应: {raw_text[:500]}")
            return {
                "pattern_name": "解析失败",
                "pattern_state": "unknown",
                "summary": "LLM返回格式不正确，无法解析",
                "confidence": "low",
            }

    def _save_analysis(
        self, symbol: str, analysis_date: date,
        period: str, parsed: Dict, raw_response: str
    ) -> PatternAnalysis:
        """保存分析结果到数据库"""
        # 检查是否已存在
        existing = (
            self.db.query(PatternAnalysis)
            .filter_by(
                stock_symbol=symbol,
                analysis_date=analysis_date,
                period=period,
            )
            .first()
        )

        if existing:
            analysis = existing
        else:
            analysis = PatternAnalysis(
                stock_symbol=symbol,
                analysis_date=analysis_date,
                period=period,
            )
            self.db.add(analysis)

        # 填充字段
        analysis.pattern_name = parsed.get("pattern_name", "")
        analysis.pattern_state = parsed.get("pattern_state", "")
        analysis.summary = parsed.get("summary", "")
        analysis.confidence = parsed.get("confidence", "low")
        analysis.confidence_scores_json = json.dumps(
            parsed.get("confidence_scores", {}), ensure_ascii=False
        )
        analysis.confidence_upgrade_hint = parsed.get(
            "confidence_upgrade_hint", ""
        )
        analysis.raw_response = raw_response

        # JSON字段
        analysis.key_levels_json = json.dumps(
            parsed.get("key_levels", {}), ensure_ascii=False
        )
        analysis.detail_text = parsed.get("detail_text", "")

        # 关键价位
        targets = parsed.get("targets", {})
        analysis.strong_support = self._to_decimal(
            targets.get("stop_loss")
        )
        analysis.neckline = self._to_decimal(
            parsed.get("key_levels", {}).get("neckline")
        )
        analysis.target_1 = self._to_decimal(targets.get("target_1"))
        analysis.target_2 = self._to_decimal(targets.get("target_2"))
        analysis.stop_loss = self._to_decimal(targets.get("stop_loss"))

        # 验证JSON
        analysis.validation_json = json.dumps(
            parsed.get("validation", {}), ensure_ascii=False
        )

        # 持仓联动JSON
        analysis.actionable_json = json.dumps(
            parsed.get("actionable", {}), ensure_ascii=False
        )

        # 解析状态
        if analysis.pattern_name and analysis.pattern_name != "解析失败":
            analysis.parse_status = "success"
        else:
            analysis.parse_status = "fail"

        analysis.updated_at = datetime.now()
        self.db.commit()
        return analysis

    @staticmethod
    def _to_decimal(value) -> Optional[Decimal]:
        """将值转换为Decimal，支持从字符串中提取数字"""
        if value is None:
            return None

        import re

        text = str(value).strip()
        if not text:
            return None

        # 尝试直接转换
        try:
            return Decimal(text)
        except (ValueError, TypeError, Exception):
            pass

        # 从字符串中提取第一个数字（支持整数、小数、负数）
        match = re.search(r'-?\d+\.?\d*', text)
        if match:
            try:
                return Decimal(match.group())
            except (ValueError, TypeError):
                pass

        return None
