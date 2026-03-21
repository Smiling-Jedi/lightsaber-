"""
股价更新服务
处理股价获取、缓存更新、数据源切换
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.data_sources.base import DataSourceError, MaxRetriesExceededError
from app.data_sources.aggregated_source import AggregatedPriceSource
from app.data_sources.exchange_rate_source import ExchangeRateSource

logger = logging.getLogger(__name__)


class PriceService:
    """股价更新服务"""

    def __init__(self, db: Session):
        self.db = db
        self.price_source = AggregatedPriceSource()
        self.exchange = ExchangeRateSource()

    def update_single_stock(self, stock: Stock) -> Tuple[bool, str]:
        """
        更新单只股票的股价

        Returns:
            (success: bool, message: str)
        """
        try:
            logger.info(f"更新股价: {stock.symbol}")
            price_data = self.price_source.get_price(stock.symbol)

            # 更新股票记录
            stock.current_price = price_data.current_price
            stock.open_price = price_data.open_price
            stock.high_price = price_data.high_price
            stock.low_price = price_data.low_price
            stock.volume = price_data.volume
            stock.price_updated_at = datetime.now()

            self.db.commit()

            return True, f"成功更新 {stock.symbol}: {price_data.current_price}"

        except MaxRetriesExceededError as e:
            logger.error(f"更新 {stock.symbol} 失败: 重试耗尽 - {e}")
            return False, f"更新失败: 网络错误"

        except DataSourceError as e:
            logger.error(f"更新 {stock.symbol} 失败: 数据源错误 - {e}")
            return False, f"更新失败: {str(e)}"

        except Exception as e:
            logger.error(f"更新 {stock.symbol} 失败: 未知错误 - {e}")
            return False, f"更新失败: 未知错误"

    def update_all_prices(self) -> Dict:
        """
        更新所有持仓股票的股价

        Returns:
            {
                "total": int,
                "success": int,
                "failed": int,
                "details": [(symbol, success, message), ...],
                "updated_at": datetime
            }
        """
        # 获取所有有持仓的股票
        stocks = self.db.query(Stock).join(Stock.positions).all()

        results = {
            "total": len(stocks),
            "success": 0,
            "failed": 0,
            "details": [],
            "updated_at": datetime.now().isoformat()
        }

        for stock in stocks:
            success, message = self.update_single_stock(stock)

            if success:
                results["success"] += 1
            else:
                results["failed"] += 1

            results["details"].append({
                "symbol": stock.symbol,
                "name": stock.name,
                "success": success,
                "message": message,
                "price": float(stock.current_price) if stock.current_price else None
            })

        logger.info(f"股价更新完成: 成功 {results['success']}/{results['total']}")
        return results

    def update_market_prices(self, market: str) -> Dict:
        """
        按市场更新股价

        Args:
            market: "A", "HK", or "US"
        """
        stocks = (
            self.db.query(Stock)
            .join(Stock.positions)
            .filter(Stock.market == market)
            .all()
        )

        results = {
            "market": market,
            "total": len(stocks),
            "success": 0,
            "failed": 0,
            "details": [],
            "updated_at": datetime.now().isoformat()
        }

        for stock in stocks:
            success, message = self.update_single_stock(stock)

            if success:
                results["success"] += 1
            else:
                results["failed"] += 1

            results["details"].append({
                "symbol": stock.symbol,
                "success": success,
                "message": message
            })

        return results

    def get_price_history(self, symbol: str, days: int = 30) -> List[Dict]:
        """
        获取股票历史价格（用于图表展示）
        预留接口，目前返回空列表
        """
        # TODO: 实现历史数据获取
        # 需要扩展数据源适配器支持 get_history 方法
        logger.warning(f"历史数据获取暂未实现: {symbol}")
        return []

    def get_exchange_rate(self, from_currency: str, to_currency: str = "CNY") -> Decimal:
        """
        获取汇率
        """
        try:
            return self.exchange.get_rate(from_currency, to_currency)
        except Exception as e:
            logger.error(f"获取汇率失败 {from_currency}->{to_currency}: {e}")
            # 返回硬编码汇率作为备用
            fallback_rates = {
                ("USD", "CNY"): Decimal("7.2"),
                ("HKD", "CNY"): Decimal("0.92"),
                ("CNY", "CNY"): Decimal("1.0"),
            }
            return fallback_rates.get((from_currency, to_currency), Decimal("1.0"))

    def get_last_update_time(self) -> Optional[datetime]:
        """
        获取最近一次的股价更新时间
        """
        latest = (
            self.db.query(Stock)
            .filter(Stock.price_updated_at.isnot(None))
            .order_by(Stock.price_updated_at.desc())
            .first()
        )
        return latest.price_updated_at if latest else None
