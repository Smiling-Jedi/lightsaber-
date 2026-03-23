"""
富途持仓同步服务

从富途 OpenD 实时拉取持仓 + 快照，自动同步到本地 DB。
- 股票基本信息 (Stock)：自动创建/更新
- 持仓数据 (Position)：自动创建/更新 qty、cost_price、当前价
- 现金余额 (CashBalance)：按市场同步富途账户现金
- base_shares（底仓）：首次创建时默认=总股数；已有记录不覆盖，保留用户手动设置
- 不在富途持仓里的本地记录：不删除（可能是已平仓记录，保留做历史）

需要 OpenD 运行在 127.0.0.1:11111
"""
import logging
import socket
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.position import Position
from app.models.cash import CashBalance

logger = logging.getLogger(__name__)

# 富途市场前缀 → (光剑市场, 货币)
MARKET_MAP = {
    "HK": ("HK", "HKD"),
    "US": ("US", "USD"),
    "SH": ("A", "CNY"),
    "SZ": ("A", "CNY"),
}

# 光剑市场 → 富途 TrdMarket key（用于对应 market_funds）
LIGHTSABER_MARKET_TO_FUTU = {
    "HK": "HK",
    "US": "US",
    "A":  "HK",  # A股通过港股通账户，暂用HK账户资金
}


