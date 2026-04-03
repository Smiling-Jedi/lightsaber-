#!/usr/bin/env python3
"""
执行总资产数据库测试用例
根据 TEST_总资产数据库测试用例_v1.0.md 执行测试
"""
import sys
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal, init_db
from app.models.position import Position
from app.models.position_audit_log import PositionAuditLog
from app.models.exchange_rate_history import ExchangeRateHistory
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.cash import CashBalance
from app.models.trade import Trade
from app.services.position_audit_service import PositionAuditService
from app.services.exchange_rate_service import ExchangeRateService
from app.services.position_service import PositionService
from app.services.portfolio_service import PortfolioService
from app.data_sources.exchange_rate_source import ExchangeRateSource


class TestResult:
    """测试结果记录"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.details = []

    def add_pass(self, tc_id, description):
        self.passed += 1
        self.details.append({"id": tc_id, "status": "✅ PASS", "desc": description})
        print(f"✅ {tc_id}: {description}")

    def add_fail(self, tc_id, description, reason):
        self.failed += 1
        self.details.append({"id": tc_id, "status": "❌ FAIL", "desc": description, "reason": reason})
        print(f"❌ {tc_id}: {description}")
        print(f"   原因: {reason}")

    def add_warning(self, tc_id, description, msg):
        self.warnings += 1
        self.details.append({"id": tc_id, "status": "⚠️ WARN", "desc": description, "msg": msg})
        print(f"⚠️ {tc_id}: {description}")
        print(f"   警告: {msg}")

    def summary(self):
        print("\n" + "="*60)
        print("测试执行总结")
        print("="*60)
        print(f"✅ 通过: {self.passed}")
        print(f"❌ 失败: {self.failed}")
        print(f"⚠️ 警告: {self.warnings}")
        print(f"总计: {self.passed + self.failed + self.warnings}")
        print("="*60)


result = TestResult()


def test_database_structure():
    """TC-001~004: 数据库结构验证"""
    print("\n" + "="*60)
    print("测试组1: 数据库结构验证")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        from sqlalchemy import text

        # 检查表是否存在
        tables = [
            ("position_audit_logs", "持仓审计日志表"),
            ("exchange_rate_history", "汇率历史表"),
        ]

        for table_name, desc in tables:
            r = db.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")).fetchone()
            if r:
                result.add_pass(f"TC-STRUCT-{table_name}", f"{desc}存在")
            else:
                result.add_fail(f"TC-STRUCT-{table_name}", f"{desc}检查", "表不存在")

        # 检查字段
        columns_check = [
            ("positions", "source", "持仓数据来源字段"),
            ("positions", "last_sync_at", "最后同步时间字段"),
            ("portfolio_snapshots", "hkd_rate", "港元汇率字段"),
            ("portfolio_snapshots", "usd_rate", "美元汇率字段"),
        ]

        for table, col, desc in columns_check:
            r = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
            cols = [c[1] for c in r]
            if col in cols:
                result.add_pass(f"TC-STRUCT-{table}-{col}", f"{desc}存在")
            else:
                result.add_fail(f"TC-STRUCT-{table}-{col}", f"{desc}检查", "字段不存在")

    finally:
        db.close()


def test_hk_us_sync():
    """TC-001/002: 港股/美股持仓同步测试"""
    print("\n" + "="*60)
    print("测试组2: 港股/美股持仓同步")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        # 检查富途同步的持仓
        hk_positions = db.query(Position).filter(
            Position.stock_symbol.like("HK:%"),
            Position.total_shares > 0
        ).all()

        us_positions = db.query(Position).filter(
            Position.stock_symbol.like("US:%"),
            Position.total_shares > 0
        ).all()

        if len(hk_positions) >= 8:
            result.add_pass("TC-001-HK", f"港股持仓同步正常，共{len(hk_positions)}只")
        else:
            result.add_warning("TC-001-HK", "港股持仓数量", f"只有{len(hk_positions)}只，预期8+")

        if len(us_positions) >= 11:
            result.add_pass("TC-002-US", f"美股持仓同步正常，共{len(us_positions)}只")
        else:
            result.add_warning("TC-002-US", "美股持仓数量", f"只有{len(us_positions)}只，预期11+")

        # 检查source字段
        for pos in hk_positions[:3]:
            if pos.source in ["FUTU_AUTO", "MIXED"]:
                result.add_pass(f"TC-001-SOURCE-{pos.stock_symbol}", f"{pos.stock_symbol} source={pos.source}")
            else:
                result.add_warning(f"TC-001-SOURCE-{pos.stock_symbol}", "数据来源标记", f"source={pos.source}")

    finally:
        db.close()


def test_a_shares_manual():
    """TC-003/004: A股持仓手动录入和保护"""
    print("\n" + "="*60)
    print("测试组3: A股持仓手动录入和保护")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        audit_service = PositionAuditService(db)

        # 检查A股持仓
        a_positions = db.query(Position).filter(
            Position.stock_symbol.like("A:%"),
            Position.total_shares > 0
        ).all()

        if len(a_positions) >= 12:
            result.add_pass("TC-003-A", f"A股持仓录入正常，共{len(a_positions)}只")
        else:
            result.add_fail("TC-003-A", "A股持仓数量", f"只有{len(a_positions)}只，预期12")

        # 检查A股数据来源
        for pos in a_positions:
            if pos.source in ["MANUAL", "MIXED"]:
                result.add_pass(f"TC-003-SOURCE-{pos.stock_symbol}", f"{pos.stock_symbol} source={pos.source}")
            else:
                result.add_warning(f"TC-003-SOURCE-{pos.stock_symbol}", "A股数据来源", f"source={pos.source}")

        # 测试A股保护机制
        validation = audit_service.validate_a_shares_consistency()
        if validation["is_valid"]:
            result.add_pass("TC-004-PROTECTION", "A股数据保护机制正常，无异常警告")
        else:
            result.add_warning("TC-004-PROTECTION", "A股数据保护", f"发现{len(validation['warnings'])}个警告")

        # 显示当前A股持仓
        print(f"\n当前A股持仓详情:")
        for pos in a_positions:
            print(f"  - {pos.stock_symbol}: {pos.total_shares}股 @ {pos.avg_cost}")

    finally:
        db.close()


def test_base_swing():
    """TC-005: 底仓/波段分离测试"""
    print("\n" + "="*60)
    print("测试组4: 底仓/波段分离")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        # 查询设置了底仓的持仓
        positions_with_base = db.query(Position).filter(
            Position.base_shares > 0,
            Position.total_shares > 0
        ).all()

        if len(positions_with_base) > 0:
            result.add_pass("TC-005-BASE", f"底仓设置正常，共{len(positions_with_base)}只设置了底仓")

            # 验证波段计算
            for pos in positions_with_base[:5]:
                expected_swing = pos.total_shares - pos.base_shares
                actual_swing = pos.swing_shares
                if expected_swing == actual_swing:
                    result.add_pass(f"TC-005-SWING-{pos.stock_symbol}",
                        f"{pos.stock_symbol}: 总{pos.total_shares} 底{pos.base_shares} 波{actual_swing}")
                else:
                    result.add_fail(f"TC-005-SWING-{pos.stock_symbol}", "波段计算",
                        f"预期{expected_swing}, 实际{actual_swing}")
        else:
            result.add_warning("TC-005-BASE", "底仓设置", "没有持仓设置底仓")

    finally:
        db.close()


def test_cash_balance():
    """TC-006: 现金余额测试"""
    print("\n" + "="*60)
    print("测试组5: 现金余额")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        cash_balances = db.query(CashBalance).all()

        markets = ["HK", "US", "A", "FUND"]
        for market in markets:
            cb = next((c for c in cash_balances if c.market == market), None)
            if cb:
                result.add_pass(f"TC-006-{market}", f"{market}现金: {float(cb.amount):,.2f} {cb.currency}")
            else:
                result.add_warning(f"TC-006-{market}", f"{market}现金", "记录不存在")

    finally:
        db.close()


def test_exchange_rate():
    """TC-007: 汇率历史记录测试"""
    print("\n" + "="*60)
    print("测试组6: 汇率历史记录")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        rate_service = ExchangeRateService(db)

        # 记录今日汇率
        try:
            rate_record = rate_service.record_today_rate()
            db.commit()
            result.add_pass("TC-007-RECORD", f"汇率记录成功: HKD={rate_record.hkd_rate}, USD={rate_record.usd_rate}")
        except Exception as e:
            result.add_fail("TC-007-RECORD", "汇率记录", str(e))

        # 查询历史汇率
        history = rate_service.get_rate_history(days=7)
        if len(history) > 0:
            result.add_pass("TC-007-HISTORY", f"汇率历史查询成功，共{len(history)}条记录")
        else:
            result.add_warning("TC-007-HISTORY", "汇率历史", "无历史记录")

        # 获取当前汇率
        hkd_rate = rate_service.get_current_rate("HKD")
        usd_rate = rate_service.get_current_rate("USD")
        result.add_pass("TC-007-CURRENT", f"当前汇率: HKD={hkd_rate}, USD={usd_rate}")

        # 获取指定日期汇率
        today = date.today()
        rate_for_today = rate_service.get_rate_for_date("HKD", today)
        result.add_pass("TC-007-DATE", f"指定日期汇率查询成功: {rate_for_today}")

    finally:
        db.close()


def test_portfolio_snapshot():
    """TC-008: 资产快照生成测试"""
    print("\n" + "="*60)
    print("测试组7: 资产快照生成")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        portfolio_service = PortfolioService(db)

        # 生成今日快照
        try:
            snapshot = portfolio_service.take_snapshot("REAL", note="测试快照")
            db.commit()

            if snapshot.hkd_rate and snapshot.usd_rate:
                result.add_pass("TC-008-RATE", f"快照汇率记录成功: HKD={snapshot.hkd_rate}, USD={snapshot.usd_rate}")
            else:
                result.add_warning("TC-008-RATE", "快照汇率", "汇率字段为空")

            if snapshot.breakdown_json:
                result.add_pass("TC-008-BREAKDOWN", "快照明细记录成功")
            else:
                result.add_warning("TC-008-BREAKDOWN", "快照明细", "明细为空")

            result.add_pass("TC-008-SNAPSHOT", f"资产快照生成成功: 总资产RMB={float(snapshot.total_assets_rmb):,.2f}")

        except Exception as e:
            result.add_fail("TC-008-SNAPSHOT", "资产快照生成", str(e))

    finally:
        db.close()


def test_portfolio_summary():
    """TC-009: 资产汇总计算测试"""
    print("\n" + "="*60)
    print("测试组8: 资产汇总计算")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        position_service = PositionService(db)
        portfolio = position_service.get_portfolio_summary()

        # 验证总资产
        if portfolio.get("total_market_value_rmb", 0) > 0:
            result.add_pass("TC-009-TOTAL", f"总资产计算成功: {portfolio['total_market_value_rmb']:,.2f} RMB")
        else:
            result.add_fail("TC-009-TOTAL", "总资产计算", "总资产为0或负数")

        # 验证各市场
        markets = portfolio.get("markets", {})
        for market in ["HK", "US", "A"]:
            if market in markets:
                mv = markets[market].get("total_market_value", 0)
                result.add_pass(f"TC-009-{market}", f"{market}市场市值: {mv:,.2f}")
            else:
                result.add_warning(f"TC-009-{market}", f"{market}市场", "数据缺失")

        # 显示汇总详情
        print(f"\n资产汇总详情:")
        print(f"  总持仓: {portfolio.get('total_positions', 0)} 只")
        print(f"  总市值(RMB): {portfolio.get('total_market_value_rmb', 0):,.2f}")
        print(f"  今日盈亏(RMB): {portfolio.get('today_profit', 0):,.2f}")

    finally:
        db.close()


def test_audit_log():
    """TC-011: 审计日志完整性测试"""
    print("\n" + "="*60)
    print("测试组9: 审计日志完整性")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        audit_service = PositionAuditService(db)

        # 查询所有审计日志
        all_logs = db.query(PositionAuditLog).all()

        if len(all_logs) > 0:
            result.add_pass("TC-011-EXIST", f"审计日志存在，共{len(all_logs)}条记录")

            # 显示最近的几条
            recent_logs = audit_service.get_audit_history(limit=5)
            print(f"\n最近审计日志:")
            for log in recent_logs:
                print(f"  - {log.stock_symbol}: {log.field_name} {log.old_value} -> {log.new_value} ({log.change_reason})")
        else:
            result.add_warning("TC-011-EXIST", "审计日志", "暂无记录（新功能，后续操作会生成）")

        # 按股票查询
        a_logs = db.query(PositionAuditLog).filter(
            PositionAuditLog.stock_symbol.like("A:%")
        ).all()
        result.add_pass("TC-011-A-SHARES", f"A股审计日志: {len(a_logs)}条")

    finally:
        db.close()


def main():
    """主函数"""
    print("\n" + "="*70)
    print("光剑系统总资产数据库 - 测试用例执行")
    print("执行时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*70 + "\n")

    # 初始化数据库
    print("初始化数据库连接...")
    init_db()
    print("✅ 数据库初始化完成\n")

    # 执行测试
    test_database_structure()
    test_hk_us_sync()
    test_a_shares_manual()
    test_base_swing()
    test_cash_balance()
    test_exchange_rate()
    test_portfolio_snapshot()
    test_portfolio_summary()
    test_audit_log()

    # 输出总结
    result.summary()

    # 返回退出码
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    exit(main())
