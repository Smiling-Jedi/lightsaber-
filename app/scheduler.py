"""
定时任务调度器
港股新闻：16:15 HKT（收盘后）
美股新闻：05:30 HKT（次日，约美股收盘后1小时）
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def _fetch_market_news(db_factory, market: str):
    """定时任务：拉取指定市场的新闻"""
    from app.services.news_service import NewsService
    from app.models.stock import Stock

    db = db_factory()
    try:
        svc = NewsService(db)
        stocks = db.query(Stock).join(Stock.positions).filter(Stock.market == market).all()
        total_added = 0
        for stock in stocks:
            added = svc.fetch_news_for_stock(stock)
            total_added += len(added)
        logger.info(f"[Scheduler] {market} 新闻更新完成，新增 {total_added} 条")
    except Exception as e:
        logger.error(f"[Scheduler] {market} 新闻更新失败: {e}")
    finally:
        db.close()


def create_scheduler(db_factory):
    """创建并配置调度器"""
    scheduler = BackgroundScheduler(timezone="Asia/Hong_Kong")

    # 港股：16:15 HKT
    scheduler.add_job(
        lambda: _fetch_market_news(db_factory, "HK"),
        CronTrigger(hour=16, minute=15, timezone="Asia/Hong_Kong"),
        id="news_hk",
        name="港股新闻定时拉取",
        replace_existing=True,
    )

    # 美股：次日 05:30 HKT（约美股收盘后1小时）
    scheduler.add_job(
        lambda: _fetch_market_news(db_factory, "US"),
        CronTrigger(hour=5, minute=30, timezone="Asia/Hong_Kong"),
        id="news_us",
        name="美股新闻定时拉取",
        replace_existing=True,
    )

    return scheduler
