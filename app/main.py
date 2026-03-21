"""
FastAPI 主应用入口
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db, init_db
from app.routers import position_router, dashboard_router, api_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized.")
    yield
    # 关闭时清理
    logger.info("Shutting down...")


# 创建 FastAPI 应用
app = FastAPI(
    title="光剑 (Lightsaber) - 股票交易辅助决策系统",
    description="个人持仓管理与交易建议系统",
    version="1.0.0",
    lifespan=lifespan
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 模板引擎
templates = Jinja2Templates(directory="app/templates")

# 注册路由
app.include_router(position_router.router, prefix="/positions", tags=["持仓管理"])
app.include_router(dashboard_router.router, prefix="/dashboard", tags=["仪表盘"])
app.include_router(api_router.router, prefix="/api", tags=["API接口"])


@app.get("/")
async def root(request: Request):
    """首页重定向到持仓列表"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/positions/")


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "service": "lightsaber"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
