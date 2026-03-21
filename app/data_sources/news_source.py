"""
新闻数据源 — yfinance（按股票过滤的真实资讯）
"""
import logging
from datetime import datetime
from typing import List

from app.data_sources.base import BaseDataSource, PriceData, NewsData

logger = logging.getLogger(__name__)


def _symbol_to_yf(symbol: str) -> str:
    """将内部 symbol 转为 yfinance 格式"""
    if ":" not in symbol:
        return symbol
    market, code = symbol.split(":", 1)
    if market == "HK":
        return str(int(code)).zfill(4) + ".HK"
    return code  # US stocks use code directly


class YFinanceNewsSource(BaseDataSource):
    """yfinance 新闻数据源，按个股拉取真实资讯"""

    def get_price(self, symbol: str) -> PriceData:
        raise NotImplementedError("YFinanceNewsSource 不提供股价数据")

    def get_news(self, symbol: str, max_results: int = 5) -> List[NewsData]:
        try:
            return self.fetch_with_retry(self._fetch_news, symbol, max_results)
        except Exception as e:
            logger.warning(f"获取新闻失败: {symbol} - {e}")
            return []

    def _fetch_news(self, symbol: str, max_results: int) -> List[NewsData]:
        import yfinance as yf
        yf_symbol = _symbol_to_yf(symbol)
        ticker = yf.Ticker(yf_symbol)
        raw_news = ticker.news or []

        news_list = []
        for item in raw_news[:max_results]:
            content = item.get("content", {})
            title = content.get("title", "")
            if not title:
                continue

            url = (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get("url", "")
            summary = content.get("summary") or content.get("description") or ""
            source = (content.get("provider") or {}).get("displayName", "Yahoo Finance")

            pub_date_str = content.get("pubDate") or content.get("displayTime") or ""
            published_at = self._parse_date(pub_date_str)

            news_list.append(NewsData(
                stock_symbol=symbol,
                title=title,
                url=url,
                source=source,
                summary=summary[:300] if summary else title,
                published_at=published_at,
            ))

        return news_list

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        if not date_str:
            return datetime.now()
        try:
            return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return datetime.now()


# 兼容旧导入名
SinaNewsSource = YFinanceNewsSource
