"""
数据库连接管理
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from config.settings import DATABASE_URL

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 模型基类
Base = declarative_base()


def get_db():
    """获取数据库会话（生成器，用于依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表"""
    from app.models import stock, position, trade, news, signal_log

    Base.metadata.create_all(bind=engine)

    # 补 news 表新增字段（SQLite 不支持 IF NOT EXISTS，需手动检查）
    if "sqlite" in DATABASE_URL:
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(news)"))]
            if "title_zh" not in cols:
                conn.execute(text("ALTER TABLE news ADD COLUMN title_zh VARCHAR(500)"))
            if "importance" not in cols:
                conn.execute(text("ALTER TABLE news ADD COLUMN importance VARCHAR(10)"))
            conn.commit()
