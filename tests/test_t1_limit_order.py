"""
T+1限价单模式测试用例

测试范围:
1. SignalService._calculate_limit_price - 各类策略limit_price计算
2. SignalLogService.save_signal_simulated - BUY信号保存逻辑
3. SignalExecutionService - T+1成交检查全流程
4. 边界情况和异常处理
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import datetime, date, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock

from app.core.database import Base
from app.models.signal_log import SignalLog
from app.models.sim_position import SimPosition
from app.models.stock import Stock
from app.models.position import Position
from app.services.signal_service import SignalService, TradeInstruction, SignalResult
from app.services.signal_log_service import SignalLogService
from app.services.signal_execution_service import SignalExecutionService


class TestCalculateLimitPrice:
    """测试各类策略的limit_price计算"""

    @pytest.fixture
    def signal_service(self, db):
        return SignalService(db)

    def test_cyclical_strategy(self, signal_service):
        """cyclical策略: limit_price = T日收盘价"""
        close_price = 355.28
        indicators = {"bb_lower": 359.49}

        result = signal_service._calculate_limit_price(close_price, "cyclical", indicators)

        assert result == 355.28
        assert isinstance(result, float)

    def test_defensive_strategy(self, signal_service):
        """defensive策略: limit_price = 布林下轨"""
        close_price = 270.0
        indicators = {"bb_lower": 266.0}

        result = signal_service._calculate_limit_price(close_price, "defensive", indicators)

        assert result == 266.0

    def test_large_tech_strategy(self, signal_service):
        """large_tech策略: limit_price = T日收盘价 × 102%"""
        close_price = 420.0
        indicators = {"bb_lower": 410.0}

        result = signal_service._calculate_limit_price(close_price, "large_tech", indicators)

        assert result == 428.40  # 420 * 1.02

    def test_biotech_strategy(self, signal_service):
        """biotech策略: limit_price = T日收盘价 × 102%"""
        close_price = 15.0
        indicators = {"bb_lower": 14.5}

        result = signal_service._calculate_limit_price(close_price, "biotech", indicators)

        assert result == 15.30  # 15 * 1.02

    def test_unknown_strategy_defaults_to_close(self, signal_service):
        """未知策略类型默认使用收盘价"""
        close_price = 100.0
        indicators = {"bb_lower": 95.0}

        result = signal_service._calculate_limit_price(close_price, "unknown", indicators)

        assert result == 100.0

    def test_missing_bb_lower_defaults_to_close(self, signal_service):
        """缺少bb_lower时默认使用收盘价"""
        close_price = 100.0
        indicators = {}

        result = signal_service._calculate_limit_price(close_price, "defensive", indicators)

        assert result == 100.0


class TestSignalExecutionPriceCalculation:
    """测试T+1成交价计算逻辑"""

    @pytest.fixture
    def execution_service(self, db):
        return SignalExecutionService(db)

    def test_open_price_below_limit(self, execution_service):
        """场景A: 开盘直接低于limit_price → 按开盘价成交"""
        t1_open = 350.0
        t1_low = 345.0
        limit_price = 355.28

        result = execution_service._calculate_execute_price(t1_open, t1_low, limit_price)

        assert result == 350.0

    def test_open_price_above_limit_low_below(self, execution_service):
        """场景B: 开盘高于limit，但盘中跌破 → 按limit_price成交"""
        t1_open = 358.0
        t1_low = 345.0
        limit_price = 355.28

        result = execution_service._calculate_execute_price(t1_open, t1_low, limit_price)

        assert result == 355.28

    def test_open_equal_to_limit(self, execution_service):
        """开盘等于limit_price → 按limit_price成交"""
        t1_open = 355.28
        t1_low = 350.0
        limit_price = 355.28

        result = execution_service._calculate_execute_price(t1_open, t1_low, limit_price)

        assert result == 355.28

    def test_result_rounded_to_2_decimals(self, execution_service):
        """成交价保留2位小数"""
        t1_open = 350.555
        t1_low = 345.0
        limit_price = 355.28

        result = execution_service._calculate_execute_price(t1_open, t1_low, limit_price)

        assert result == 350.56  # 四舍五入到2位小数


class TestT1ExecutionFlow:
    """测试T+1成交检查全流程"""

    @pytest.fixture
    def setup_test_data(self, db):
        """设置测试数据: 股票和信号"""
        # 创建测试股票
        stock = Stock(
            symbol="US:TSLA",
            name="Tesla",
            market="US",
            currency="USD",
            current_price=358.0,
            open_price=350.0,
            high_price=360.0,
            low_price=345.0,
            price_updated_at=datetime.now()
        )
        db.add(stock)

        # 创建PENDING BUY信号
        yesterday = date.today() - timedelta(days=1)
        signal = SignalLog(
            symbol="US:TSLA",
            name="Tesla",
            category="cyclical",
            generated_at=datetime.combine(yesterday, datetime.min.time()),
            action="BUY",
            confidence="HIGH",
            entry_price=355.28,
            stop_loss_pct=-7.0,
            target_pct=25.0,
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=355.28,
            recommended_shares=100,
            recommended_shares_second=100,
        )
        db.add(signal)
        db.commit()

        return {"stock": stock, "signal": signal}

    def test_check_pending_signals_executes_when_low_below_limit(self, db, setup_test_data):
        """测试: 最低价 <= limit_price 时成交"""
        service = SignalExecutionService(db)
        yesterday = date.today() - timedelta(days=1)

        results = service.check_pending_signals(target_date=yesterday)

        assert results["checked"] == 1
        assert results["executed"] == 1
        assert results["expired"] == 0

        # 验证信号状态
        signal = db.query(SignalLog).filter(SignalLog.symbol == "US:TSLA").first()
        assert signal.entered is True
        assert signal.entered_price == 350.0  # 开盘价低于limit，按开盘成交
        assert signal.t1_low_price == 345.0
        assert signal.t1_open_price == 350.0

    def test_check_pending_signals_expires_when_low_above_limit(self, db):
        """测试: 最低价 > limit_price 时过期"""
        # 设置股票价格（最低价高于limit）
        stock = Stock(
            symbol="HK:00700",
            name="腾讯控股",
            market="HK",
            currency="HKD",
            current_price=433.0,
            open_price=430.0,
            high_price=435.0,
            low_price=429.0,  # 高于limit_price
            price_updated_at=datetime.now()
        )
        db.add(stock)

        yesterday = date.today() - timedelta(days=1)
        signal = SignalLog(
            symbol="HK:00700",
            name="腾讯控股",
            category="large_tech",
            generated_at=datetime.combine(yesterday, datetime.min.time()),
            action="BUY",
            confidence="HIGH",
            entry_price=420.0,
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=428.40,  # 420 * 1.02
        )
        db.add(signal)
        db.commit()

        service = SignalExecutionService(db)
        results = service.check_pending_signals(target_date=yesterday)

        assert results["checked"] == 1
        assert results["executed"] == 0
        assert results["expired"] == 1

        # 验证信号状态
        signal = db.query(SignalLog).filter(SignalLog.symbol == "HK:00700").first()
        assert signal.status == "EXPIRED"
        assert signal.entered is False

    def test_check_pending_signals_skips_when_no_price_data(self, db):
        """测试: 无价格数据时跳过"""
        # 创建股票但无价格数据
        stock = Stock(
            symbol="US:NVDA",
            name="NVIDIA",
            market="US",
            currency="USD",
            current_price=None,
            open_price=None,
            low_price=None,
            price_updated_at=None
        )
        db.add(stock)

        yesterday = date.today() - timedelta(days=1)
        signal = SignalLog(
            symbol="US:NVDA",
            name="NVIDIA",
            generated_at=datetime.combine(yesterday, datetime.min.time()),
            action="BUY",
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=400.0,
        )
        db.add(signal)
        db.commit()

        service = SignalExecutionService(db)
        results = service.check_pending_signals(target_date=yesterday)

        assert results["checked"] == 1
        assert results["skipped"] == 1

    def test_check_pending_signals_skips_when_no_limit_price(self, db):
        """测试: 无limit_price时跳过"""
        stock = Stock(
            symbol="US:NVDA",
            name="NVIDIA",
            market="US",
            currency="USD",
            current_price=400.0,
            open_price=395.0,
            low_price=390.0,
            price_updated_at=datetime.now()
        )
        db.add(stock)

        yesterday = date.today() - timedelta(days=1)
        signal = SignalLog(
            symbol="US:NVDA",
            name="NVIDIA",
            generated_at=datetime.combine(yesterday, datetime.min.time()),
            action="BUY",
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=None,  # 无limit_price
        )
        db.add(signal)
        db.commit()

        service = SignalExecutionService(db)
        results = service.check_pending_signals(target_date=yesterday)

        assert results["checked"] == 1
        assert results["skipped"] == 1


class TestSimPositionCreation:
    """测试模拟持仓创建"""

    @pytest.fixture
    def setup_and_execute(self, db):
        """设置并执行信号"""
        # 创建股票
        stock = Stock(
            symbol="US:TSLA",
            name="Tesla",
            market="US",
            currency="USD",
            current_price=358.0,
            open_price=350.0,
            high_price=360.0,
            low_price=345.0,
            price_updated_at=datetime.now()
        )
        db.add(stock)

        # 创建信号
        yesterday = date.today() - timedelta(days=1)
        signal = SignalLog(
            symbol="US:TSLA",
            name="Tesla",
            category="cyclical",
            generated_at=datetime.combine(yesterday, datetime.min.time()),
            action="BUY",
            confidence="HIGH",
            entry_price=355.28,
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=355.28,
            recommended_shares=100,
            recommended_shares_second=100,
        )
        db.add(signal)
        db.commit()

        # 执行成交检查
        service = SignalExecutionService(db)
        service.check_pending_signals(target_date=yesterday)

        return {"stock": stock, "signal": signal}

    def test_new_position_created_after_execution(self, db, setup_and_execute):
        """测试: 成交后创建新持仓"""
        position = db.query(SimPosition).filter(SimPosition.symbol == "US:TSLA").first()

        assert position is not None
        assert position.shares == 100
        assert position.avg_cost == 350.0  # 成交价
        assert position.batch_status == "FIRST_FILLED"
        assert position.second_batch_pending == 100
        assert position.category == "cyclical"

    def test_position_market_value_calculated(self, db, setup_and_execute):
        """测试: 持仓市值按成交价计算（买入时刻）"""
        position = db.query(SimPosition).filter(SimPosition.symbol == "US:TSLA").first()

        expected_value = 100 * 350.0  # shares * execute_price (开盘价低于limit，按开盘成交)
        assert position.market_value == expected_value


class TestExistingPositionUpdate:
    """测试已有持仓的更新"""

    @pytest.fixture
    def setup_existing_position_and_signal(self, db):
        """设置已有持仓和新信号"""
        # 创建股票
        stock = Stock(
            symbol="US:TSLA",
            name="Tesla",
            market="US",
            currency="USD",
            current_price=358.0,
            open_price=350.0,
            high_price=360.0,
            low_price=345.0,
            price_updated_at=datetime.now()
        )
        db.add(stock)

        # 创建已有持仓（比如之前已买入50股）
        existing_position = SimPosition(
            symbol="US:TSLA",
            name="Tesla",
            category="cyclical",
            snapshot_date=date.today(),
            shares=50,
            avg_cost=360.0,
            last_price=358.0,
            market_value=50 * 358.0,
            batch_status="COMPLETED",
            first_batch_shares=50,
            first_batch_price=360.0,
            first_batch_date=date.today() - timedelta(days=10),
            second_batch_pending=0,
        )
        db.add(existing_position)

        # 创建新信号（今天的新买入信号）
        yesterday = date.today() - timedelta(days=1)
        signal = SignalLog(
            symbol="US:TSLA",
            name="Tesla",
            category="cyclical",
            generated_at=datetime.combine(yesterday, datetime.min.time()),
            action="BUY",
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=355.28,
            recommended_shares=100,
            recommended_shares_second=100,
        )
        db.add(signal)
        db.commit()

        # 执行
        service = SignalExecutionService(db)
        service.check_pending_signals(target_date=yesterday)

        return {"existing_position": existing_position}

    def test_existing_position_updated_with_weighted_avg_cost(self, db, setup_existing_position_and_signal):
        """测试: 已有持仓按加权平均更新成本"""
        position = db.query(SimPosition).filter(SimPosition.symbol == "US:TSLA").first()

        # 原持仓: 50股 @ 360.0 = 18,000
        # 新增: 100股 @ 350.0 = 35,000
        # 新成本: (18,000 + 35,000) / 150 = 353.33

        assert position.shares == 150  # 50 + 100
        assert abs(position.avg_cost - 353.33) < 0.01  # 加权平均成本


class TestExpireStaleSignals:
    """测试过期信号清理"""

    def test_stale_signals_marked_cancelled(self, db):
        """测试: 超过3日未入场的信号标记为CANCELLED"""
        # 创建5天前的信号
        old_date = datetime.now() - timedelta(days=5)
        signal = SignalLog(
            symbol="US:NVDA",
            name="NVIDIA",
            generated_at=old_date,
            action="BUY",
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=400.0,
        )
        db.add(signal)
        db.commit()

        service = SignalExecutionService(db)
        count = service.check_and_expire_stale_signals()

        assert count == 1

        # 验证信号状态
        updated_signal = db.query(SignalLog).filter(SignalLog.symbol == "US:NVDA").first()
        assert updated_signal.status == "CANCELLED"
        assert "超过3个交易日未入场" in updated_signal.note

    def test_recent_signals_not_expired(self, db):
        """测试: 3日内的信号不标记过期"""
        # 创建1天前的信号
        recent_date = datetime.now() - timedelta(days=1)
        signal = SignalLog(
            symbol="US:NVDA",
            name="NVIDIA",
            generated_at=recent_date,
            action="BUY",
            is_simulated=True,
            entered=False,
            status="PENDING",
            limit_price=400.0,
        )
        db.add(signal)
        db.commit()

        service = SignalExecutionService(db)
        count = service.check_and_expire_stale_signals()

        assert count == 0

        # 验证信号状态未变
        updated_signal = db.query(SignalLog).filter(SignalLog.symbol == "US:NVDA").first()
        assert updated_signal.status == "PENDING"


class TestIntegrationScenarios:
    """综合场景测试"""

    @pytest.fixture
    def setup_multiple_signals(self, db):
        """设置多个信号，模拟完整场景"""
        stocks_data = [
            ("US:TSLA", "Tesla", "cyclical", 350.0, 345.0, 355.28),  # 成交
            ("US:UNH", "联合健康", "defensive", 268.0, 262.0, 266.0),  # 成交
            ("HK:00700", "腾讯", "large_tech", 430.0, 429.0, 428.40),  # 过期
            ("US:RKLB", "Rocket Lab", "biotech", 14.5, 14.2, 15.30),  # 成交
        ]

        yesterday = date.today() - timedelta(days=1)

        for symbol, name, category, open_p, low_p, limit_p in stocks_data:
            stock = Stock(
                symbol=symbol,
                name=name,
                market=symbol.split(":")[0],
                currency="USD" if symbol.startswith("US:") else "HKD",
                current_price=open_p + 5,
                open_price=open_p,
                high_price=open_p + 10,
                low_price=low_p,
                price_updated_at=datetime.now()
            )
            db.add(stock)

            signal = SignalLog(
                symbol=symbol,
                name=name,
                category=category,
                generated_at=datetime.combine(yesterday, datetime.min.time()),
                action="BUY",
                is_simulated=True,
                entered=False,
                status="PENDING",
                limit_price=limit_p,
                recommended_shares=100,
            )
            db.add(signal)

        db.commit()
        return {"date": yesterday}

    def test_multiple_signals_execution(self, db, setup_multiple_signals):
        """测试: 多个信号同时处理"""
        service = SignalExecutionService(db)
        results = service.check_pending_signals(target_date=setup_multiple_signals["date"])

        assert results["checked"] == 4
        assert results["executed"] == 3  # TSLA, UNH, RKLB
        assert results["expired"] == 1   # 腾讯

        # 验证持仓创建
        positions = db.query(SimPosition).all()
        assert len(positions) == 3

        # 验证腾讯过期
        tencent_signal = db.query(SignalLog).filter(SignalLog.symbol == "HK:00700").first()
        assert tencent_signal.status == "EXPIRED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
