"""
数据源适配器模块
"""
from app.data_sources.base import BaseDataSource, PriceData, NewsData
from app.data_sources.tushare_source import TushareSource
from app.data_sources.yahoo_source import YahooSource
from app.data_sources.yahoo_finance import YahooFinanceSource
from app.data_sources.eastmoney_source import EastMoneySource
from app.data_sources.alpha_vantage_source import AlphaVantageSource
from app.data_sources.aggregated_source import AggregatedPriceSource
from app.data_sources.news_source import SinaNewsSource
from app.data_sources.exchange_rate_source import ExchangeRateSource

__all__ = [
    "BaseDataSource",
    "PriceData",
    "NewsData",
    "TushareSource",
    "YahooSource",
    "YahooFinanceSource",
    "EastMoneySource",
    "AlphaVantageSource",
    "AggregatedPriceSource",
    "SinaNewsSource",
    "ExchangeRateSource",
]
