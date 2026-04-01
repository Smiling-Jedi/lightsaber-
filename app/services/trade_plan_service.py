"""
交易计划服务
"""
from decimal import Decimal
from typing import Optional, List, Dict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.trade_plan import TradePlan
from app.models.trade import Trade
from app.models.position import Position
from app.models.stock import Stock
from app.models.cash import CashBalance
from app.services.indicator_service import IndicatorService
from app.services.position_service import PositionService



class TradePlanService:
    """交易计划业务服务"""

    # 止损方式配置
    STOP_LOSS_METHODS = {
        "不止损,长期持有": {"param_label": "无", "param_type": "none", "default": 0},
        "固定比例": {"param_label": "%", "param_type": "percent", "default": 7.0},
        "ATR倍数": {"param_label": "倍", "param_type": "atr", "default": 2.0},
        "支撑位": {"param_label": "价格", "param_type": "price", "default": None},
        "移动平均线": {"param_label": "天数", "param_type": "ma", "default": 20},
    }

    # 策略默认配置
    STRATEGY_DEFAULTS = {
        "底仓": {"stop_loss_method": "固定比例", "stop_loss_param": 20.0},
        "波段": {"stop_loss_method": "ATR倍数", "stop_loss_param": 2.0},
    }

    def __init__(self, db: Session):
        self.db = db
        self.indicator_svc = IndicatorService()
        self.position_svc = PositionService(db)

    def get_plan(self, plan_id: int) -> Optional[TradePlan]:
        """获取单个计划"""
        return self.db.query(TradePlan).filter(TradePlan.id == plan_id).first()

    def list_plans(self, limit: int = 100, offset: int = 0) -> List[TradePlan]:
        """获取计划列表"""
        return (
            self.db.query(TradePlan)
            .order_by(TradePlan.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_plan_by_trade(self, trade_id: int) -> Optional[TradePlan]:
        """通过交易ID获取计划"""
        return self.db.query(TradePlan).filter(TradePlan.trade_id == trade_id).first()

    def create_plan(self, data: dict) -> TradePlan:
        """创建新计划"""
        # 参数验证
        planned_price = Decimal(str(data["planned_price"]))
        target_price = Decimal(str(data["target_price"]))

        # 检查目标价是否高于买入价
        if target_price <= planned_price:
            raise ValueError(f"目标价({float(target_price)})必须高于买入价({float(planned_price)})")

        # 计算止损价
        stop_result = self._calculate_stop_loss_price(
            symbol=data["symbol"],
            planned_price=planned_price,
            method=data["stop_loss_method"],
            param=Decimal(str(data["stop_loss_param"])),
        )
        stop_loss_price = stop_result["stop_loss_price"]

        # 检查止损价是否高于买入价（除"不止损"外）
        if data["stop_loss_method"] != "不止损,长期持有" and stop_loss_price >= planned_price:
            detail_msg = ""
            if stop_result.get("calculation_detail"):
                detail = stop_result["calculation_detail"]
                detail_msg = f" [{detail.get('method')}]"
            raise ValueError(f"止损价({float(stop_loss_price)}){detail_msg}必须低于买入价({float(planned_price)})")

        # 计算风险指标
        planned_price = Decimal(str(data["planned_price"]))
        planned_shares = int(data["planned_shares"])
        risk_amount = (planned_price - stop_loss_price) * planned_shares

        target_price = Decimal(str(data["target_price"]))
        profit = target_price - planned_price
        loss = planned_price - stop_loss_price
        risk_reward_ratio = round(profit / loss, 2) if loss > 0 else Decimal("0")

        plan = TradePlan(
            symbol=data["symbol"],
            market=self._extract_market(data["symbol"]),
            strategy_type=data["strategy_type"],
            planned_shares=planned_shares,
            planned_price=planned_price,
            target_price=target_price,
            stop_loss_method=data["stop_loss_method"],
            stop_loss_param=Decimal(str(data["stop_loss_param"])),
            stop_loss_price=stop_loss_price,
            risk_amount=risk_amount,
            risk_reward_ratio=risk_reward_ratio,
            buy_reason=data["buy_reason"],
            note=data.get("note"),
            trade_id=data.get("trade_id"),
            status="计划中",
            created_at=datetime.now(),
        )

        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def update_plan(self, plan_id: int, data: dict) -> Optional[TradePlan]:
        """更新计划（仅计划中状态）"""
        plan = self.get_plan(plan_id)
        if not plan or plan.status != "计划中":
            return None

        # 获取更新后的价格
        planned_price = Decimal(str(data.get("planned_price", plan.planned_price)))
        target_price = Decimal(str(data.get("target_price", plan.target_price)))

        # 检查目标价是否高于买入价
        if target_price <= planned_price:
            raise ValueError(f"目标价({float(target_price)})必须高于买入价({float(planned_price)})")

        # 如果修改了关键字段，重新计算
        need_recalculate = any(k in data for k in [
            "planned_price", "target_price", "planned_shares",
            "stop_loss_method", "stop_loss_param"
        ])

        if need_recalculate:
            stop_loss_method = data.get("stop_loss_method", plan.stop_loss_method)
            stop_result = self._calculate_stop_loss_price(
                symbol=data.get("symbol", plan.symbol),
                planned_price=planned_price,
                method=stop_loss_method,
                param=Decimal(str(data.get("stop_loss_param", plan.stop_loss_param))),
            )
            stop_loss_price = stop_result["stop_loss_price"]

            # 检查止损价是否高于买入价（除"不止损"外）
            if stop_loss_method != "不止损,长期持有" and stop_loss_price >= planned_price:
                raise ValueError(f"止损价({float(stop_loss_price)})必须低于买入价({float(planned_price)})")

            planned_shares = int(data.get("planned_shares", plan.planned_shares))
            risk_amount = (planned_price - stop_loss_price) * planned_shares

            profit = target_price - planned_price
            loss = planned_price - stop_loss_price
            risk_reward_ratio = round(profit / loss, 2) if loss > 0 else Decimal("0")

            plan.stop_loss_price = stop_loss_price
            plan.risk_amount = risk_amount
            plan.risk_reward_ratio = risk_reward_ratio

        # 更新其他字段
        for key in ["symbol", "strategy_type", "planned_shares", "planned_price",
                    "target_price", "stop_loss_method", "stop_loss_param",
                    "buy_reason", "note"]:
            if key in data:
                setattr(plan, key, data[key])

        self.db.commit()
        self.db.refresh(plan)
        return plan

    def delete_plan(self, plan_id: int) -> bool:
        """删除计划（仅计划中状态）"""
        plan = self.get_plan(plan_id)
        if not plan or plan.status != "计划中":
            return False

        self.db.delete(plan)
        self.db.commit()
        return True

    def mark_executed(self, plan_id: int, trade_id: int) -> Optional[TradePlan]:
        """标记计划已执行"""
        plan = self.get_plan(plan_id)
        if not plan:
            return None

        plan.trade_id = trade_id
        plan.status = "已执行"
        plan.executed_at = datetime.now()

        self.db.commit()
        self.db.refresh(plan)
        return plan

    def add_review(self, plan_id: int, data: dict) -> Optional[TradePlan]:
        """添加复盘"""
        plan = self.get_plan(plan_id)
        if not plan or plan.status != "已执行":
            return None

        plan.review_result = data.get("review_result")
        plan.review_note = data.get("review_note")
        plan.planned_vs_actual = data.get("planned_vs_actual")
        plan.lesson_learned = data.get("lesson_learned")
        plan.reviewed_at = datetime.now()
        plan.status = "已复盘"

        self.db.commit()
        self.db.refresh(plan)
        return plan

    def evaluate_plan(self, data: dict) -> Dict:
        """评估交易计划（不保存到数据库）"""
        # 计算基础指标
        planned_price = Decimal(str(data["planned_price"]))
        target_price = Decimal(str(data["target_price"]))
        planned_shares = int(data["planned_shares"])

        stop_result = self._calculate_stop_loss_price(
            symbol=data["symbol"],
            planned_price=planned_price,
            method=data["stop_loss_method"],
            param=Decimal(str(data["stop_loss_param"])),
        )
        stop_loss_price = stop_result["stop_loss_price"]
        calc_detail = stop_result.get("calculation_detail")

        # 检查止损价是否高于买入价（除"不止损"外）
        if data["stop_loss_method"] != "不止损,长期持有" and stop_loss_price >= planned_price:
            error_result = {
                "error": "止损配置错误",
                "message": f"止损价({float(stop_loss_price)})高于或等于买入价({float(planned_price)})，请检查止损设置",
                "plan": {
                    "symbol": data["symbol"],
                    "stop_loss_price": float(stop_loss_price),
                    "risk_amount": 0,
                    "risk_reward_ratio": 0,
                    "position_pct": 0,
                },
                "evaluation": {
                    "overall": "配置错误",
                    "overall_code": "red",
                    "checks": [
                        {
                            "item": "止损设置",
                            "status": "fail",
                            "message": f"止损价({float(stop_loss_price)})高于或等于买入价({float(planned_price)})"
                        }
                    ],
                    "suggestions": ["请重新设置止损价，确保低于买入价"],
                }
            }
            # 添加计算详情（帮助用户理解错误原因）
            if calc_detail:
                error_result["calculation_detail"] = calc_detail
            return error_result

        risk_amount = (planned_price - stop_loss_price) * planned_shares
        profit = target_price - planned_price
        loss = planned_price - stop_loss_price
        risk_reward_ratio = round(profit / loss, 2) if loss > 0 else Decimal("0")

        # 获取上下文数据
        portfolio = self.position_svc.get_portfolio_summary()

        # 从symbol提取市场
        market = data["symbol"].split(":")[0] if ":" in data["symbol"] else "A"
        # 标准化市场代码
        market_map = {"A": "A", "HK": "HK", "US": "US", "SH": "A", "SZ": "A"}
        market = market_map.get(market, market)

        # 获取该市场的总资金（含现金）
        markets_data = portfolio.get("markets", {})
        market_data = markets_data.get(market, {})
        market_total = Decimal(str(market_data.get("total_with_cash", 0)))
        # 如果市场数据为空，使用总资产作为fallback
        total_assets = market_total if market_total > 0 else Decimal(str(portfolio.get("total_market_value_rmb", 0)))

        position = self.position_svc.get_position_by_symbol(data["symbol"])
        current_shares = position.total_shares if position else 0

        # 计算持仓后占比（基于该市场总资金）
        stock = self.db.query(Stock).filter(Stock.symbol == data["symbol"]).first()
        current_price = Decimal(str(stock.current_price)) if stock and stock.current_price else planned_price
        total_shares_after = current_shares + planned_shares
        position_value = total_shares_after * current_price
        position_pct = (position_value / total_assets * 100) if total_assets > 0 else Decimal("0")

        # 执行评估检查
        checks = []
        suggestions = []


        # 1. 仓位红线检查
        position_check = self._check_position_limits(data["symbol"], position_pct, portfolio)
        checks.append(position_check)

        # 2. 风险金额检查
        risk_check = self._check_risk_amount(risk_amount, total_assets)
        checks.append(risk_check)

        # 3. 盈亏比检查
        rr_check = self._check_risk_reward(risk_reward_ratio)
        checks.append(rr_check)
        if rr_check["status"] == "warning":
            suggestions.append("盈亏比一般，需确保胜率足够高")

        # 5. 策略匹配检查
        strategy_check = self._check_strategy_match(data)
        checks.append(strategy_check)

        # 综合结论
        has_fail = any(c["status"] == "fail" for c in checks)
        has_warning = any(c["status"] == "warning" for c in checks)

        if has_fail:
            overall = "不建议"
            overall_code = "red"
        elif has_warning:
            overall = "谨慎执行"
            overall_code = "yellow"
        else:
            overall = "建议执行"
            overall_code = "green"

        result = {
            "plan": {
                "symbol": data["symbol"],
                "stop_loss_price": float(stop_loss_price),
                "risk_amount": float(risk_amount),
                "risk_reward_ratio": float(risk_reward_ratio),
                "position_pct": float(position_pct),
            },
            "evaluation": {
                "overall": overall,
                "overall_code": overall_code,
                "checks": checks,
                "suggestions": suggestions,
            }
        }

        # 添加计算详情（如果存在）
        if calc_detail:
            result["calculation_detail"] = calc_detail

        return result

    def _extract_market(self, symbol: str) -> str:
        """从symbol提取市场"""
        return symbol.split(":")[0] if ":" in symbol else "A"

    def _calculate_stop_loss_price(self, symbol: str, planned_price: Decimal,
                                    method: str, param: Decimal) -> dict:
        """计算止损价，返回包含价格和计算详情的字典"""
        result = {
            "stop_loss_price": Decimal("0"),
            "calculation_detail": None
        }

        if method == "不止损,长期持有":
            # 不设止损，返回0表示无止损
            result["stop_loss_price"] = Decimal("0")
            return result

        if method == "固定比例":
            stop_price = planned_price * (1 - param / 100)
            result["stop_loss_price"] = stop_price
            result["calculation_detail"] = {
                "method": "固定比例",
                "param": float(param),
                "formula": f"{float(planned_price)} × (1 - {float(param)}%) = {float(stop_price):.3f}"
            }
            return result

        elif method == "ATR倍数":
            # 获取真实ATR14数据
            atr_data = self._get_atr_data(symbol)
            if atr_data and atr_data.get("atr14"):
                atr14 = Decimal(str(atr_data["atr14"]))
                multiplier = Decimal(str(param))
                stop_price = planned_price - atr14 * multiplier
                result["stop_loss_price"] = stop_price
                result["calculation_detail"] = {
                    "method": "ATR倍数",
                    "atr14": float(atr14),
                    "multiplier": float(multiplier),
                    "planned_price": float(planned_price),
                    "formula": f"{float(planned_price)} - {float(atr14):.4f} × {float(multiplier)} = {float(stop_price):.3f}",
                    "data_date": atr_data.get("date"),
                    "note": f"基于最近14日ATR({float(atr14):.4f})计算"
                }
            else:
                # 无法获取ATR时，使用固定比例7%作为fallback
                stop_price = planned_price * Decimal("0.93")
                result["stop_loss_price"] = stop_price
                result["calculation_detail"] = {
                    "method": "ATR倍数",
                    "atr14": None,
                    "multiplier": float(param),
                    "planned_price": float(planned_price),
                    "formula": f"{float(planned_price)} × 0.93 = {float(stop_price):.3f} (ATR数据不可用，使用默认7%)",
                    "note": "无法获取ATR数据，使用默认7%跌幅"
                }
            return result

        elif method == "支撑位":
            stop_price = param
            result["stop_loss_price"] = stop_price
            result["calculation_detail"] = {
                "method": "支撑位",
                "support_price": float(param),
                "formula": f"支撑位 = {float(param)}"
            }
            return result

        elif method == "移动平均线":
            # 获取MA数据
            ma_data = self._get_ma_data(symbol, int(param))
            if ma_data and ma_data.get("ma_value"):
                ma_value = Decimal(str(ma_data["ma_value"]))
                stop_price = ma_value
                result["stop_loss_price"] = stop_price
                result["calculation_detail"] = {
                    "method": "移动平均线",
                    "ma_period": int(param),
                    "ma_value": float(ma_value),
                    "formula": f"MA{int(param)} = {float(ma_value):.3f}",
                    "data_date": ma_data.get("date")
                }
            else:
                # 无法获取MA时，使用固定比例7%作为fallback
                stop_price = planned_price * Decimal("0.93")
                result["stop_loss_price"] = stop_price
                result["calculation_detail"] = {
                    "method": "移动平均线",
                    "ma_period": int(param),
                    "ma_value": None,
                    "formula": f"{float(planned_price)} × 0.93 = {float(stop_price):.3f} (MA数据不可用，使用默认7%)",
                    "note": "无法获取MA数据，使用默认7%跌幅"
                }
            return result

        # 默认fallback
        stop_price = planned_price * Decimal("0.93")
        result["stop_loss_price"] = stop_price
        return result

    def _get_atr_data(self, symbol: str) -> Optional[dict]:
        """获取ATR14数据"""
        """获取ATR14数据"""
        try:
            from app.services.futu_kline_service import FutuKlineService
            import pandas as pd

            kline_service = FutuKlineService()
            rows = kline_service.get_kline(symbol, count=100)

            if not rows or len(rows) < 30:
                return None

            # 转换为DataFrame
            df = pd.DataFrame(rows)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')

            # 计算ATR14
            indicator_svc = IndicatorService()
            df["atr14"] = indicator_svc._atr(df, 14)

            # 获取最新数据
            latest = df.iloc[-1]
            latest_date = df.index[-1].strftime("%Y-%m-%d")

            if pd.notna(latest["atr14"]):
                return {
                    "atr14": round(float(latest["atr14"]), 4),
                    "date": latest_date
                }
            return None
        except Exception as e:
            logger.warning(f"获取ATR数据失败 {symbol}: {e}")
            return None

    def _get_ma_data(self, symbol: str, period: int) -> Optional[dict]:
        """获取MA数据"""
        try:
            from app.services.futu_kline_service import FutuKlineService

            kline_service = FutuKlineService()
            rows = kline_service.get_kline(symbol, count=250)

            if not rows or len(rows) < period:
                return None

            # 计算MA
            closes = [r["close"] for r in rows]
            ma_values = []
            for i in range(len(closes)):
                if i < period - 1:
                    ma_values.append(None)
                else:
                    ma_values.append(sum(closes[i - period + 1: i + 1]) / period)

            # 获取最新MA值
            latest_ma = None
            for i in range(len(ma_values) - 1, -1, -1):
                if ma_values[i] is not None:
                    latest_ma = ma_values[i]
                    break

            if latest_ma:
                return {
                    "ma_value": round(latest_ma, 4),
                    "date": rows[-1]["date"]
                }
            return None
        except Exception as e:
            logger.warning(f"获取MA数据失败 {symbol}: {e}")
            return None

    def _check_reserve(self, data: dict, risk_amount: Decimal) -> Dict:
        """储备金检查"""
        # 获取当前现金
        cash_balances = self.db.query(CashBalance).all()
        total_cash = sum(Decimal(str(cb.amount)) for cb in cash_balances)

        # 储备金缺口60万
        RESERVE_TARGET = Decimal("3000000")
        reserve_gap = RESERVE_TARGET - total_cash

        if reserve_gap > 0:
            return {
                "item": "储备金检查",
                "status": "fail",
                "message": f"储备金缺口{float(reserve_gap)/10000:.0f}万，当前现金{float(total_cash)/10000:.0f}万"
            }

        return {
            "item": "储备金检查",
            "status": "pass",
            "message": "储备金充足"
        }

    def _check_position_limits(self, symbol: str, position_pct: Decimal, portfolio: dict) -> Dict:
        """仓位红线检查"""
        messages = []
        status = "pass"

        # 单票集中度
        if position_pct > 25:
            status = "fail"
            messages.append(f"单票占比{float(position_pct):.1f}%超过25%红线")
        elif position_pct > 20:
            status = "warning"
            messages.append(f"单票占比{float(position_pct):.1f}%接近上限")

        if not messages:
            messages.append(f"买入后占比{float(position_pct):.1f}%，未超红线")

        return {
            "item": "仓位红线",
            "status": status,
            "message": "；".join(messages)
        }

    def _check_risk_amount(self, risk_amount: Decimal, total_assets: Decimal) -> Dict:
        """风险金额检查"""
        if total_assets <= 0:
            return {
                "item": "风险金额",
                "status": "warning",
                "message": "无法获取总资产数据"
            }

        risk_pct = risk_amount / total_assets * 100

        if risk_pct > 1:
            return {
                "item": "风险金额",
                "status": "warning",
                "message": f"单笔风险{float(risk_pct):.2f}%，建议<1%"
            }

        return {
            "item": "风险金额",
            "status": "pass",
            "message": f"单笔风险{float(risk_pct):.2f}%，可控"
        }

    def _check_risk_reward(self, rr_ratio: Decimal) -> Dict:
        """盈亏比检查"""
        if rr_ratio < 1:
            return {
                "item": "盈亏比",
                "status": "fail",
                "message": f"1:{float(rr_ratio):.1f}，风险大于收益，不建议"
            }
        elif rr_ratio < 2:
            return {
                "item": "盈亏比",
                "status": "warning",
                "message": f"1:{float(rr_ratio):.1f}，一般，需确保胜率>50%"
            }
        else:
            return {
                "item": "盈亏比",
                "status": "pass",
                "message": f"1:{float(rr_ratio):.1f}，良好"
            }

    def _check_strategy_match(self, data: dict) -> Dict:
        """策略匹配检查"""
        strategy = data.get("strategy_type")
        buy_reason = data.get("buy_reason", "")

        if strategy == "底仓":
            keywords = ["业绩", "护城河", "竞争力", "行业地位", "现金流", "ROE"]
            has_fundamental = any(kw in buy_reason for kw in keywords)

            if not has_fundamental:
                return {
                    "item": "策略匹配",
                    "status": "warning",
                    "message": "底仓建议补充基本面逻辑（业绩/护城河等）"
                }

        elif strategy == "波段":
            keywords = ["RSI", "MACD", "均线", "突破", "支撑", "超卖", "金叉"]
            has_technical = any(kw in buy_reason for kw in keywords)

            if not has_technical:
                return {
                    "item": "策略匹配",
                    "status": "warning",
                    "message": "波段建议补充技术面信号（RSI/MACD等）"
                }

        return {
            "item": "策略匹配",
            "status": "pass",
            "message": "策略匹配良好"
        }
