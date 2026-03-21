"""
测试配置和公共 fixtures
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import Base
from app.models import Stock, Position, Trade, News


@pytest.fixture(scope="function")
def db_engine():
    """每个测试函数使用独立的内存数据库"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db(db_engine):
    """数据库会话 fixture"""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_stock_hk(db):
    """港股样本数据"""
    stock = Stock(
        symbol="HK:00700",
        name="腾讯控股",
        market="HK",
        currency="HKD",
        sector="科技",
    )
    db.add(stock)
    db.commit()
    return stock


@pytest.fixture
def sample_stock_us(db):
    """美股样本数据"""
    stock = Stock(
        symbol="US:TSLA",
        name="特斯拉",
        market="US",
        currency="USD",
        sector="新能源",
    )
    db.add(stock)
    db.commit()
    return stock


@pytest.fixture
def sample_stock_a(db):
    """A股样本数据"""
    stock = Stock(
        symbol="A:600519",
        name="贵州茅台",
        market="A",
        currency="CNY",
        sector="消费",
    )
    db.add(stock)
    db.commit()
    return stock
