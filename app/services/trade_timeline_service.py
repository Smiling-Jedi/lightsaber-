"""
统一时间轴服务

将真实成交（trades 表）和模拟交易（signal_logs，is_simulated=True）
按日期合并成统一时间轴，用于个股详情页对比。
"""
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.trade import Trade
from app.models.position import Position
from app.models.signal_log import SignalLog


class TradeTimelineService:

    def __init__(self, db: Session):
        self.db = db

    def get_timeline(self, symbol: str) -> Dict:
        """
        返回统一时间轴数据。

        symbol 格式：HK:00700

        返回结构：
        {
          "rows": [
            {
              "date": "2026-02-21",
              "real": {"direction": "买入", "price": 361.2, "shares": 400, "pct": 9.7} or None,
              "sim":  {"direction": "买入", "price": 355.6, "shares": 380, "pct": 11.4} or None,
            },
            ...
          ]
        }
        按日期倒序排列。
        """
        real_trades = self._get_real_trades(symbol)
        sim_trades  = self._get_sim_trades(symbol)

        # 按日期分组（同一天可能多笔，取 id 最大的一笔，即最晚写入的）
        def group_by_date(trades: List[Dict]) -> Dict[str, dict]:
            result: Dict[str, dict] = {}
            for t in trades:
                d = t["date"]
                if not d:
                    continue
                existing = result.get(d)
                if existing is None or t.get("_id", 0) > existing.get("_id", 0):
                    result[d] = t
            return result

        all_dates: set = set()
        for t in real_trades:
            if t["date"]:
                all_dates.add(t["date"])
        for t in sim_trades:
            if t["date"]:
                all_dates.add(t["date"])

        real_by_date = group_by_date(real_trades)
        sim_by_date  = group_by_date(sim_trades)

        rows = []
        for d in sorted(all_dates, reverse=True):
            rows.append({
                "date": d,
                "real": real_by_date.get(d),
                "sim":  sim_by_date.get(d),
            })

        return {"rows": rows}

    # ─────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────

    def _get_real_trades(self, symbol: str) -> List[Dict]:
        """从 trades 表获取真实成交记录"""
        position = self.db.query(Position).filter_by(stock_symbol=symbol).first()
        if not position:
            return []

        trades = (
            self.db.query(Trade)
            .filter(Trade.position_id == position.id)
            .order_by(Trade.trade_date.desc())
            .all()
        )

        result = []
        for t in trades:
            result.append({
                "_id":       t.id,
                "date":      t.trade_date.isoformat() if t.trade_date else None,
                "direction": "买入" if t.trade_type == "BUY" else "卖出",
                "price":     float(t.price) if t.price else None,
                "shares":    t.shares,
                "pct":       None,
                "pct_label": None,
            })
        return [r for r in result if r["date"]]

    def _get_sim_trades(self, symbol: str) -> List[Dict]:
        """从 signal_logs 表获取模拟成交记录（is_simulated=True）"""
        logs = (
            self.db.query(SignalLog)
            .filter(
                SignalLog.symbol == symbol,
                SignalLog.is_simulated == True,
                SignalLog.action.in_(["BUY", "SELL"]),
                SignalLog.entered == True,
                SignalLog.status.in_(["PENDING", "HIT_TARGET", "HIT_STOP", "EXPIRED"]),
            )
            .order_by(SignalLog.generated_at.desc())
            .all()
        )

        result = []
        for log in logs:
            trade_date = log.entered_at.date().isoformat() if log.entered_at else (
                log.generated_at.date().isoformat() if log.generated_at else None
            )
            price = log.entered_price or log.entry_price

            # pct 恒为数值或 None，用 pct_label 单独承载"持有中"文本
            pct = log.actual_pct if log.actual_pct is not None else None
            pct_label = "持有中" if log.status == "PENDING" and log.entered else None

            result.append({
                "_id":       log.id,
                "date":      trade_date,
                "direction": "买入" if log.action == "BUY" else "卖出",
                "price":     price,
                "shares":    log.recommended_shares,  # 使用建议买入股数（第一批）
                "pct":       pct,
                "pct_label": pct_label,
            })

        return [r for r in result if r["date"]]