class FutuSyncService:

    def __init__(self, db: Session):
        self.db = db

    def sync(self) -> Dict:
        """
        从富途拉取全部实盘持仓，同步到本地 DB。
        返回同步摘要 {"synced": N, "created": M, "errors": [...]}
        """
        try:
            futu_positions, market_funds = self._fetch_futu_positions()
        except Exception as e:
            logger.error(f"富途持仓拉取失败: {e}")
            return {"synced": 0, "created": 0, "errors": [str(e)]}

        synced, created, errors = 0, 0, []

        # 同步现金余额到 CashBalance 表
        try:
            self._sync_cash_balances(market_funds)
        except Exception as e:
            logger.warning(f"现金余额同步失败: {e}")

        # 获取快照拿实时价格
        futu_codes = [p["code"] for p in futu_positions]
        snapshots = self._fetch_snapshots(futu_codes)

        for pos_data in futu_positions:
            try:
                # 按代码前缀取对应市场的账户总资产
                market_prefix = pos_data["code"].split(".")[0]  # e.g. "HK" / "US"
                funds = market_funds.get(market_prefix, {})
                total_assets = float(funds.get("total_assets", 0))

                is_new = self._upsert_position(pos_data, snapshots, total_assets)
                synced += 1
                if is_new:
                    created += 1
            except Exception as e:
                errors.append(f"{pos_data.get('code')}: {e}")
                logger.warning(f"同步持仓失败 {pos_data.get('code')}: {e}")

        self.db.commit()
        logger.info(f"富途持仓同步完成: synced={synced}, created={created}, errors={len(errors)}")
        return {
            "synced": synced,
            "created": created,
            "errors": errors,
            "market_funds": {k: v.get("total_assets", 0) for k, v in market_funds.items()},
        }

    # ─────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────

    def _fetch_futu_positions(self) -> Tuple[List[Dict], Dict]:
        """
        调用富途 API 获取实盘持仓和各市场账户资金。
        返回 (positions, market_funds)
        market_funds: {"HK": {"total_assets": ..., "cash": ..., "currency": "HKD"}, "US": {...}}
        """
        # 快速探测 OpenD 是否在线，避免 SDK 无限重连阻塞
        try:
            with socket.create_connection(('127.0.0.1', 11111), timeout=1):
                pass
        except OSError:
            raise ConnectionError("富途 OpenD 未运行（127.0.0.1:11111 不可达）")

        from futu import OpenSecTradeContext, TrdEnv, TrdMarket, SecurityFirm, RET_OK

        positions = []
        market_funds: Dict[str, Dict] = {}

        # 每个市场期望的货币，用于过滤错误的账户数据
        expected_currency = {"HK": "HKD", "US": "USD"}

        # US市场优先用 FUTUINC（美元账户），HK市场优先用 FUTUSECURITIES（港元账户）
        market_configs = [
            (TrdMarket.HK, "HK", [SecurityFirm.FUTUSECURITIES, SecurityFirm.FUTUINC]),
            (TrdMarket.US, "US", [SecurityFirm.FUTUINC, SecurityFirm.FUTUSECURITIES]),
        ]

        for trd_market, market_key, firms in market_configs:
            for firm in firms:
                try:
                    ctx = OpenSecTradeContext(
                        filter_trdmarket=trd_market,
                        host='127.0.0.1', port=11111,
                        security_firm=firm,
                    )
                    try:
                        # 拉取持仓
                        ret, data = ctx.position_list_query(trd_env=TrdEnv.REAL)
                        if ret == RET_OK and not data.empty:
                            for _, row in data.iterrows():
                                pos = {
                                    "code":       row["code"],
                                    "name":       row["stock_name"],
                                    "qty":        int(row["qty"]),
                                    "cost_price": float(row["cost_price"]),
                                    "market_val": float(row["market_val"]),
                                    "pl_ratio":   float(row["pl_ratio"]),
                                    "pl_val":     float(row["pl_val"]),
                                }
                                # 去重（同代码可能在多个券商出现）
                                if not any(p["code"] == pos["code"] for p in positions):
                                    positions.append(pos)

                        # 拿该市场账户资金（每个市场只取一次）
                        if market_key not in market_funds:
                            ret2, fund_data = ctx.accinfo_query(trd_env=TrdEnv.REAL)
                            if ret2 == RET_OK and not fund_data.empty:
                                row = fund_data.iloc[0]
                                market_funds[market_key] = {
                                    "total_assets": float(row.get("total_assets", 0)),
                                    "cash":         float(row.get("cash", 0)),
                                    "currency":     str(row.get("currency", "HKD")),
                                    # 细分字段（港元账户特有）
                                    "hk_cash":      float(row.get("hk_cash", 0) or 0),
                                    "us_cash":      float(row.get("us_cash", 0) or 0),
                                    "fund_assets":  float(row.get("fund_assets", 0) or 0),
                                    "securities_assets": float(row.get("securities_assets", 0) or 0),
                                }
                    finally:
                        ctx.close()
                except Exception as e:
                    logger.warning(f"富途连接失败 {firm}/{market_key}: {e}")

        return positions, market_funds

    def _sync_cash_balances(self, market_funds: Dict[str, Dict]):
        """
        将富途账户现金余额同步到 CashBalance 表。

        字段说明（来自 accinfo_query）：
        - hk_cash: 港元现金（不含基金）
        - us_cash: 美元现金（不含基金）
        - fund_assets: 港元+美元活期基金合计（以港元计），API 不提供货币拆分
          → 存入 market="FUND" (currency=HKD) 作为独立行，不拆分至 HK/US
        """
        hk_funds = market_funds.get("HK", {})
        if not hk_funds:
            return

        # 港元现金（通常为0，因为全投了基金）
        hk_cash = Decimal(str(round(float(hk_funds.get("hk_cash", 0) or 0), 4)))
        cb_hk = self.db.get(CashBalance, "HK")
        if not cb_hk:
            cb_hk = CashBalance(market="HK", currency="HKD", amount=hk_cash)
            self.db.add(cb_hk)
        else:
            cb_hk.amount = hk_cash
            cb_hk.currency = "HKD"

        # 美元现金
        us_cash = Decimal(str(round(float(hk_funds.get("us_cash", 0) or 0), 4)))
        cb_us = self.db.get(CashBalance, "US")
        if not cb_us:
            cb_us = CashBalance(market="US", currency="USD", amount=us_cash)
            self.db.add(cb_us)
        else:
            cb_us.amount = us_cash
            cb_us.currency = "USD"

        # 活期基金（港元+美元合计，以HKD计，API无法拆分）
        # 存为 market="FUND"，在页面单独展示为"活期基金"
        fund_assets = Decimal(str(round(float(hk_funds.get("fund_assets", 0) or 0), 4)))
        cb_fund = self.db.get(CashBalance, "FUND")
        if not cb_fund:
            cb_fund = CashBalance(market="FUND", currency="HKD", amount=fund_assets)
            self.db.add(cb_fund)
        else:
            cb_fund.amount = fund_assets
            cb_fund.currency = "HKD"

        self.db.flush()
        logger.info(f"现金同步: HK={hk_cash} HKD, US={us_cash} USD, 基金={fund_assets} HKD")

    def _fetch_snapshots(self, futu_codes: List[str]) -> Dict[str, Dict]:
        """批量获取市场快照（实时价格）"""
        from futu import OpenQuoteContext, RET_OK

        if not futu_codes:
            return {}

        result = {}
        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        try:
            ret, data = ctx.get_market_snapshot(futu_codes)
            if ret == RET_OK:
                for _, row in data.iterrows():
                    result[row["code"]] = {
                        "current_price":    float(row.get("last_price", 0)),
                        "open_price":       float(row.get("open_price", 0)),
                        "prev_close_price": float(row.get("prev_close_price", 0)),
                        "high_price":       float(row.get("high_price", 0)),
                        "low_price":        float(row.get("low_price", 0)),
                        "volume":           int(row.get("volume", 0)),
                    }
        except Exception as e:
            logger.warning(f"快照获取失败: {e}")
        finally:
            ctx.close()

        return result

    def _upsert_position(self, pos_data: Dict, snapshots: Dict, total_assets: float) -> bool:
        """
        将单条富途持仓写入 DB（创建或更新）。
        返回 True 表示新建，False 表示更新。
        """
        futu_code = pos_data["code"]                    # e.g. "HK.00700"
        symbol    = futu_code.replace(".", ":", 1)      # → "HK:00700"
        market_prefix = futu_code.split(".")[0]
        market, currency = MARKET_MAP.get(market_prefix, ("HK", "HKD"))

        snap = snapshots.get(futu_code, {})
        current_price = snap.get("current_price") or (
            pos_data["market_val"] / pos_data["qty"] if pos_data["qty"] > 0 else 0
        )

        # 从快照获取价格数据（富途API已统一为港币/美元）
        open_price = snap.get("open_price", 0) or 0
        prev_close_price = snap.get("prev_close_price", 0) or 0
        high_price = snap.get("high_price", 0) or 0
        low_price = snap.get("low_price", 0) or 0

        # ── Stock ──────────────────────────────────────────
        stock = self.db.get(Stock, symbol)
        if not stock:
            stock = Stock(symbol=symbol, name=pos_data["name"],
                          market=market, currency=currency)
            self.db.add(stock)
        else:
            stock.name = pos_data["name"]

        stock.current_price     = Decimal(str(round(current_price, 4)))
        stock.open_price        = Decimal(str(open_price))
        stock.prev_close_price  = Decimal(str(prev_close_price))
        stock.high_price        = Decimal(str(high_price))
        stock.low_price         = Decimal(str(low_price))
        stock.volume            = snap.get("volume", 0)
        stock.price_updated_at  = datetime.now()

        # ── Position ───────────────────────────────────────
        position = self.db.query(Position).filter_by(stock_symbol=symbol).first()
        total_shares = pos_data["qty"]
        avg_cost     = Decimal(str(round(pos_data["cost_price"], 4)))
        is_new = False

        if not position:
            position = Position(
                stock_symbol=symbol,
                total_shares=total_shares,
                base_shares=total_shares,       # 首次默认全部算底仓
                avg_cost=avg_cost,
                currency=currency,
                market_total_fund=Decimal(str(total_assets)),
            )
            self.db.add(position)
            is_new = True
        else:
            position.total_shares      = total_shares
            # 负成本（历史卖出已回收成本）不被富途同步覆盖，保留手动设置值
            if position.avg_cost is None or position.avg_cost >= 0:
                position.avg_cost = avg_cost
            position.market_total_fund = Decimal(str(total_assets))
            # base_shares 不覆盖，保留用户手动设置的底仓数

        self.db.flush()
        return is_new
