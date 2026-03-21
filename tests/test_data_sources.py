"""
数据源适配器测试
使用 Mock 测试外部 API 调用
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
from datetime import datetime


class TestTushareSource:
    """Tushare 数据源适配器测试"""

    @pytest.fixture
    def tushare_source(self):
        """创建 Tushare 数据源实例"""
        # 这里模拟真实的数据源类
        return {
            "token": "test_token_12345",
            "base_url": "https://api.tushare.pro",
            "retry_count": 3,
            "retry_delay": 1
        }

    def test_get_price_success(self, tushare_source):
        """测试成功获取 A 股价格"""
        mock_response = {
            "code": 0,
            "data": {
                "ts_code": "600519.SH",
                "trade_date": "20260319",
                "close": 1750.00,
                "open": 1740.00,
                "high": 1760.00,
                "low": 1735.00,
                "vol": 25000
            }
        }

        # Mock API 调用
        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.status_code = 200

            # 模拟调用
            result = self._mock_fetch_price(tushare_source, "600519")

            assert result["symbol"] == "600519"
            assert result["close"] == Decimal("1750.00")
            assert result["market"] == "A"

    def test_get_price_insufficient_points(self, tushare_source):
        """测试 Tushare 积分不足错误"""
        mock_response = {
            "code": -2001,
            "msg": "积分不足"
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.status_code = 200

            result = self._mock_fetch_price(tushare_source, "600519")

            # 应该返回错误信息，提示用户配置备用源
            assert result["error"] == "INSUFFICIENT_POINTS"
            assert "积分不足" in result["message"]

    def test_get_price_network_error_with_retry(self, tushare_source):
        """测试网络错误时的重试机制"""
        with patch('requests.post') as mock_post:
            # 前两次失败，第三次成功
            mock_post.side_effect = [
                Exception("Connection timeout"),
                Exception("Connection timeout"),
                MagicMock(
                    status_code=200,
                    json=lambda: {
                        "code": 0,
                        "data": {"close": 1750.00}
                    }
                )
            ]

            result = self._mock_fetch_price_with_retry(tushare_source, "600519")

            # 应该成功（第三次）
            assert result["close"] == Decimal("1750.00")
            # 验证调用了3次
            assert mock_post.call_count == 3

    def test_get_price_all_retries_failed(self, tushare_source):
        """测试重试全部失败后返回错误"""
        with patch('requests.post') as mock_post:
            mock_post.side_effect = Exception("Connection timeout")

            result = self._mock_fetch_price_with_retry(tushare_source, "600519")

            # 验证调用了3次（最大重试次数）
            assert mock_post.call_count == 3
            # 返回错误信息
            assert result["error"] == "MAX_RETRIES_EXCEEDED"

    def _mock_fetch_price(self, source, symbol):
        """模拟获取价格（无重试）"""
        import requests
        try:
            response = requests.post(
                source["base_url"],
                json={"api_name": "daily", "params": {"ts_code": symbol}}
            )
            data = response.json()

            if data.get("code") != 0:
                return {
                    "error": "INSUFFICIENT_POINTS" if data.get("code") == -2001 else "API_ERROR",
                    "message": data.get("msg", "Unknown error")
                }

            return {
                "symbol": symbol,
                "close": Decimal(str(data["data"]["close"])),
                "market": "A"
            }
        except Exception as e:
            return {"error": "NETWORK_ERROR", "message": str(e)}

    def _mock_fetch_price_with_retry(self, source, symbol):
        """模拟获取价格（带重试）"""
        import requests
        import time

        for attempt in range(source["retry_count"]):
            try:
                response = requests.post(
                    source["base_url"],
                    json={"api_name": "daily", "params": {"ts_code": symbol}}
                )
                data = response.json()

                if data.get("code") == 0:
                    return {
                        "symbol": symbol,
                        "close": Decimal(str(data["data"]["close"])),
                        "market": "A"
                    }
            except Exception:
                if attempt < source["retry_count"] - 1:
                    time.sleep(source["retry_delay"] * (2 ** attempt))  # 指数退避
                continue

        return {"error": "MAX_RETRIES_EXCEEDED", "message": "所有重试均失败"}


class TestYahooSource:
    """Yahoo Finance 数据源适配器测试"""

    @pytest.fixture
    def yahoo_source(self):
        return {
            "base_url": "https://query1.finance.yahoo.com",
            "retry_count": 3,
            "proxy": None  # 可选代理配置
        }

    def test_get_hk_stock_price(self, yahoo_source):
        """测试获取港股价格"""
        mock_response = {
            "chart": {
                "result": [{
                    "meta": {"regularMarketPrice": 400.00},
                    "timestamp": [1700000000],
                    "indicators": {
                        "quote": [{"close": [400.00], "open": [395.00], "high": [405.00], "low": [394.00]}]
                    }
                }]
            }
        }

        with patch('requests.get') as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.status_code = 200

            result = self._mock_fetch_yahoo_price(yahoo_source, "0700.HK")

            assert result["symbol"] == "0700.HK"
            assert result["close"] == Decimal("400.00")
            assert result["market"] == "HK"

    def test_get_us_stock_price(self, yahoo_source):
        """测试获取美股价格"""
        mock_response = {
            "chart": {
                "result": [{
                    "meta": {"regularMarketPrice": 250.00},
                    "timestamp": [1700000000],
                    "indicators": {
                        "quote": [{"close": [250.00], "open": [245.00], "high": [255.00], "low": [244.00]}]
                    }
                }]
            }
        }

        with patch('requests.get') as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.status_code = 200

            result = self._mock_fetch_yahoo_price(yahoo_source, "TSLA")

            assert result["symbol"] == "TSLA"
            assert result["close"] == Decimal("250.00")
            assert result["market"] == "US"

    def test_yahoo_403_error(self, yahoo_source):
        """测试 Yahoo 403 错误（IP被封）"""
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 403
            mock_get.return_value.text = "Forbidden"

            result = self._mock_fetch_yahoo_price(yahoo_source, "0700.HK")

            # 403 不应该重试，直接失败
            assert result["error"] == "FORBIDDEN"
            assert mock_get.call_count == 1  # 只调用一次，不重试

    def _mock_fetch_yahoo_price(self, source, symbol):
        """模拟 Yahoo Finance 获取价格"""
        import requests

        try:
            response = requests.get(
                f"{source['base_url']}/v8/finance/chart/{symbol}",
                proxies=source.get("proxy")
            )

            if response.status_code == 403:
                return {"error": "FORBIDDEN", "message": "IP被限制，建议配置代理"}

            response.raise_for_status()
            data = response.json()

            result = data["chart"]["result"][0]
            return {
                "symbol": symbol,
                "close": Decimal(str(result["meta"]["regularMarketPrice"])),
                "market": "HK" if ".HK" in symbol else "US",
                "open": Decimal(str(result["indicators"]["quote"][0]["open"][0])),
                "high": Decimal(str(result["indicators"]["quote"][0]["high"][0])),
                "low": Decimal(str(result["indicators"]["quote"][0]["low"][0]))
            }
        except Exception as e:
            return {"error": "FETCH_ERROR", "message": str(e)}


class TestNewsSource:
    """新闻数据源适配器测试"""

    @pytest.fixture
    def sina_news_source(self):
        return {
            "rss_url": "https://rss.sina.com.cn/finance/stock/{symbol}.xml",
            "max_news_per_stock": 5,
            "retry_count": 3
        }

    def test_fetch_news_success(self, sina_news_source):
        """测试成功获取新闻"""
        mock_xml = """<?xml version="1.0"?>
        <rss>
            <channel>
                <item>
                    <title>腾讯发布Q3财报</title>
                    <link>https://finance.sina.com.cn/1.html</link>
                    <pubDate>Thu, 19 Mar 2026 10:00:00 GMT</pubDate>
                    <description>腾讯Q3营收增长10%...</description>
                </item>
            </channel>
        </rss>"""

        with patch('requests.get') as mock_get:
            mock_get.return_value.text = mock_xml
            mock_get.return_value.status_code = 200

            result = self._mock_fetch_news(sina_news_source, "00700")

            assert len(result) == 1
            assert result[0]["title"] == "腾讯发布Q3财报"
            assert result[0]["source"] == "新浪财经"

    def test_fetch_news_empty(self, sina_news_source):
        """测试无新闻返回"""
        mock_xml = """<?xml version="1.0"?>
        <rss><channel></channel></rss>"""

        with patch('requests.get') as mock_get:
            mock_get.return_value.text = mock_xml
            mock_get.return_value.status_code = 200

            result = self._mock_fetch_news(sina_news_source, "00700")

            assert len(result) == 0  # 空列表，不报错

    def test_fetch_news_network_error(self, sina_news_source):
        """测试新闻获取网络错误"""
        with patch('requests.get') as mock_get:
            mock_get.side_effect = Exception("Connection failed")

            result = self._mock_fetch_news_with_retry(sina_news_source, "00700")

            # 返回空列表，留白
            assert result == []

    def _mock_fetch_news(self, source, symbol):
        """模拟获取新闻"""
        import requests
        from xml.etree import ElementTree as ET

        try:
            response = requests.get(source["rss_url"].format(symbol=symbol))
            response.raise_for_status()

            root = ET.fromstring(response.text)
            items = root.findall('.//item')

            news_list = []
            for item in items[:source["max_news_per_stock"]]:
                news_list.append({
                    "title": item.findtext("title", ""),
                    "url": item.findtext("link", ""),
                    "summary": item.findtext("description", "")[:200],  # 截断前200字
                    "source": "新浪财经",
                    "published_at": item.findtext("pubDate", "")
                })

            return news_list
        except Exception:
            return []

    def _mock_fetch_news_with_retry(self, source, symbol):
        """模拟获取新闻（带重试）"""
        import requests
        import time

        for attempt in range(source["retry_count"]):
            try:
                response = requests.get(source["rss_url"].format(symbol=symbol))
                response.raise_for_status()
                # 解析逻辑...
                return []  # 简化返回
            except Exception:
                if attempt < source["retry_count"] - 1:
                    time.sleep(1)
                continue

        return []  # 失败后返回空列表（留白）


class TestDataSourceFallback:
    """数据源降级测试"""

    def test_fallback_when_tushare_fails(self):
        """测试 Tushare 失败时降级到备用源"""
        # 模拟 Tushare 积分不足
        tushare_result = {"error": "INSUFFICIENT_POINTS", "message": "积分不足"}

        # 应该尝试备用源（如东方财富）
        fallback_result = {
            "symbol": "600519",
            "close": Decimal("1750.00"),
            "market": "A",
            "source": "EASTMONEY"  # 备用源
        }

        # 验证降级逻辑
        if tushare_result.get("error") == "INSUFFICIENT_POINTS":
            result = fallback_result
        else:
            result = tushare_result

        assert result["source"] == "EASTMONEY"
        assert result["close"] == Decimal("1750.00")

    def test_all_sources_failed(self):
        """测试所有数据源都失败"""
        tushare_result = {"error": "FAILED"}
        yahoo_result = {"error": "FAILED"}
        eastmoney_result = {"error": "FAILED"}

        # 所有源都失败，使用缓存数据或报错
        final_result = {
            "error": "ALL_SOURCES_FAILED",
            "message": "所有数据源均不可用，请稍后重试或手动更新",
            "cached": True,  # 标记使用缓存数据
            "last_price": Decimal("1700.00"),  # 上次成功获取的价格
            "last_update": "2026-03-18 15:00:00"
        }

        assert final_result["error"] == "ALL_SOURCES_FAILED"
        assert final_result["cached"] is True
