"""
富途 OpenD 连接管理器

解决性能问题：避免每次请求都新建 OpenQuoteContext（每次连接耗时 2-3 秒）
改为单例模式，全局复用同一个连接
"""
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class FutuConnectionManager:
    """
    OpenD 连接管理器（线程安全的单例模式）

    使用方式：
        ctx = FutuConnectionManager.get_context()
        ret, data = ctx.get_market_snapshot(codes)
        # 不需要手动 close，程序退出时统一清理
    """
    _instance: Optional['FutuConnectionManager'] = None
    _lock = threading.Lock()
    _ctx = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_context(cls):
        """获取 OpenQuoteContext 实例（全局复用）"""
        if cls._ctx is None:
            with cls._lock:
                if cls._ctx is None:
                    try:
                        from futu import OpenQuoteContext
                        cls._ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                        logger.info("OpenD 连接已建立（全局复用）")
                    except Exception as e:
                        logger.error(f"OpenD 连接建立失败: {e}")
                        raise
        return cls._ctx

    @classmethod
    def close(cls):
        """关闭连接（程序退出时调用）"""
        if cls._ctx is not None:
            try:
                cls._ctx.close()
                logger.info("OpenD 连接已关闭")
            except Exception as e:
                logger.warning(f"关闭 OpenD 连接时出错: {e}")
            finally:
                cls._ctx = None

    @classmethod
    def is_connected(cls) -> bool:
        """检查连接是否可用"""
        return cls._ctx is not None


def get_futu_context():
    """获取富途 OpenD 连接上下文（快捷函数）"""
    return FutuConnectionManager.get_context()


def close_futu_connection():
    """关闭富途 OpenD 连接（程序退出时调用）"""
    FutuConnectionManager.close()
