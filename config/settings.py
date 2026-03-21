"""
光剑系统配置
"""
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent.parent

# 数据目录
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# 历史数据缓存目录
HISTORY_DIR = DATA_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)

# 回测结果目录
BACKTEST_DIR = DATA_DIR / "backtest"
BACKTEST_DIR.mkdir(exist_ok=True)

# 数据库
DATABASE_URL = f"sqlite:///{DATA_DIR / 'lightsaber.db'}"

# API 配置（从环境变量或配置文件读取）
TUSHARE_TOKEN = "9c9112c76b1a88af0ebbcc5994b372f3c46b52a8abb7d84169fdc7bb"
ALPHA_VANTAGE_KEY = "K3UPHWTREIVCGOA1"

# 数据源配置
DATA_SOURCE_CONFIG = {
    "tushare": {
        "enabled": True,
        "token": TUSHARE_TOKEN,
        "base_url": "https://api.tushare.pro",
        "retry_count": 3,
        "retry_delay": 1,
    },
    "yahoo": {
        "enabled": True,
        "base_url": "https://query1.finance.yahoo.com",
        "retry_count": 3,
        "retry_delay": 1,
        "proxy": None,  # 可选代理配置
    },
    "sina_news": {
        "enabled": True,
        "rss_url": "https://rss.sina.com.cn/finance/stock/{symbol}.xml",
        "max_news_per_stock": 5,
        "retry_count": 3,
    },
    "exchange_rate": {
        "enabled": True,
        "base_url": "https://api.exchangerate-api.com/v4/latest/",
    },
}

# 缓存配置
CACHE_CONFIG = {
    "price_ttl": 300,  # 股价缓存5分钟
    "news_ttl": 3600,  # 新闻缓存1小时
    "rate_ttl": 86400,  # 汇率缓存1天
}
