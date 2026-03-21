"""
新闻服务
处理新闻获取、摘要生成、缓存管理
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.news import News
from app.data_sources.news_source import SinaNewsSource as NewsSource

logger = logging.getLogger(__name__)


class NewsService:
    """新闻服务类"""

    def __init__(self, db: Session):
        self.db = db
        self.news_source = NewsSource()

    def fetch_news_for_stock(self, stock: Stock, max_results: int = 5) -> List[News]:
        """
        获取单只股票的新闻

        Args:
            stock: 股票对象
            max_results: 最多获取几条

        Returns:
            新闻对象列表
        """
        try:
            # 获取股票代码（不含市场前缀）
            symbol = stock.symbol.split(":")[-1] if ":" in stock.symbol else stock.symbol

            # 从数据源获取新闻
            news_data_list = self.news_source.get_news(symbol, max_results)

            added_news = []
            for news_data in news_data_list:
                # 检查是否已存在（根据 URL 去重）
                existing = (
                    self.db.query(News)
                    .filter(News.url == news_data.url)
                    .first()
                )
                if existing:
                    continue

                # 创建新闻记录
                news = News(
                    stock_symbol=stock.symbol,
                    title=news_data.title,
                    summary=news_data.summary or news_data.title[:100] + "...",
                    url=news_data.url,
                    source=news_data.source,
                    published_at=news_data.published_at,
                )
                self.db.add(news)
                added_news.append(news)

            if added_news:
                self.db.commit()
                logger.info(f"为 {stock.symbol} 新增 {len(added_news)} 条新闻")

            return added_news

        except Exception as e:
            logger.error(f"获取 {stock.symbol} 新闻失败: {e}")
            return []

    def fetch_all_news(self, max_per_stock: int = 5) -> Dict:
        """
        获取所有持仓股票的新闻

        Returns:
            统计信息
        """
        stocks = self.db.query(Stock).join(Stock.positions).all()

        results = {
            "total_stocks": len(stocks),
            "total_added": 0,
            "details": [],
            "updated_at": datetime.now().isoformat()
        }

        for stock in stocks:
            added = self.fetch_news_for_stock(stock, max_per_stock)
            results["total_added"] += len(added)
            results["details"].append({
                "symbol": stock.symbol,
                "added": len(added)
            })

        return results

    def get_stock_news(self, symbol: str, limit: int = 10) -> List[News]:
        """
        获取某只股票的新闻（从缓存）

        Args:
            symbol: 股票代码
            limit: 返回条数

        Returns:
            新闻列表，按发布时间倒序
        """
        news = (
            self.db.query(News)
            .filter(News.stock_symbol == symbol)
            .order_by(News.published_at.desc())
            .limit(limit)
            .all()
        )
        return news

    def get_recent_news(self, hours: int = 24, limit: int = 50) -> List[News]:
        """
        获取最近的新闻（所有股票）

        Args:
            hours: 最近几小时
            limit: 返回条数

        Returns:
            新闻列表
        """
        since = datetime.now() - timedelta(hours=hours)

        news = (
            self.db.query(News)
            .filter(News.published_at >= since)
            .order_by(News.published_at.desc())
            .limit(limit)
            .all()
        )
        return news

    def delete_old_news(self, days: int = 30) -> int:
        """
        删除旧新闻（清理缓存）

        Args:
            days: 保留几天内的新闻

        Returns:
            删除条数
        """
        cutoff = datetime.now() - timedelta(days=days)

        result = (
            self.db.query(News)
            .filter(News.published_at < cutoff)
            .delete(synchronize_session=False)
        )

        self.db.commit()
        logger.info(f"删除 {result} 条旧新闻（{days}天前）")
        return result

    def to_dict(self, news: News) -> Dict:
        """
        将新闻对象转为字典（用于 API 返回）
        """
        return {
            "id": news.id,
            "symbol": news.stock_symbol,
            "title": news.title,
            "summary": news.summary,
            "url": news.url,
            "source": news.source,
            "published_at": news.published_at.isoformat() if news.published_at else None,
            "created_at": news.created_at.isoformat() if news.created_at else None,
        }
