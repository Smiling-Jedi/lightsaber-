#!/usr/bin/env python3
"""
数据库优化测试脚本
验证新表结构和审计功能是否正常工作
"""
import sys
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.models.position import Position
from app.models.position_audit_log import PositionAuditLog
from app.models.exchange_rate_history import ExchangeRateHistory
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.cash import CashBalance
from app.services.position_audit_service import PositionAuditService
from app.services.exchange_rate_service import ExchangeRateService
from app.services.position_service import PositionService
from sqlalchemy import text


def test_database_structure():
    """测试数据库结构是否正确"""
    print("=" * 60)
    print("测试1: 数据库结构验证")
    print("=" * 60)

    db = SessionLocal()
    try:
        # 检查新表是否存在
        tables = [
            ("position_audit_logs", "持仓审计日志表"),
            ("exchange_rate_history", "汇率历史表"),
        ]

        for table_name, desc in tables:
            result = db.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")).fetchone()
            if result:
                print(f"✅ {desc} ({table_name}) 存在")
            else:
                print(f"❌ {desc} ({table_name}) 不存在")

        # 检查新字段是否存在
        columns_to_check = [
            ("positions", "source", "持仓数据来源"),
            ("positions", "last_sync_at", "最后同步时间"),
            ("portfolio_snapshots", "hkd_rate", "港元汇率"),
            ("portfolio_snapshots", "usd_rate", "美元汇率"),
        ]

        for table, column, desc in columns_to_check:
            result = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
            column_names = [col[1] for col in result]
            if column in column_names:
                print(f"✅ {desc} ({table}.{column}) 存在")
            else:
                print(f"❌ {desc} ({table}.{column}) 不存在")

    finally:
        db.close()

    print()


def test_audit_log():
    """测试审计日志功能"""
    print("=" * 60)
    print("测试2: 审计日志功能")
    print("=" * 60)

    db = SessionLocal()
    try:
        audit_service = PositionAuditService(db)

        # 找一个测试持仓
        position = db.query(Position).filter(Position.total_shares > 0).first()
        if not position:
            print("⚠️ 没有找到持仓记录，跳过审计日志测试")
            return

        print(f"使用持仓: {position.stock_symbol}, 当前股数: {position.total_shares}")

        # 记录一个测试变更
        old_shares = position.total_shares
        audit_service.log_change(
            position=position,
            field_name="total_shares",
            old_value=old_shares,
            new_value=old_shares,
            change_reason="TEST",
            source="SCRIPT"
        )
        db.commit()

        # 查询审计日志
        logs = audit_service.get_audit_history(
            stock_symbol=position.stock_symbol,
            limit=5
        )

        if logs:
            print(f"✅ 审计日志记录成功，共 {len(logs)} 条记录")
            for log in logs[:3]:
                print(f"   - {log.stock_symbol}: {log.field_name} {log.old_value} -> {log.new_value} ({log.source})")
        else:
            print("⚠️ 没有找到审计日志记录")

    finally:
        db.close()

    print()


def test_exchange_rate():
    """测试汇率服务"""
    print("=" * 60)
    print("测试3: 汇率服务功能")
    print("=" * 60)

    db = SessionLocal()
    try:
        rate_service = ExchangeRateService(db)

        # 记录今日汇率
        rate_record = rate_service.record_today_rate()
        db.commit()

        print(f"✅ 今日汇率记录成功")
        print(f"   - 日期: {rate_record.date}")
        print(f"   - 港元汇率: {rate_record.hkd_rate}")
        print(f"   - 美元汇率: {rate_record.usd_rate}")

        # 查询历史汇率
        history = rate_service.get_rate_history(days=7)
        print(f"✅ 查询汇率历史成功，共 {len(history)} 条记录")

        # 获取当前汇率
        hkd_rate = rate_service.get_current_rate("HKD")
        usd_rate = rate_service.get_current_rate("USD")
        print(f"✅ 当前汇率: HKD={hkd_rate}, USD={usd_rate}")

    finally:
        db.close()

    print()


def test_a_shares_protection():
    """测试A股数据保护"""
    print("=" * 60)
    print("测试4: A股数据保护机制")
    print("=" * 60)

    db = SessionLocal()
    try:
        audit_service = PositionAuditService(db)

        # 检查A股持仓一致性
        result = audit_service.validate_a_shares_consistency()

        print(f"✅ A股持仓验证完成")
        print(f"   - 当前A股持仓数量: {result['current_a_positions']}")
        print(f"   - 是否通过验证: {result['is_valid']}")

        if result['warnings']:
            print(f"   ⚠️ 警告 ({len(result['warnings'])}):")
            for warning in result['warnings']:
                print(f"      - {warning['message']}")
        else:
            print("   - 没有发现异常")

    finally:
        db.close()

    print()


def test_position_data_integrity():
    """测试持仓数据完整性"""
    print("=" * 60)
    print("测试5: 持仓数据完整性")
    print("=" * 60)

    db = SessionLocal()
    try:
        # 统计各市场持仓
        positions = db.query(Position).filter(Position.total_shares > 0).all()

        market_stats = {"A": 0, "HK": 0, "US": 0}
        total_value = {"A": Decimal("0"), "HK": Decimal("0"), "US": Decimal("0")}

        for pos in positions:
            market = pos.stock_symbol.split(":")[0]
            if market in market_stats:
                market_stats[market] += 1
                if pos.stock and pos.stock.current_price:
                    value = pos.total_shares * pos.stock.current_price
                    total_value[market] += value

        print(f"✅ 持仓统计:")
        print(f"   - A股: {market_stats['A']} 只, 市值约 {float(total_value['A']):,.0f} CNY")
        print(f"   - 港股: {market_stats['HK']} 只, 市值约 {float(total_value['HK']):,.0f} HKD")
        print(f"   - 美股: {market_stats['US']} 只, 市值约 {float(total_value['US']):,.0f} USD")

        # 检查底仓/波段数据
        positions_with_base = db.query(Position).filter(Position.base_shares > 0).count()
        print(f"✅ 设置了底仓的持仓: {positions_with_base} 只")

        # 检查现金余额
        cash_balances = db.query(CashBalance).all()
        print(f"✅ 现金余额记录:")
        for cb in cash_balances:
            print(f"   - {cb.market}: {float(cb.amount):,.2f} {cb.currency}")

    finally:
        db.close()

    print()


def test_portfolio_summary():
    """测试资产汇总功能"""
    print("=" * 60)
    print("测试6: 资产汇总功能")
    print("=" * 60)

    db = SessionLocal()
    try:
        position_service = PositionService(db)
        portfolio = position_service.get_portfolio_summary()

        print(f"✅ 资产汇总计算成功")
        print(f"   - 总持仓数量: {portfolio['total_positions']}")
        print(f"   - 总市值(RMB): {portfolio['total_market_value_rmb']:,.2f}")
        print(f"   - 今日盈亏(RMB): {portfolio['today_profit']:,.2f}")

        # 各市场统计
        for market, data in portfolio.get('markets', {}).items():
            print(f"   - {market}: 市值 {data['total_market_value']:,.2f}, 现金 {data.get('cash', 0):,.2f}")

    finally:
        db.close()

    print()


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("光剑系统数据库优化测试")
    print("=" * 60 + "\n")

    # 初始化数据库
    print("初始化数据库...")
    init_db()
    print("✅ 数据库初始化完成\n")

    # 运行各项测试
    test_database_structure()
    test_audit_log()
    test_exchange_rate()
    test_a_shares_protection()
    test_position_data_integrity()
    test_portfolio_summary()

    print("=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
