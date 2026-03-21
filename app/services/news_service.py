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
from app.services.news_process_service import process_news

logger = logging.getLogger(__name__)


class NewsService:
    """新闻服务类"""

    def __init__(self, db: Session):
        self.db = db
        self.news_source = NewsSource()

    def fetch_news_for_stock(self, stock: Stock, max_results: int = 10) -> List[News]:
        """
        获取单只股票的新闻

        Args:
            stock: 股票对象
            max_results: 最多获取几条

        Returns:
            新闻对象列表
        """
        try:
            # 直接传完整 symbol（news_source 内部处理 HK:00700 → 0700.HK 转换）
            news_data_list = self.news_source.get_news(stock.symbol, max_results)

            # 过滤已存在的（URL 去重）
            new_items = []
            for news_data in news_data_list:
                existing = self.db.query(News).filter(News.url == news_data.url).first()
                if not existing:
                    new_items.append(news_data)

            if not new_items:
                return []

            # LLM 批量翻译+打分
            raw_dicts = [{"title": nd.title, "summary": nd.summary or ""} for nd in new_items]
            processed = process_news(raw_dicts)

            added_news = []
            for news_data, proc in zip(new_items, processed):
                news = News(
                    stock_symbol=stock.symbol,
                    title=news_data.title,
                    summary=news_data.summary or news_data.title[:100] + "...",
                    url=news_data.url,
                    source=news_data.source,
                    published_at=news_data.published_at,
                    title_zh=proc.get("title_zh"),
                    importance=proc.get("importance"),
                )
                self.db.add(news)
                added_news.append(news)

            self.db.commit()
            logger.info(f"为 {stock.symbol} 新增 {len(added_news)} 条新闻")

            return added_news

        except Exception as e:
            logger.error(f"获取 {stock.symbol} 新闻失败: {e}")
            return []

    def fetch_all_news(self, max_per_stock: int = 10) -> Dict:
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

    def get_top_news(self, symbol: str, limit: int = 5) -> List[News]:
        """返回3天内的新闻，按重要度+时间倒序，最多 limit 条"""
        from sqlalchemy import case
        cutoff = datetime.now() - timedelta(days=3)
        importance_order = case(
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2},
            value=News.importance,
            else_=3,
        )
        return (
            self.db.query(News)
            .filter(
                News.stock_symbol == symbol,
                News.published_at >= cutoff,
            )
            .order_by(importance_order, News.published_at.desc())
            .limit(limit)
            .all()
        )

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
        """将新闻对象转为字典（用于 API 返回）"""
        return {
            "id": news.id,
            "symbol": news.stock_symbol,
            "title": news.title,
            "title_zh": news.title_zh,
            "summary": news.summary,
            "url": news.url,
            "source": news.source,
            "importance": news.importance,
            "published_at": news.published_at.isoformat() if news.published_at else None,
            "fetched_at": news.fetched_at.isoformat() if news.fetched_at else None,
        }
