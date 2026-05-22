"""
富途持仓同步服务

【数据维度说明】（重要！以下三个维度完全独立，禁止混为一谈）

1. 【持仓同步】（数量/成本/交易流水）
   - 港股：✅ 富途OpenD API自动获取
   - 美股：✅ 富途OpenD API自动获取
   - A股：✗ 无API支持，必须用户手动录入（截图/口头告知）

2. 【价格更新】（当前价/开盘价/收盘价等）
   - 港股：OpenD > Tushare > Yahoo
   - 美股：OpenD > Tushare > Yahoo
   - A股：Tushare > EastMoney > akshare（注意：A股无OpenD选项）

3. 【现金余额】
   - HK_CASH：✅ 富途OpenD API
   - US_CASH：✅ 富途OpenD API
   - A_CASH：✗ 用户手动录入
   - FUND：✅ 富途OpenD API（返回港币合计，需拆分）

【本服务处理范围】
本服务只处理维度1（持仓同步）和维度3（现金余额）中的港/美股部分。
A股持仓数量和A股现金余额需通过其他方式（截图/口头告知）手动更新。

需要 OpenD 运行在 127.0.0.1:11111
"""
import logging
import socket
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.position import Position
from app.models.cash import CashBalance
from app.models.trade import Trade
from app.services.position_audit_service import PositionAuditService

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
        从富途拉取港/美股实盘持仓，同步到本地 DB。

        ⚠️ 注意：本方法只同步港/美股持仓（HK/US），A股持仓不在富途OpenD覆盖范围内，
        需通过 scripts/import_a_shares.py 或其他方式手动录入。

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

        # 【新增】标记已清仓持仓：在富途持仓中不存在但本地有持仓的记录
        closed_count = self._mark_closed_positions(futu_positions)
        if closed_count > 0:
            synced += closed_count  # 将清仓标记计入同步统计

        self.db.commit()
        # 【数据保护】验证A股持仓一致性
        audit_service = PositionAuditService(self.db)
        validation_result = audit_service.validate_a_shares_consistency()
        if not validation_result["is_valid"]:
            for warning in validation_result["warnings"]:
                logger.warning(warning["message"])

        self.db.commit()
        logger.info(f"富途持仓同步完成: synced={synced}, created={created}, closed={closed_count}, errors={len(errors)}")

        # 同步交易流水（从周一开始）
        trades_synced, trades_created = self._sync_trades()

        # 【T+1限价单模式】检查PENDING信号是否成交
        signal_results = self._check_signal_executions()

        return {
            "synced": synced,
            "created": created,
            "errors": errors,
            "market_funds": {k: v.get("total_assets", 0) for k, v in market_funds.items()},
            "trades_synced": trades_synced,
            "trades_created": trades_created,
            "signal_check": signal_results,
        }

    # ─────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────

    def _fetch_futu_positions(self) -> Tuple[List[Dict], Dict]:
        """
        调用富途 API 获取港/美股实盘持仓和各市场账户资金。

        ⚠️ 注意：富途OpenD API只返回港/美股持仓，A股持仓需手动录入。

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

        # US市场优先用 FUTUINC（美元账户），HK市场优先用 FUTUSECURITIES（港元账户）
        # 注意：富途OpenD只覆盖港/美股持仓同步，A股持仓数量和A股现金需手动录入
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
                                # 注意：同一市场的不同券商返回的是相同数据，不累加
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
        将富途账户现金余额同步到 CashBalance 表（港/美股现金）。

        ⚠️ 注意：A股现金（market="A"）不在富途OpenD覆盖范围内，需手动录入。

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

        # 记录审计日志
        audit_service = PositionAuditService(self.db)

        if not position:
            position = Position(
                stock_symbol=symbol,
                total_shares=total_shares,
                base_shares=total_shares,       # 首次默认全部算底仓
                base_cost=avg_cost,             # OpenD cost_price 作为底仓成本
                avg_cost=avg_cost,
                currency=currency,
                market_total_fund=Decimal(str(total_assets)),
                source="FUTU_AUTO",
                last_sync_at=datetime.now(),
            )
            self.db.add(position)
            self.db.flush()

            # 记录创建审计日志
            audit_service.log_change(
                position, "total_shares", None, total_shares,
                change_reason="SYNC", source="FUTU"
            )
            is_new = True
        else:
            # 记录旧值
            old_shares = position.total_shares
            old_cost = position.avg_cost
            old_source = position.source

            position.total_shares      = total_shares
            # 负成本（历史卖出已回收成本）不被富途同步覆盖，保留手动设置值
            if position.avg_cost is None or position.avg_cost >= 0:
                position.avg_cost = avg_cost
            # base_cost 同步：若为空或负值，用 OpenD cost_price 填充
            if position.base_cost is None or position.base_cost <= 0:
                position.base_cost = avg_cost
            position.market_total_fund = Decimal(str(total_assets))
            position.source = "FUTU_AUTO" if old_source != "MANUAL" else "MIXED"
            position.last_sync_at = datetime.now()
            # base_shares 不覆盖，保留用户手动设置的底仓数

            # 记录变更审计日志
            if old_shares != total_shares:
                audit_service.log_change(
                    position, "total_shares", old_shares, total_shares,
                    change_reason="SYNC", source="FUTU"
                )
            if old_cost != avg_cost and (old_cost is None or old_cost >= 0):
                audit_service.log_change(
                    position, "avg_cost", old_cost, avg_cost,
                    change_reason="SYNC", source="FUTU"
                )

        self.db.flush()
        return is_new

    def _mark_closed_positions(self, futu_positions: List[Dict]) -> int:
        """
        标记已清仓的持仓：只处理富途能覆盖的市场（HK / US）。
        A 股市场持仓为手动录入/其他来源维护，不应被富途同步误清空。
        """
        # 获取富途返回的所有股票代码（转换为光剑格式）
        futu_codes = {p["code"].replace(".", ":", 1) for p in futu_positions}

        # 只查询富途覆盖市场的本地持仓（HK / US），跳过 A 股
        from sqlalchemy import or_
        local_positions = (
            self.db.query(Position)
            .filter(Position.total_shares > 0)
            .filter(
                or_(
                    Position.stock_symbol.like("HK:%"),
                    Position.stock_symbol.like("US:%"),
                )
            )
            .all()
        )

        closed_count = 0
        for pos in local_positions:
            if pos.stock_symbol not in futu_codes:
                # 该持仓在富途已不存在，标记为清仓
                pos.total_shares = 0
                # base_shares 也设为 0，保持一致性
                pos.base_shares = 0
                closed_count += 1
                logger.info(f"持仓已清仓: {pos.stock_symbol}")

        if closed_count > 0:
            logger.info(f"标记 {closed_count} 个已清仓持仓")

        return closed_count

    def _sync_trades(self) -> tuple:
        """
        从富途拉取交易流水（从周一开始），同步到 trades 表。
        deal_list_query 支持不传 code 获取全部成交记录。
        返回 (synced_count, created_count)
        """
        from futu import OpenSecTradeContext, TrdEnv, TrdMarket, SecurityFirm, RET_OK

        # 从周一开始（本周一）
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        synced, created = 0, 0

        # 先尝试 FUTUINC（数据更全），再尝试 FUTUSECURITIES
        market_configs = [
            (TrdMarket.HK, SecurityFirm.FUTUINC),
            (TrdMarket.US, SecurityFirm.FUTUINC),
            (TrdMarket.HK, SecurityFirm.FUTUSECURITIES),
            (TrdMarket.US, SecurityFirm.FUTUSECURITIES),
        ]

        processed_deal_ids = set()  # 去重

        for trd_market, firm in market_configs:
            try:
                ctx = OpenSecTradeContext(
                    filter_trdmarket=trd_market,
                    host='127.0.0.1', port=11111,
                    security_firm=firm,
                )
                try:
                    # 不传 code 参数，获取所有成交记录
                    ret, data = ctx.deal_list_query(trd_env=TrdEnv.REAL)
                    if data is not None and not data.empty:
                        logger.info(f"交易流水查询 [{trd_market}/{firm}]: 返回 {len(data)} 条")
                        for _, row in data.iterrows():
                            # 使用 create_time 字段（trd_time 通常为 None）
                            create_time = row.get("create_time", "")
                            if not create_time:
                                continue

                            try:
                                # 处理格式: 2026-03-23 12:54:16.811
                                time_str = str(create_time).split('.')[0]  # 去掉毫秒
                                trade_datetime = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                                if trade_datetime.date() < monday:
                                    continue  # 跳过周一之前的记录
                            except Exception as e:
                                logger.debug(f"时间解析失败: {create_time}, {e}")
                                continue

                            # 去重检查
                            deal_id = str(row.get("deal_id", ""))
                            if deal_id in processed_deal_ids:
                                continue
                            processed_deal_ids.add(deal_id)

                            if self._upsert_trade(row, trade_datetime.date()):
                                created += 1
                            else:
                                synced += 1
                finally:
                    ctx.close()
            except Exception as e:
                logger.warning(f"交易流水查询失败 [{trd_market}/{firm}]: {e}")

        self.db.commit()
        logger.info(f"交易流水同步完成: synced={synced}, created={created}")
        return synced, created

    def _upsert_trade(self, row, trade_date: date) -> bool:
        """
        将单条成交记录写入 trades 表。
        返回 True 表示新建，False 表示已存在跳过。
        """
        # 富途订单ID（幂等去重）
        deal_id = str(row.get("deal_id", ""))
        if not deal_id:
            deal_id = f"{row.get('order_id')}_{row.get('create_time')}"

        # 检查是否已存在
        existing = self.db.query(Trade).filter_by(futu_order_id=deal_id).first()
        if existing:
            return False  # 已存在，跳过

        # 解析交易方向
        trd_side = row.get("trd_side", "")
        # BUY / SELL / SELL_SHORT / BUY_BACK 等
        if "BUY" in trd_side:
            trade_type = "BUY"
        elif "SELL" in trd_side:
            trade_type = "SELL"
        else:
            trade_type = trd_side

        # 从 code 获取 symbol (e.g., "HK.00700" -> "HK:00700")
        futu_code = row.get("code", "")
        symbol = futu_code.replace(".", ":", 1) if "." in futu_code else futu_code

        # 查找对应的 position
        position = self.db.query(Position).filter_by(stock_symbol=symbol).first()
        position_id = position.id if position else None

        # 交易费用字段可能不存在，需要安全获取
        try:
            commission = float(row.get("commission", 0) or 0)
        except (TypeError, ValueError):
            commission = 0
        try:
            stamp_duty = float(row.get("stamp_duty", 0) or 0)
        except (TypeError, ValueError):
            stamp_duty = 0
        try:
            platform_fee = float(row.get("platform_fee", 0) or 0)
        except (TypeError, ValueError):
            platform_fee = 0

        trading_cost = Decimal(str(commission + stamp_duty + platform_fee))

        trade = Trade(
            position_id=position_id,
            trade_type=trade_type,
            shares=int(row.get("qty", 0)),
            price=Decimal(str(round(float(row.get("price", 0)), 4))),
            trading_cost=trading_cost,
            futu_order_id=deal_id,
            trade_date=trade_date,
        )

        self.db.add(trade)

        # 根据交易自动更新对应的基金金额
        self._update_fund_from_trade(row, trade_type)

        return True

    def _update_fund_from_trade(self, row, trade_type: str):
        """
        ⚠️ 已禁用：真实交易不再更新 HKD_FUND/USD_FUND

        原因：
        - HKD_FUND/USD_FUND 专用于模拟账户资金追踪
        - 真实交易的资金变动由 CashBalance 表（HK/US）记录
        - 避免真实/模拟账户数据污染

        如需追踪真实账户资金，请查询 CashBalance 表的 HK/US 市场记录。
        """
        # 完全禁用，不更新任何模拟账户字段
        return

    def _check_signal_executions(self) -> dict:
        """
        【T+1限价单模式】检查PENDING信号是否成交
        在每日价格同步完成后调用
        """
        try:
            from app.services.signal_execution_service import SignalExecutionService

            exec_svc = SignalExecutionService(self.db)

            # 检查T+1成交
            results = exec_svc.check_pending_signals()

            # 清理过期信号（超过3日未入场）
            expired_count = exec_svc.check_and_expire_stale_signals()

            logger.info(
                f"信号执行检查完成: 检查{results['checked']}条, "
                f"成交{results['executed']}条, 过期{results['expired']}条, "
                f"自动失效{expired_count}条"
            )

            return {
                "checked": results["checked"],
                "executed": results["executed"],
                "expired": results["expired"],
                "stale_cancelled": expired_count,
            }

        except Exception as e:
            logger.warning(f"信号执行检查失败: {e}")
            return {"error": str(e)}

    def _update_fund_balance(self, market_key: str, currency: str, change: float):
        """
        更新指定币种的基金余额。

        Args:
            market_key: "HKD_FUND" 或 "USD_FUND"
            currency: "HKD" 或 "USD"
            change: 变动金额（正数为增加，负数为减少）
        """
        cb = self.db.get(CashBalance, market_key)
        if cb:
            current = Decimal(str(cb.amount))
            new_amount = current + Decimal(str(change))
            # 不允许为负
            cb.amount = new_amount if new_amount > 0 else Decimal("0")
            cb.updated_at = datetime.now()
            logger.info(f"{market_key} 更新: {current:.2f} + ({change:.2f}) = {cb.amount:.2f} {currency}")
        else:
            # 首次创建（仅在卖出时，买入时设为0）
            initial = Decimal(str(change)) if change > 0 else Decimal("0")
            cb_new = CashBalance(market=market_key, currency=currency, amount=initial)
            self.db.add(cb_new)
            logger.info(f"{market_key} 初始化: {initial:.2f} {currency}")
