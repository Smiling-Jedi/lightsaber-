"""
富途历史成交同步服务

功能：
- 调用富途 deal_list_query 拉取历史成交流水
- 写入本地 trades 表
- 以 futu_order_id 做幂等去重（重复不写）

调用时机：每日收盘后，由 scripts/refresh_prices.py 触发
"""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.trade import Trade
from app.models.position import Position

logger = logging.getLogger(__name__)


class FutuDealSyncService:

    def __init__(self, db: Session):
        self.db = db

    def sync(self) -> Dict:
        """
        从富途拉取所有持仓股的历史成交，写入本地 trades 表。
        返回 {"synced": N, "skipped": M, "errors": [...]}
        """
        try:
            deals = self._fetch_deals()
        except Exception as e:
            logger.error(f"富途成交拉取失败: {e}")
            return {"synced": 0, "skipped": 0, "errors": [str(e)]}

        synced = skipped = 0
        errors = []

        for deal in deals:
            try:
                with self.db.begin_nested():   # savepoint：单条失败不影响其他
                    result = self._upsert_deal(deal)
                if result == "new":
                    synced += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(f"{deal.get('code')}: {e}")
                logger.warning(f"成交写入失败 {deal.get('code')}: {e}")

        self.db.commit()
        logger.info(f"富途成交同步: synced={synced}, skipped={skipped}, errors={len(errors)}")
        return {"synced": synced, "skipped": skipped, "errors": errors}

    # ─────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────

    def _fetch_deals(self) -> List[Dict]:
        """调用富途 deal_list_query 拉取成交流水"""
        from futu import OpenSecTradeContext, TrdEnv, TrdMarket, SecurityFirm, RET_OK

        deals = []
        market_configs = [
            (TrdMarket.HK, [SecurityFirm.FUTUSECURITIES, SecurityFirm.FUTUINC]),
            (TrdMarket.US, [SecurityFirm.FUTUINC, SecurityFirm.FUTUSECURITIES]),
        ]

        for trd_market, firms in market_configs:
            for firm in firms:
                try:
                    ctx = OpenSecTradeContext(
                        filter_trdmarket=trd_market,
                        host='127.0.0.1', port=11111,
                        security_firm=firm,
                    )
                    try:
                        ret, data = ctx.deal_list_query(trd_env=TrdEnv.REAL)
                        if ret == RET_OK and not data.empty:
                            for _, row in data.iterrows():
                                deal = {
                                    "order_id":  str(row.get("order_id", "")),
                                    "deal_id":   str(row.get("deal_id", "")),
                                    "code":      str(row.get("code", "")),
                                    "name":      str(row.get("stock_name", "")),
                                    "side":      str(row.get("trd_side", "") or "").upper(),  # BUY / SELL
                                    "qty":       int(row.get("qty", 0)),
                                    "price":     float(row.get("price", 0)),
                                    "deal_time": str(row.get("create_time", "") or "")[:10],  # 只取日期
                                }
                                # 去重（同订单可能在两个市场配置里都出现）
                                futu_id = deal["order_id"] or deal["deal_id"]
                                if futu_id and not any(
                                    (d.get("order_id") or d.get("deal_id")) == futu_id
                                    for d in deals
                                ):
                                    deals.append(deal)
                    finally:
                        ctx.close()
                    break  # 该市场成功拉取后跳出 firms 循环
                except Exception as e:
                    logger.warning(f"富途成交拉取失败 market={trd_market} firm={firm}: {e}")

        return deals

    def _upsert_deal(self, deal: Dict) -> str:
        """
        将单条成交写入 trades 表。
        futu_order_id 相同则跳过（幂等）。
        返回 "new" 或 "skip"。
        """
        futu_order_id = deal.get("order_id") or deal.get("deal_id")
        if not futu_order_id:
            return "skip"

        # 幂等检查
        exists = self.db.query(Trade).filter_by(futu_order_id=futu_order_id).first()
        if exists:
            return "skip"

        # 找对应 position（按 symbol）
        raw_code = deal["code"]
        symbol = raw_code.replace(".", ":", 1)  # HK.00700 → HK:00700 / US.TSLA → US:TSLA
        if ":" not in symbol:
            # 无前缀（如纯 "TSLA"），无法匹配，跳过并告警
            logger.warning(f"成交 code 格式无法识别，跳过: {raw_code!r}")
            return "skip"
        position = self.db.query(Position).filter_by(stock_symbol=symbol).first()
        if not position:
            logger.warning(f"未找到对应持仓，跳过成交: {symbol}")
            return "skip"

        price = Decimal(str(deal["price"]))
        qty   = deal["qty"]
        trade = Trade(
            position_id   = position.id,
            trade_type    = "BUY" if deal["side"] == "BUY" else "SELL",
            shares        = qty,
            price         = price,
            trading_cost  = Decimal("0"),
            total_cost    = price * qty,
            is_swing      = False,
            remaining_shares = qty if deal["side"] == "BUY" else 0,
            trade_date    = (datetime.strptime(deal["deal_time"], "%Y-%m-%d").date()
                             if deal["deal_time"] and len(deal["deal_time"]) == 10
                             else datetime.now().date()),
            futu_order_id = futu_order_id,
        )
        self.db.add(trade)
        return "new"
