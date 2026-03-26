"""
富途价格数据源 - 通过 OpenD 批量获取实时快照
一次 API call 拿全部股票，比逐只拉取快几十倍
"""
import socket
import logging
from typing import Dict, List

from app.data_sources.futu_connection import get_futu_context

logger = logging.getLogger(__name__)

HOST = '127.0.0.1'
PORT = 11111


def is_opend_available() -> bool:
    """探测 OpenD 是否在线"""
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            return True
    except OSError:
        return False


def get_snapshots(futu_codes: List[str]) -> Dict[str, Dict]:
    """
    批量获取价格快照
    富途 API 不能同时查询不同市场，需要按市场分组

    Args:
        futu_codes: 富途格式代码列表，如 ["HK.00700", "US.AAPL"]

    Returns:
        {futu_code: {current_price, open_price, high_price, low_price, volume}}

    Raises:
        ConnectionError: OpenD 不可达
    """
    from futu import RET_OK

    # 按市场分组
    market_groups: Dict[str, List[str]] = {}
    for code in futu_codes:
        market = code.split(".")[0]
        market_groups.setdefault(market, []).append(code)

    result = {}
    # 使用全局复用的连接
    ctx = get_futu_context()

    for market, codes in market_groups.items():
        try:
            ret, data = ctx.get_market_snapshot(codes)
            if ret == RET_OK:
                for _, row in data.iterrows():
                    last_price = float(row.get("last_price", 0))
                    prev_close = float(row.get("prev_close_price", 0))
                    change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    result[row["code"]] = {
                        "current_price":    last_price,
                        "prev_close_price": prev_close,
                        "open_price":       float(row.get("open_price", 0)),
                        "high_price":       float(row.get("high_price", 0)),
                        "low_price":        float(row.get("low_price", 0)),
                        "volume":           int(row.get("volume", 0)),
                        "change_pct":       change_pct,
                    }
            else:
                logger.warning(f"{market} 市场快照失败: {data}")
        except Exception as e:
            logger.warning(f"{market} 市场快照异常: {e}")

    return result
