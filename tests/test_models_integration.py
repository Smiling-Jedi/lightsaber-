"""
数据模型集成测试（使用真实数据库）
"""
import pytest
from decimal import Decimal
from datetime import date

from app.models import Stock, Position, Trade, News


class TestStockModel:
    """股票模型集成测试"""

    def test_create_stock(self, db):
        stock = Stock(symbol="HK:00700", name="腾讯控股", market="HK", currency="HKD", sector="科技")
        db.add(stock)
        db.commit()

        result = db.query(Stock).filter_by(symbol="HK:00700").first()
        assert result is not None
        assert result.name == "腾讯控股"
        assert result.market == "HK"
        assert result.currency == "HKD"

    def test_stock_price_change_pct(self, db):
        stock = Stock(
            symbol="HK:00700", name="腾讯控股", market="HK", currency="HKD",
            open_price=Decimal("390.00"), current_price=Decimal("400.00")
        )
        db.add(stock)
        db.commit()

        assert abs(stock.price_change_pct - 2.564) < 0.01


class TestPositionModel:
    """持仓模型集成测试"""

    def test_create_position(self, db, sample_stock_hk):
        position = Position(
            stock_symbol="HK:00700",
            total_shares=1500,
            base_shares=1000,
            base_cost=Decimal("360.00"),
            avg_cost=Decimal("350.00"),
            market_total_fund=Decimal("1000000"),
            currency="HKD",
        )
        db.add(position)
        db.commit()

        result = db.query(Position).filter_by(stock_symbol="HK:00700").first()
        assert result.total_shares == 1500
        assert result.swing_shares == 500

    def test_profit_calculation(self, db, sample_stock_hk):
        position = Position(
            stock_symbol="HK:00700",
            total_shares=1000,
            base_shares=1000,
            avg_cost=Decimal("350.00"),
            market_total_fund=Decimal("1000000"),
            currency="HKD",
        )
        db.add(position)
        db.commit()

        profit = position.calculate_profit(Decimal("400.00"))
        assert profit == Decimal("50000.00")

        pct = position.calculate_profit_pct(Decimal("400.00"))
        assert abs(pct - 14.285) < 0.01

    def test_position_weight(self, db, sample_stock_hk):
        position = Position(
            stock_symbol="HK:00700",
            total_shares=1000,
            base_shares=1000,
            avg_cost=Decimal("350.00"),
            market_total_fund=Decimal("1000000"),
            currency="HKD",
        )
        db.add(position)
        db.commit()

        weight = position.calculate_position_weight(Decimal("400.00"))
        assert abs(weight - 40.0) < 0.01


class TestTradeModel:
    """交易模型集成测试"""

    def test_create_buy_trade(self, db, sample_stock_hk):
        position = Position(
            stock_symbol="HK:00700", total_shares=500, base_shares=0,
            avg_cost=Decimal("380.00"), market_total_fund=Decimal("1000000"), currency="HKD"
        )
        db.add(position)
        db.commit()

        trade = Trade(
            position_id=position.id,
            trade_type="BUY",
            shares=500,
            price=Decimal("380.00"),
            is_swing=True,
            target_sell_price=Decimal("450.00"),
            trade_date=date.today(),
        )
        db.add(trade)
        db.commit()

        assert trade.total_cost == Decimal("190000.00")
        assert trade.remaining_shares == 500
        assert trade.is_swing is True

    def test_swing_sell_decision(self, db, sample_stock_hk):
        position = Position(
            stock_symbol="HK:00700", total_shares=500, base_shares=0,
            avg_cost=Decimal("380.00"), market_total_fund=Decimal("1000000"), currency="HKD"
        )
        db.add(position)
        db.commit()

        trade = Trade(
            position_id=position.id, trade_type="BUY", shares=500,
            price=Decimal("380.00"), is_swing=True,
            target_sell_price=Decimal("420.00"),
            stop_loss_price=Decimal("350.00"),
            trade_date=date.today(),
        )
        db.add(trade)
        db.commit()

        assert trade.should_sell_at_price(Decimal("430.00")) == "TARGET_HIT"
        assert trade.should_sell_at_price(Decimal("340.00")) == "STOP_LOSS"
        assert trade.should_sell_at_price(Decimal("400.00")) == "HOLD"


class TestNewsModel:
    """新闻模型集成测试"""

    def test_create_news(self, db, sample_stock_hk):
        news = News(
            stock_symbol="HK:00700",
            title="腾讯Q4财报超预期",
            summary="腾讯Q4营收同比增长12%...",
            url="https://finance.sina.com.cn/test",
            source="新浪财经",
        )
        db.add(news)
        db.commit()

        result = db.query(News).filter_by(stock_symbol="HK:00700").first()
        assert result.title == "腾讯Q4财报超预期"
        assert result.source == "新浪财经"
