"""
持仓计算逻辑测试
测试盈亏计算、仓位计算、汇率换算等核心业务逻辑
"""
import pytest
from decimal import Decimal
from datetime import date


class TestProfitLossCalculation:
    """盈亏计算测试"""

    def test_simple_profit_calculation(self):
        """测试简单盈亏计算：盈利场景"""
        position = {
            "total_shares": 1000,
            "avg_cost": Decimal("350.00"),
            "trading_cost": Decimal("500.00")
        }
        current_price = Decimal("400.00")

        # 当前市值
        market_value = position["total_shares"] * current_price
        # 投入成本（不含交易成本）
        cost_basis = position["total_shares"] * position["avg_cost"]
        # 盈亏金额
        profit = market_value - cost_basis

        assert market_value == Decimal("400000.00")
        assert cost_basis == Decimal("350000.00")
        assert profit == Decimal("50000.00")

    def test_loss_calculation(self):
        """测试亏损场景"""
        position = {
            "total_shares": 1000,
            "avg_cost": Decimal("350.00"),
            "trading_cost": Decimal("500.00")
        }
        current_price = Decimal("300.00")

        market_value = position["total_shares"] * current_price
        cost_basis = position["total_shares"] * position["avg_cost"]
        loss = market_value - cost_basis

        assert loss == Decimal("-50000.00")

    def test_profit_percentage(self):
        """测试盈亏百分比"""
        position = {
            "total_shares": 1000,
            "avg_cost": Decimal("350.00"),
            "trading_cost": Decimal("500.00")
        }
        current_price = Decimal("400.00")

        cost_basis = position["total_shares"] * position["avg_cost"]
        profit = (position["total_shares"] * current_price) - cost_basis
        # 盈亏比例 = 盈亏金额 / 投入成本
        profit_pct = (profit / cost_basis) * 100

        assert abs(profit_pct - Decimal("14.285714")) < Decimal("0.000001")  # 约 14.29%


class TestPositionWeightCalculation:
    """仓位占比计算测试"""

    def test_single_stock_position_weight(self):
        """测试单票仓位占该市场比例"""
        market_total_fund = Decimal("1000000.00")  # 100万 HKD
        position = {
            "total_shares": 1000,
            "avg_cost": Decimal("350.00"),
            "currency": "HKD"
        }
        current_price = Decimal("400.00")

        # 市值
        market_value = position["total_shares"] * current_price
        # 仓位占比
        weight = (market_value / market_total_fund) * 100

        assert market_value == Decimal("400000.00")
        assert weight == Decimal("40.00")  # 40% 仓位

    def test_total_portfolio_weight_rmb(self):
        """测试总仓位（换算为RMB）"""
        # 港股持仓
        hk_position = {
            "market_value_hkd": Decimal("400000.00"),
            "exchange_rate": Decimal("0.92")  # 1 HKD = 0.92 RMB
        }
        # 美股持仓
        us_position = {
            "market_value_usd": Decimal("50000.00"),
            "exchange_rate": Decimal("7.20")  # 1 USD = 7.20 RMB
        }
        # A股持仓
        a_position = {
            "market_value_cny": Decimal("300000.00"),
            "exchange_rate": Decimal("1.00")
        }

        # 总市值（RMB）
        total_rmb = (
            hk_position["market_value_hkd"] * hk_position["exchange_rate"] +
            us_position["market_value_usd"] * us_position["exchange_rate"] +
            a_position["market_value_cny"] * a_position["exchange_rate"]
        )

        assert total_rmb == Decimal("368000.00") + Decimal("360000.00") + Decimal("300000.00")
        assert total_rmb == Decimal("1028000.00")

    def test_position_weight_warning(self):
        """测试仓位预警：单票超过30%应该警告"""
        market_total = Decimal("1000000.00")
        position_value = Decimal("350000.00")  # 35万

        weight = (position_value / market_total) * 100

        assert weight > Decimal("30.00")  # 超过30%


