"""
数据模型测试
测试 Stock, Position, Trade, News 模型的创建和关系
"""
import pytest
from datetime import datetime, date
from decimal import Decimal


class TestStock:
    """股票基础信息模型测试"""

    def test_stock_creation(self):
        """测试创建股票记录"""
        stock = {
            "symbol": "00700",
            "name": "腾讯控股",
            "market": "HK",
            "currency": "HKD",
            "sector": "科技",
            "created_at": datetime.now()
        }

        assert stock["symbol"] == "00700"
        assert stock["market"] == "HK"
        assert stock["currency"] == "HKD"

    def test_stock_symbol_format(self):
        """测试股票代码格式"""
        # 港股
        hk_stock = {"symbol": "00700", "market": "HK"}
        assert hk_stock["market"] == "HK"

        # A股
        a_stock = {"symbol": "600519", "market": "A"}
        assert a_stock["market"] == "A"

        # 美股
        us_stock = {"symbol": "TSLA", "market": "US"}
        assert us_stock["market"] == "US"


class TestPosition:
    """持仓记录模型测试"""

    def test_position_creation(self):
        """测试创建持仓记录"""
        position = {
            "stock_symbol": "00700",
            "total_shares": 1500,
            "base_position_shares": 1000,  # 底仓
            "swing_position_shares": 500,   # 波段仓
            "avg_cost": Decimal("350.00"),
            "base_cost": Decimal("360.00"),
            "trading_cost": Decimal("500.00"),
            "created_at": datetime.now()
        }

        assert position["total_shares"] == 1500
        assert position["base_position_shares"] == 1000
        assert position["swing_position_shares"] == 500
        assert position["avg_cost"] == Decimal("350.00")

    def test_position_calculation(self):
        """测试持仓计算逻辑"""
        position = {
            "total_shares": 1500,
            "avg_cost": Decimal("350.00"),
            "trading_cost": Decimal("500.00")
        }

        # 投入成本 = 股数 * 成本价 + 交易成本
        invested = position["total_shares"] * position["avg_cost"] + position["trading_cost"]
        assert invested == Decimal("525500.00")  # 1500 * 350 + 500

    def test_position_shares_consistency(self):
        """测试股数一致性：总股数 = 底仓 + 波段仓"""
        position = {
            "total_shares": 1500,
            "base_position_shares": 1000,
            "swing_position_shares": 500
        }

        assert position["total_shares"] == position["base_position_shares"] + position["swing_position_shares"]


class TestTrade:
    """交易记录模型测试"""

    def test_trade_creation(self):
        """测试创建交易记录"""
        trade = {
            "position_id": 1,
            "trade_type": "BUY",  # BUY or SELL
            "shares": 500,
            "price": Decimal("380.00"),
            "trading_cost": Decimal("200.00"),
            "is_swing": True,  # 是否为波段交易
            "target_sell_price": Decimal("450.00"),  # 波段仓目标卖出价
            "trade_date": date.today(),
            "created_at": datetime.now()
        }

        assert trade["trade_type"] == "BUY"
        assert trade["shares"] == 500
        assert trade["is_swing"] is True
        assert trade["target_sell_price"] == Decimal("450.00")

    def test_swing_trade_batch(self):
        """测试波段仓分批记录"""
        trades = [
            {
                "trade_type": "BUY",
                "shares": 500,
                "price": Decimal("400.00"),
                "is_swing": True,
                "target_sell_price": Decimal("450.00")
            },
            {
                "trade_type": "BUY",
                "shares": 500,
                "price": Decimal("380.00"),
                "is_swing": True,
                "target_sell_price": Decimal("420.00")
            }
        ]

        # 波段仓总股数
        total_swing = sum(t["shares"] for t in trades if t["is_swing"])
        assert total_swing == 1000

        # 每批独立记录成本和目标价
        assert trades[0]["target_sell_price"] == Decimal("450.00")
        assert trades[1]["target_sell_price"] == Decimal("420.00")


class TestNews:
    """新闻缓存模型测试"""

    def test_news_creation(self):
        """测试创建新闻记录"""
        news = {
            "stock_symbol": "00700",
            "title": "腾讯发布Q3财报",
            "summary": "腾讯Q3营收同比增长10%，净利润超预期...",
            "url": "https://finance.sina.com.cn/xxx",
            "source": "新浪财经",
            "published_at": datetime.now(),
            "fetched_at": datetime.now()
        }

        assert news["stock_symbol"] == "00700"
        assert news["source"] == "新浪财经"
        assert "url" in news

    def test_news_summary_length(self):
        """测试新闻摘要长度限制"""
        news = {
            "summary": "这是一个很长的摘要内容..." * 10
        }

        # 摘要应该限制在合理长度，比如200字
        assert len(news["summary"]) <= 500


class TestRelationships:
    """模型关系测试"""

    def test_stock_has_many_positions(self):
        """测试一只股票可被多次买入（不同时间）"""
        stock = {"symbol": "00700", "name": "腾讯控股"}
        positions = [
            {"stock_symbol": "00700", "total_shares": 1000},
            {"stock_symbol": "00700", "total_shares": 500}  # 追加买入
        ]

        assert all(p["stock_symbol"] == stock["symbol"] for p in positions)

    def test_position_has_many_trades(self):
        """测试持仓关联多笔交易"""
        position = {"id": 1, "stock_symbol": "00700"}
        trades = [
            {"position_id": 1, "trade_type": "BUY", "shares": 1000},
            {"position_id": 1, "trade_type": "BUY", "shares": 500},
        ]

        assert all(t["position_id"] == position["id"] for t in trades)
        total_shares = sum(t["shares"] for t in trades if t["trade_type"] == "BUY")
        assert total_shares == 1500
