#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光剑系统 · 持仓体检报告生成脚本
从数据库生成 Markdown 格式的五维雷达体检报告
"""

import os
import sys
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import SessionLocal
from app.services.analysis_service import AnalysisService
from app.services.position_service import PositionService
from app.services.price_service import PriceService
from app.models.position import Position
from app.models.stock import Stock
from app.models.cash import CashBalance


def format_currency(value: float, currency: str = "CNY") -> str:
    """格式化货币显示"""
    if value >= 10000:
        return f"{value/10000:.1f}万"
    return f"{value:,.0f}"


def get_exchange_rate_cached(db, from_currency: str) -> float:
    """获取汇率"""
    price_service = PriceService(db)
    return price_service.get_exchange_rate(from_currency)


def generate_report_markdown(report_data: Dict, db) -> str:
    """
    根据 report_data 生成 Markdown 格式的持仓体检报告

    报告结构：
    1. 头部信息
    2. 总资产计算
    3. 五维雷达分析
    4. 行动建议
    """
    generated_at = report_data.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    date_str = generated_at[:10].replace("-", "")

    summary = report_data.get("summary", {})
    total_assets = summary.get("total_assets", 0)
    cash_value = summary.get("cash_value", 0)
    stock_value = summary.get("stock_value", 0)
    cash_ratio = summary.get("cash_ratio", 0)
    top3_ratio = summary.get("top3_ratio", 0)
    max_single_ratio = summary.get("single_max_ratio", 0)
    health_score = summary.get("health_score", 0)
    expected_return = summary.get("expected_return", 0)

    # 获取详细持仓数据
    position_service = PositionService(db)
    portfolio = position_service.get_portfolio_summary()
    markets_data = portfolio.get("markets", {})

    # 获取汇率
    hk_rate = get_exchange_rate_cached(db, "HKD")
    us_rate = get_exchange_rate_cached(db, "USD")

    lines = []

    # ========== 头部 ==========
    lines.append("# 光剑系统 · 五维雷达体检报告")
    lines.append(f"**日期**：{generated_at[:10]}")
    lines.append(f"**框架版本**：五维雷达 v1.0")
    lines.append(f"**数据来源**：港/美股 → 富途OpenD实时价格；A股 → 近期收盘价")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ========== 总资产计算 ==========
    lines.append("## 总资产计算")
    lines.append("")

    # 汇率
    lines.append("### 汇率")
    lines.append(f"- HKD/CNY = {hk_rate:.3f}")
    lines.append(f"- USD/CNY = {us_rate:.3f}")
    lines.append("")

    # 各市场持仓明细
    all_positions = []
    market_values = {}

    for market, data in markets_data.items():
        positions = data.get("positions", [])
        market_total = data.get("total_market_value", 0)
        market_cash = data.get("cash", 0)
        fund_value = data.get("fund_hkd", 0) or data.get("fund_usd", 0)
        exchange_rate = data.get("exchange_rate", 1.0)

        # 过滤出真实持仓（非现金）
        stock_positions = [p for p in positions if not p.get("is_cash")]

        if stock_positions:
            lines.append(f"### {market}股")
            lines.append("")
            lines.append("| 标的 | 股数 | 现价 | 市值(本地) |")
            lines.append("|------|------|------|-----------|")

            for pos in stock_positions:
                symbol = pos.get("symbol", "")
                name = pos.get("name", "")
                shares = pos.get("shares", 0)
                price = pos.get("price", 0)
                mv = pos.get("market_value", 0)
                currency = "HKD" if market == "HK" else ("USD" if market == "US" else "CNY")

                display_symbol = name if name else symbol
                lines.append(f"| {display_symbol} | {shares:,} | {price:,.2f} {currency} | {mv:,.0f} |")

                all_positions.append({
                    "symbol": symbol,
                    "name": name,
                    "market": market,
                    "shares": shares,
                    "price": price,
                    "market_value": mv,
                    "market_value_cny": mv * exchange_rate if market != "A" else mv,
                    "avg_cost": pos.get("avg_cost", 0),
                    "profit_pct": pos.get("profit_pct", 0),
                    "position_weight": pos.get("position_weight", 0),
                })

            # 市场合计
            currency = "HKD" if market == "HK" else ("USD" if market == "US" else "CNY")
            total_with_fund = market_total + fund_value
            total_cny = (total_with_fund + market_cash) * exchange_rate if market != "A" else (total_with_fund + market_cash)

            lines.append(f"| **{market}股持仓合计** | | | **{market_total:,.0f} {currency}** |")
            lines.append("")

            if market_cash > 0:
                lines.append(f"{market}股现金：{market_cash:,.0f} {currency}")
            if fund_value > 0:
                fund_currency = "HKD" if market == "HK" else "USD"
                lines.append(f"{market}股货基：{fund_value:,.0f} {fund_currency}")

            lines.append(f"**{market}股合计：{total_with_fund + market_cash:,.0f} {currency} ≈ CNY {format_currency(total_cny)}**")
            lines.append("")

            market_values[market] = {
                "total": total_cny,
                "cash": market_cash * exchange_rate if market != "A" else market_cash,
                "fund": fund_value * exchange_rate if market != "A" else 0,
                "stocks": market_total * exchange_rate if market != "A" else market_total,
            }

    # 总资产汇总表
    lines.append("### 总资产汇总")
    lines.append("")
    lines.append("| 市场 | 折合CNY | 占比 |")
    lines.append("|------|---------|------|")

    total_cny = sum(m["total"] for m in market_values.values())
    for market, values in market_values.items():
        pct = values["total"] / total_cny * 100 if total_cny > 0 else 0
        lines.append(f"| {market}股 | {format_currency(values['total'])} | {pct:.1f}% |")

    lines.append(f"| **总计** | **{format_currency(total_cny)}** | 100% |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ========== 五维雷达分析 ==========

    # 维度一：集中度风险
    lines.append("## ▌ 维度一：集中度风险")
    lines.append("")

    # 主要持仓占比
    lines.append("### 主要持仓占比")
    lines.append("")
    lines.append(f"| 标的 | 市值CNY | 占比 |")
    lines.append(f"|------|---------|------|")

    all_positions.sort(key=lambda x: x.get("market_value_cny", 0), reverse=True)
    for pos in all_positions[:10]:
        name = pos.get("name") or pos.get("symbol", "")
        mv_cny = pos.get("market_value_cny", 0)
        weight = pos.get("position_weight", 0)
        lines.append(f"| {name} | {format_currency(mv_cny)} | {weight:.1f}% |")

    # 现金
    cash_pct = cash_value / total_assets * 100 if total_assets > 0 else 0
    lines.append(f"| 现金/货基 | {format_currency(cash_value)} | {cash_pct:.1f}% |")
    lines.append("")

    # 集中度指标
    lines.append("| 指标 | 数值 | 状态 |")
    lines.append("|------|------|------|")

    hhi_status = "🟢" if max_single_ratio < 25 else "🔴"
    lines.append(f"| 最大单股占比 | {max_single_ratio:.1f}% | {hhi_status} {'< 25%警戒线' if max_single_ratio < 25 else '> 25%警戒线'} |")

    top3_status = "🟢" if top3_ratio < 50 else "🟡" if top3_ratio < 60 else "🔴"
    lines.append(f"| TOP3集中度 | {top3_ratio:.1f}% | {top3_status} |")

    cash_status = "🟢" if 5 <= cash_ratio <= 15 else "🟡"
    lines.append(f"| 现金比例 | {cash_ratio:.1f}% | {cash_status} {'目标区间5-15%' if 5 <= cash_ratio <= 15 else '偏离目标区间'} |")
    lines.append("")

    lines.append(f"**集中度结论**：{hhi_status} 整体{'健康' if max_single_ratio < 25 else '需关注'}，最大持仓{max_single_ratio:.1f}%，现金比例{cash_ratio:.1f}%。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 维度二：波段仓状态
    lines.append("## ▌ 维度二：波段仓状态")
    lines.append("")

    # 识别波段仓（简化逻辑：负收益或标记为波段）
    swing_positions = [p for p in all_positions if p.get("profit_pct", 0) < -5]

    if swing_positions:
        lines.append("| 波段仓 | 成本 | 现价 | 盈亏 | 状态 |")
        lines.append("|--------|------|------|------|------|")

        for pos in swing_positions[:5]:
            name = pos.get("name") or pos.get("symbol", "")
            avg_cost = pos.get("avg_cost", 0)
            price = pos.get("price", 0)
            profit_pct = pos.get("profit_pct", 0)
            currency = "HKD" if pos.get("market") == "HK" else ("USD" if pos.get("market") == "US" else "CNY")

            status = "🔴 深度被套" if profit_pct < -15 else ("🟡 小幅被套" if profit_pct < -8 else "⚠️ 浮亏")
            lines.append(f"| {name} | {avg_cost:,.2f} {currency} | {price:,.2f} {currency} | **{profit_pct:+.1f}%** | {status} |")

        lines.append("")
        lines.append("**注意**：深度被套仓位需关注止损位设置，避免亏损进一步扩大。")
    else:
        lines.append("当前无显著浮亏波段仓位。")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 维度三：投资逻辑验证
    lines.append("## ▌ 维度三：投资逻辑验证")
    lines.append("")

    lines.append("### 重点持仓逻辑标签")
    lines.append("")
    lines.append("| 标的 | 标签 | 逻辑状态 | 备注 |")
    lines.append("|------|------|---------|------|")

    # 基于数据生成逻辑标签（简化版）
    for pos in all_positions[:8]:
        name = pos.get("name") or pos.get("symbol", "")
        profit_pct = pos.get("profit_pct", 0)
        weight = pos.get("position_weight", 0)

        if weight > 15:
            tag = "核心底仓"
            status = "✅" if profit_pct > -10 else "⚠️"
            note = "高权重持仓，需持续跟踪" if profit_pct > -10 else "高权重但浮亏，需关注"
        elif profit_pct > 20:
            tag = "动量型"
            status = "✅"
            note = "盈利可观"
        elif profit_pct < -10:
            tag = "波段修复"
            status = "⚠️"
            note = "被套中，需明确止损位"
        else:
            tag = "配置型"
            status = "🟡"
            note = "正常持有"

        lines.append(f"| {name} | {tag} | {status} | {note} |")

    lines.append("")

    # 行为自查
    lines.append("### 行为自查")
    lines.append("")
    lines.append("1. **上期有没有在大涨后加仓？** 需人工复核交易记录")
    lines.append("2. **波段有没有该止损没止的？** 检查上述🔴标记仓位")
    lines.append("3. **有没有持仓'放着不看'超3个月？** 需人工评估")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 维度四：归因分析
    lines.append("## ▌ 维度四：归因分析")
    lines.append("")
    lines.append("本期为常规体检，详细归因分析建议季度深度复盘时进行。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 维度五：组合健康度预判
    lines.append("## ▌ 维度五：组合健康度预判")
    lines.append("")

    # 现金合理性
    lines.append("### 现金合理性")
    lines.append("")
    lines.append(f"| 指标 | 数值 | 评估 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| 现金+货基 | {format_currency(cash_value)} | 占比 {cash_ratio:.1f}% |")
    lines.append(f"| 目标区间 | 5-15% | {'🟢 在区间内' if 5 <= cash_ratio <= 15 else '🟡 偏离区间'} |")
    lines.append("")

    # 预期收益
    lines.append("### 组合预期收益估算")
    lines.append("")
    lines.append(f"| 指标 | 数值 | 评估 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| 预期年化收益 | ~{expected_return:.1f}% | 基于当前持仓加权估算 |")
    lines.append(f"| 目标收益 | 25% | {'🟢 接近目标' if expected_return >= 20 else '🟡 有差距' if expected_return >= 15 else '🔴 差距较大'} |")
    lines.append(f"| 健康度评分 | {health_score}/100 | {'🟢 健康' if health_score >= 70 else '🟡 一般' if health_score >= 50 else '🔴 需关注'} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ========== 行动建议 ==========
    lines.append("## 本期行动建议")
    lines.append("")

    actions = report_data.get("actions", [])
    if actions:
        lines.append("### P0 近期优先")
        lines.append("")
        for i, action in enumerate(actions[:3], 1):
            symbol = action.get("symbol", "")
            action_type = action.get("action", "")
            reason = action.get("reason", "")
            lines.append(f"{i}. **{symbol} - {action_type}**：{reason}")
        lines.append("")

    # 风险警告转建议
    risk_warnings = report_data.get("risk_warnings", [])
    if risk_warnings:
        lines.append("### P1 风险关注")
        lines.append("")
        for warning in risk_warnings[:3]:
            lines.append(f"- ⚠️ {warning}")
        lines.append("")

    lines.append("### P2 持续监控")
    lines.append("")
    lines.append("| 标的 | 监控指标 | 警戒线 |")
    lines.append("|------|---------|-------|")

    for pos in all_positions[:5]:
        name = pos.get("name") or pos.get("symbol", "")
        profit_pct = pos.get("profit_pct", 0)
        if profit_pct < 0:
            stop_loss = pos.get("price", 0) * 0.92  # 假设8%止损
            lines.append(f"| {name} | 现价 | < {stop_loss:.2f} 触发止损 |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 尾部
    lines.append("*生成时间：" + generated_at + " | 框架：五维雷达 v1.0*")

    return "\n".join(lines)


def main():
    """主函数：生成报告并保存"""
    db = SessionLocal()

    try:
        print("正在生成持仓体检报告...")

        # 获取报告数据
        analysis_service = AnalysisService(db)
        report_data = analysis_service.generate_health_check_report()

        # 生成 Markdown
        markdown_content = generate_report_markdown(report_data, db)

        # 保存文件
        date_str = datetime.now().strftime("%Y%m%d")
        docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
        os.makedirs(docs_dir, exist_ok=True)

        file_path = os.path.join(docs_dir, f"持仓体检报告_{date_str}.md")

        # 检查文件是否已存在（避免覆盖）
        if os.path.exists(file_path):
            # 添加时间戳后缀
            time_str = datetime.now().strftime("%H%M%S")
            file_path = os.path.join(docs_dir, f"持仓体检报告_{date_str}_{time_str}.md")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"✅ 报告已生成：{file_path}")
        print(f"   总资产：{report_data.get('summary', {}).get('total_assets', 0):,.0f} CNY")
        print(f"   现金比例：{report_data.get('summary', {}).get('cash_ratio', 0):.1f}%")
        print(f"   健康评分：{report_data.get('summary', {}).get('health_score', 0)}/100")

        return file_path

    except Exception as e:
        print(f"❌ 生成报告失败：{e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        db.close()


if __name__ == "__main__":
    main()