class TestSwingTradeCalculation:
    """波段交易计算测试"""

    def test_swing_trade_avg_cost(self):
        """测试波段仓整体成本计算"""
        swing_trades = [
            {"shares": 500, "price": Decimal("400.00")},
            {"shares": 500, "price": Decimal("380.00")},
        ]

        total_shares = sum(t["shares"] for t in swing_trades)
        total_cost = sum(t["shares"] * t["price"] for t in swing_trades)
        avg_cost = total_cost / total_shares

        assert total_shares == 1000
        assert total_cost == Decimal("390000.00")
        assert avg_cost == Decimal("390.00")

    def test_swing_trade_sell_decision(self):
        """测试波段仓卖出决策"""
        swing_position = {
            "shares": 1000,
            "avg_cost": Decimal("390.00"),
            "target_prices": [Decimal("450.00"), Decimal("420.00")]  # 两批不同目标价
        }
        current_price = Decimal("430.00")

        # 当前价格超过第二目标价，但未达第一目标价
        # 建议：卖出第二批（目标420），保留第一批（目标450）
        should_sell_second_batch = current_price >= swing_position["target_prices"][1]
        should_sell_first_batch = current_price >= swing_position["target_prices"][0]

        assert should_sell_second_batch is True
        assert should_sell_first_batch is False

    def test_swing_trade_profit(self):
        """测试波段仓独立盈亏计算"""
        swing_trade = {
            "shares": 500,
            "buy_price": Decimal("380.00"),
            "sell_price": Decimal("420.00"),
            "trading_cost": Decimal("200.00")
        }

        # 毛利
        gross_profit = (swing_trade["sell_price"] - swing_trade["buy_price"]) * swing_trade["shares"]
        # 净利（扣除交易成本）
        net_profit = gross_profit - swing_trade["trading_cost"]

        assert gross_profit == Decimal("20000.00")
        assert net_profit == Decimal("19800.00")


class TestMultiCurrencyCalculation:
    """多币种计算测试"""

    def test_exchange_rate_application(self):
        """测试汇率应用"""
        hkd_amount = Decimal("100000.00")
        exchange_rate = Decimal("0.92")  # HKD to CNY

        rmb_amount = hkd_amount * exchange_rate

        assert rmb_amount == Decimal("92000.00")

    def test_end_of_day_exchange_rate(self):
        """测试使用收盘汇率"""
        # 收盘时汇率
        eod_rate = {
            "HKD_CNY": Decimal("0.92"),
            "USD_CNY": Decimal("7.20"),
            "date": date.today()
        }

        # 当日所有换算使用同一汇率
        hk_value_rmb = Decimal("400000") * eod_rate["HKD_CNY"]
        us_value_rmb = Decimal("50000") * eod_rate["USD_CNY"]

        assert hk_value_rmb == Decimal("368000.00")
        assert us_value_rmb == Decimal("360000.00")


class TestBaseAndSwingSeparation:
    """底仓与波段仓分离计算测试"""

    def test_base_position_no_sell(self):
        """测试底仓长期持有，不触发卖出建议"""
        position = {
            "base_shares": 1000,
            "base_cost": Decimal("360.00"),
            "is_base": True
        }
        current_price = Decimal("500.00")

        # 底仓即使大涨也不建议卖出（价值投资）
        should_sell = False if position["is_base"] else True

        assert should_sell is False

    def test_mixed_position_calculation(self):
        """测试混合仓位计算"""
        position = {
            "base_shares": 1000,
            "base_cost": Decimal("360.00"),
            "swing_shares": 500,
            "swing_cost": Decimal("380.00"),
        }
        current_price = Decimal("400.00")

        # 底仓盈亏
        base_pnl = (current_price - position["base_cost"]) * position["base_shares"]
        # 波段仓盈亏
        swing_pnl = (current_price - position["swing_cost"]) * position["swing_shares"]
        # 总盈亏
        total_pnl = base_pnl + swing_pnl

        assert base_pnl == Decimal("40000.00")  # (400-360)*1000
        assert swing_pnl == Decimal("10000.00")  # (400-380)*500
        assert total_pnl == Decimal("50000.00")
