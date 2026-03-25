"""
信号缓存服务

缓存策略：
- 收盘后（15:00-次日09:30）：缓存2小时或直到开盘
- 开盘中（09:30-15:00）：缓存15分钟
- 手动刷新：强制重新计算

缓存键：{date}_{symbol}
"""
import json
import logging
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.signal_service import SignalResult

logger = logging.getLogger(__name__)

# 缓存目录
CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "signal_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class SignalCache:
    """信号缓存管理器"""

    # 缓存时间配置（分钟）
    CACHE_DURATION_CLOSED = 120  # 收盘后：2小时
    CACHE_DURATION_OPEN = 15     # 开盘中：15分钟

    def __init__(self):
        self._memory_cache: Dict[str, tuple] = {}  # symbol -> (result, timestamp)

    def _get_cache_key(self, symbol: str, date_str: str = None) -> str:
        """生成缓存键"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")
        return f"{date_str}_{symbol}"

    def _get_cache_file(self, key: str) -> Path:
        """获取缓存文件路径"""
        return CACHE_DIR / f"{key}.pkl"

    def _is_market_open(self) -> bool:
        """判断当前是否开盘时间（A股/港股 09:30-15:00）"""
        now = datetime.now()
        weekday = now.weekday()

        # 周末闭市
        if weekday >= 5:
            return False

        # 交易时间 09:30-15:00
        time_str = now.strftime("%H:%M")
        return "09:30" <= time_str <= "15:00"

    def _get_cache_duration(self) -> int:
        """获取当前缓存时长（分钟）"""
        return self.CACHE_DURATION_OPEN if self._is_market_open() else self.CACHE_DURATION_CLOSED

    def get(self, symbol: str, date_str: str = None) -> Optional["SignalResult"]:
        """
        获取缓存的信号

        Returns:
            SignalResult: 缓存的信号结果，如果过期或不存在则返回None
        """
        key = self._get_cache_key(symbol, date_str)

        # 1. 先检查内存缓存
        if key in self._memory_cache:
            result, timestamp = self._memory_cache[key]
            if datetime.now() - timestamp < timedelta(minutes=self._get_cache_duration()):
                logger.debug(f"内存缓存命中: {symbol}")
                return result
            else:
                # 过期，移除
                del self._memory_cache[key]

        # 2. 检查文件缓存
        cache_file = self._get_cache_file(key)
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    data = pickle.load(f)

                timestamp = data.get("timestamp")
                result = data.get("result")

                # 检查是否过期
                if datetime.now() - timestamp < timedelta(minutes=self._get_cache_duration()):
                    # 加载到内存缓存
                    self._memory_cache[key] = (result, timestamp)
                    logger.debug(f"文件缓存命中: {symbol}")
                    return result
                else:
                    # 过期，删除文件
                    cache_file.unlink()
                    logger.debug(f"文件缓存过期已删除: {symbol}")

            except Exception as e:
                logger.warning(f"读取缓存失败 {symbol}: {e}")
                if cache_file.exists():
                    cache_file.unlink()

        return None

    def set(self, symbol: str, result: "SignalResult", date_str: str = None):
        """保存信号到缓存"""
        key = self._get_cache_key(symbol, date_str)
        timestamp = datetime.now()

        # 1. 保存到内存
        self._memory_cache[key] = (result, timestamp)

        # 2. 保存到文件（持久化）
        cache_file = self._get_cache_file(key)
        try:
            with open(cache_file, "wb") as f:
                pickle.dump({"result": result, "timestamp": timestamp}, f)
            logger.debug(f"缓存已保存: {symbol}")
        except Exception as e:
            logger.warning(f"保存缓存失败 {symbol}: {e}")

    def clear(self, symbol: str = None, date_str: str = None):
        """
        清除缓存

        Args:
            symbol: 指定股票代码，None表示清除所有
            date_str: 指定日期，None表示今天
        """
        if symbol:
            # 清除指定股票的缓存
            key = self._get_cache_key(symbol, date_str)
            if key in self._memory_cache:
                del self._memory_cache[key]
            cache_file = self._get_cache_file(key)
            if cache_file.exists():
                cache_file.unlink()
            logger.info(f"缓存已清除: {symbol}")
        else:
            # 清除所有缓存
            self._memory_cache.clear()
            for f in CACHE_DIR.glob("*.pkl"):
                f.unlink()
            logger.info("所有缓存已清除")

    def get_portfolio_cache(self, symbols: List[str], date_str: str = None) -> Dict[str, "SignalResult"]:
        """
        批量获取持仓信号缓存
        返回: {symbol: SignalResult} 的缓存命中结果
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")

        results = {}
        symbols_to_fetch = []

        # 1. 先检查内存缓存
        for symbol in symbols:
            key = self._get_cache_key(symbol, date_str)
            if key in self._memory_cache:
                result, timestamp = self._memory_cache[key]
                if datetime.now() - timestamp < timedelta(minutes=self._get_cache_duration()):
                    results[symbol] = result
                    continue
                else:
                    del self._memory_cache[key]
            symbols_to_fetch.append(symbol)

        # 2. 检查文件缓存（批量读取）
        for symbol in symbols_to_fetch:
            key = self._get_cache_key(symbol, date_str)
            cache_file = self._get_cache_file(key)
            if cache_file.exists():
                try:
                    with open(cache_file, "rb") as f:
                        data = pickle.load(f)
                    timestamp = data.get("timestamp")
                    result = data.get("result")

                    if datetime.now() - timestamp < timedelta(minutes=self._get_cache_duration()):
                        self._memory_cache[key] = (result, timestamp)
                        results[symbol] = result
                    else:
                        cache_file.unlink()
                except Exception:
                    if cache_file.exists():
                        cache_file.unlink()

        logger.info(f"批量缓存: 命中 {len(results)}/{len(symbols)} 个信号")
        return results

    def set_portfolio_cache(self, results: List["SignalResult"], date_str: str = None):
        """批量保存持仓信号缓存"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")

        timestamp = datetime.now()

        for result in results:
            key = self._get_cache_key(result.symbol, date_str)
            self._memory_cache[key] = (result, timestamp)

            cache_file = self._get_cache_file(key)
            try:
                with open(cache_file, "wb") as f:
                    pickle.dump({"result": result, "timestamp": timestamp}, f)
            except Exception as e:
                logger.warning(f"保存缓存失败 {result.symbol}: {e}")
        """清除所有过期的缓存文件"""
        now = datetime.now()
        duration = timedelta(minutes=self._get_cache_duration())

        for cache_file in CACHE_DIR.glob("*.pkl"):
            try:
                with open(cache_file, "rb") as f:
                    data = pickle.load(f)
                timestamp = data.get("timestamp")

                if now - timestamp > duration:
                    cache_file.unlink()
                    logger.debug(f"过期缓存已清理: {cache_file.name}")

            except Exception:
                # 损坏的文件直接删除
                cache_file.unlink()


# 全局缓存实例
_signal_cache: Optional[SignalCache] = None


def get_signal_cache() -> SignalCache:
    """获取全局信号缓存实例"""
    global _signal_cache
    if _signal_cache is None:
        _signal_cache = SignalCache()
    return _signal_cache
