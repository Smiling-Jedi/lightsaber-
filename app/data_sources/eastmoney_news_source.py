"""
东方财富新闻数据源（通过 akshare）
适用于：港股、A股
"""
import logging
from datetime import datetime
from typing import List

from app.data_sources.base import BaseDataSource, NewsData

logger = logging.getLogger(__name__)


class EastmoneyNewsSource(BaseDataSource):
    """东方财富新闻数据源，中文新闻，港股/A股效果好"""

    def get_price(self, symbol: str):
        raise NotImplementedError("EastmoneyNewsSource 不提供股价数据")

    def _convert_symbol(self, symbol: str) -> str:
        """将内部 symbol 转为东方财富格式
        HK:00700 → 00700
        A:002594 → 002594
        US:TSLA → TSLA (但效果不好)
        """
        if ":" in symbol:
            market, code = symbol.split(":", 1)
            return code
        return symbol

    def get_news(self, symbol: str, max_results: int = 10) -> List[NewsData]:
        """获取东方财富新闻"""
        try:
            import akshare as ak

            em_symbol = self._convert_symbol(symbol)
            logger.info(f"EastmoneyNews: 查询 {symbol} -> {em_symbol}")

            # 调用 akshare 获取东方财富新闻
            df = ak.stock_news_em(symbol=em_symbol)

            if df is None or df.empty:
                logger.warning(f"东方财富无新闻: {symbol}")
                return []

            news_list = []
            for _, row in df.head(max_results).iterrows():
                try:
                    # 解析时间
                    pub_str = row.get("发布时间", "")
                    published_at = self._parse_datetime(pub_str)

                    news = NewsData(
                        stock_symbol=symbol,
                        title=row.get("新闻标题", ""),
                        url=row.get("新闻链接", ""),
                        source=row.get("文章来源", "东方财富"),
                        summary=row.get("新闻内容", "")[:200] if row.get("新闻内容") else "",
                        published_at=published_at,
                    )
                    news_list.append(news)
                except Exception as e:
                    logger.warning(f"解析新闻项失败: {e}")
                    continue

            logger.info(f"东方财富返回 {len(news_list)} 条新闻: {symbol}")
            return news_list

        except Exception as e:
            logger.warning(f"东方财富获取新闻失败: {symbol} - {e}")
            return []

    def _parse_datetime(self, dt_str: str) -> datetime:
        """解析东方财富时间格式"""
        if not dt_str:
            return datetime.now()
        try:
            # 格式: 2026-03-31 08:35:00
            return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                # 尝试其他格式
                return datetime.strptime(dt_str[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return datetime.now()
