"""
演示模式 Fixture 数据
使用真实股票代码，但仓位/价格/盈亏全部为模拟值
港股 5 只 / 美股 5 只，总资金各约 10 万
"""
import math
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

# 汇率常量
HKD_RATE = 0.91
USD_RATE = 7.26

# ─── 港股持仓 ────────────────────────────────────────────────

_HK_POSITIONS = [
    {
        "symbol": "HK:00700", "name": "腾讯控股", "market": "HK", "currency": "HKD",
        "total_shares": 50, "base_shares": 0, "swing_shares": 50,
        "avg_cost": 478.0, "base_cost": 478.0, "swing_cost": 478.0,
        "current_price": 508.0, "market_value": 25400.0,
        "profit": 1500.0, "profit_pct": 6.3, "position_weight": 24.7,
        "price_change_pct": 1.2,
        "advice": {"action": "HOLD", "reason": "盈利适中(+6.3%)，建议持有观望"},
        "monitor_targets": [{"label": "目标价1", "price": 525.8, "reached": False}],
        "support_price": 454.1, "resistance_price": 549.7,
        "latest_news": "腾讯Q4财报超预期，广告收入同比+23%",
        "latest_news_url": "#", "latest_news_source": "Bloomberg",
        "today_profit_amount": 300.0,
        # RMB 转换字段
        "profit_rmb": 1500.0 * HKD_RATE,
        "market_value_rmb": 25400.0 * HKD_RATE,
        "today_profit_rmb": 300.0 * HKD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "HK:09988", "name": "阿里巴巴-W", "market": "HK", "currency": "HKD",
        "total_shares": 200, "base_shares": 0, "swing_shares": 200,
        "avg_cost": 133.0, "base_cost": 133.0, "swing_cost": 133.0,
        "current_price": 123.0, "market_value": 24600.0,
        "profit": -2000.0, "profit_pct": -7.5, "position_weight": 23.9,
        "price_change_pct": -0.8,
        "advice": {"action": "HOLD", "reason": "回调明显(-7.5%)，关注加仓机会"},
        "monitor_targets": [{"label": "目标价1", "price": 146.3, "reached": False}],
        "support_price": 126.35, "resistance_price": 152.95,
        "latest_news": "阿里云AI业务增速超预期，季度收入突破300亿",
        "latest_news_url": "#", "latest_news_source": "Reuters",
        "today_profit_amount": -160.0,
        # RMB 转换字段
        "profit_rmb": -2000.0 * HKD_RATE,
        "market_value_rmb": 24600.0 * HKD_RATE,
        "today_profit_rmb": -160.0 * HKD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "HK:01810", "name": "小米集团-W", "market": "HK", "currency": "HKD",
        "total_shares": 500, "base_shares": 0, "swing_shares": 500,
        "avg_cost": 38.0, "base_cost": 38.0, "swing_cost": 38.0,
        "current_price": 42.5, "market_value": 21250.0,
        "profit": 2250.0, "profit_pct": 11.8, "position_weight": 20.6,
        "price_change_pct": 2.1,
        "advice": {"action": "HOLD", "reason": "盈利可观(+11.8%)，继续持有"},
        "monitor_targets": [{"label": "目标价1", "price": 41.8, "reached": True}],
        "support_price": 36.1, "resistance_price": 43.7,
        "latest_news": "小米汽车SU7 Pro发布，预订量突破10万台",
        "latest_news_url": "#", "latest_news_source": "36氪",
        "today_profit_amount": 425.0,
        # RMB 转换字段
        "profit_rmb": 2250.0 * HKD_RATE,
        "market_value_rmb": 21250.0 * HKD_RATE,
        "today_profit_rmb": 425.0 * HKD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "HK:03690", "name": "美团-W", "market": "HK", "currency": "HKD",
        "total_shares": 100, "base_shares": 0, "swing_shares": 100,
        "avg_cost": 198.0, "base_cost": 198.0, "swing_cost": 198.0,
        "current_price": 185.0, "market_value": 18500.0,
        "profit": -1300.0, "profit_pct": -6.6, "position_weight": 18.0,
        "price_change_pct": -1.1,
        "advice": {"action": "HOLD", "reason": "回调(-6.6%)，观望为主"},
        "monitor_targets": [{"label": "目标价1", "price": 217.8, "reached": False}],
        "support_price": 188.1, "resistance_price": 227.7,
        "latest_news": "美团闪购业务Q4 GMV同比增长55%",
        "latest_news_url": "#", "latest_news_source": "财联社",
        "today_profit_amount": -185.0,
        # RMB 转换字段
        "profit_rmb": -1300.0 * HKD_RATE,
        "market_value_rmb": 18500.0 * HKD_RATE,
        "today_profit_rmb": -185.0 * HKD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "HK:06160", "name": "百济神州", "market": "HK", "currency": "HKD",
        "total_shares": 60, "base_shares": 0, "swing_shares": 60,
        "avg_cost": 178.0, "base_cost": 178.0, "swing_cost": 178.0,
        "current_price": 169.0, "market_value": 10140.0,
        "profit": -540.0, "profit_pct": -5.1, "position_weight": 9.8,
        "price_change_pct": -0.6,
        "advice": {"action": "HOLD", "reason": "波动不大(-5.1%)，建议持有观望"},
        "monitor_targets": [{"label": "目标价1", "price": 195.8, "reached": False}],
        "support_price": 169.1, "resistance_price": 204.7,
        "latest_news": "百济神州BTK抑制剂获FDA突破性疗法认定",
        "latest_news_url": "#", "latest_news_source": "医药经济报",
        "today_profit_amount": -60.0,
        # RMB 转换字段
        "profit_rmb": -540.0 * HKD_RATE,
        "market_value_rmb": 10140.0 * HKD_RATE,
        "today_profit_rmb": -60.0 * HKD_RATE,
        "currency_display": "CNY",
    },
]

# ─── 美股持仓 ────────────────────────────────────────────────

_US_POSITIONS = [
    {
        "symbol": "US:META", "name": "Meta Platforms", "market": "US", "currency": "USD",
        "total_shares": 40, "base_shares": 0, "swing_shares": 40,
        "avg_cost": 542.0, "base_cost": 542.0, "swing_cost": 542.0,
        "current_price": 596.0, "market_value": 23840.0,
        "profit": 2160.0, "profit_pct": 9.9, "position_weight": 27.0,
        "price_change_pct": 1.8,
        "advice": {"action": "HOLD", "reason": "盈利良好(+9.9%)，趋势向上"},
        "monitor_targets": [{"label": "目标价1", "price": 595.2, "reached": True}],
        "support_price": 514.9, "resistance_price": 623.3,
        "latest_news": "Meta AI推出新一代Llama模型，开发者社区增长加速",
        "latest_news_url": "#", "latest_news_source": "WSJ",
        "today_profit_amount": 428.0,
        # RMB 转换字段
        "profit_rmb": 2160.0 * USD_RATE,
        "market_value_rmb": 23840.0 * USD_RATE,
        "today_profit_rmb": 428.0 * USD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "US:MSFT", "name": "Microsoft", "market": "US", "currency": "USD",
        "total_shares": 50, "base_shares": 0, "swing_shares": 50,
        "avg_cost": 398.0, "base_cost": 398.0, "swing_cost": 398.0,
        "current_price": 420.0, "market_value": 21000.0,
        "profit": 1100.0, "profit_pct": 5.5, "position_weight": 23.8,
        "price_change_pct": 0.7,
        "advice": {"action": "HOLD", "reason": "盈利适中(+5.5%)，建议持有"},
        "monitor_targets": [{"label": "目标价1", "price": 437.8, "reached": False}],
        "support_price": 378.1, "resistance_price": 457.7,
        "latest_news": "微软Azure AI服务季度营收突破200亿美元",
        "latest_news_url": "#", "latest_news_source": "CNBC",
        "today_profit_amount": 147.0,
        # RMB 转换字段
        "profit_rmb": 1100.0 * USD_RATE,
        "market_value_rmb": 21000.0 * USD_RATE,
        "today_profit_rmb": 147.0 * USD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "US:TSLA", "name": "Tesla", "market": "US", "currency": "USD",
        "total_shares": 60, "base_shares": 0, "swing_shares": 60,
        "avg_cost": 298.0, "base_cost": 298.0, "swing_cost": 298.0,
        "current_price": 265.0, "market_value": 15900.0,
        "profit": -1980.0, "profit_pct": -11.1, "position_weight": 18.0,
        "price_change_pct": -2.3,
        "advice": {"action": "HOLD", "reason": "跌幅较大(-11.1%)，可关注加仓机会"},
        "monitor_targets": [{"label": "目标价1", "price": 327.8, "reached": False}],
        "support_price": 283.1, "resistance_price": 342.7,
        "latest_news": "特斯拉Model Y改款在华交付，首月订单超5万台",
        "latest_news_url": "#", "latest_news_source": "Reuters",
        "today_profit_amount": -318.0,
        # RMB 转换字段
        "profit_rmb": -1980.0 * USD_RATE,
        "market_value_rmb": 15900.0 * USD_RATE,
        "today_profit_rmb": -318.0 * USD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "US:AMZN", "name": "Amazon", "market": "US", "currency": "USD",
        "total_shares": 50, "base_shares": 0, "swing_shares": 50,
        "avg_cost": 218.0, "base_cost": 218.0, "swing_cost": 218.0,
        "current_price": 233.0, "market_value": 11650.0,
        "profit": 750.0, "profit_pct": 6.9, "position_weight": 13.2,
        "price_change_pct": 1.1,
        "advice": {"action": "HOLD", "reason": "盈利适中(+6.9%)，云业务持续强劲"},
        "monitor_targets": [{"label": "目标价1", "price": 239.8, "reached": False}],
        "support_price": 207.1, "resistance_price": 250.7,
        "latest_news": "亚马逊AWS季度营收同比增长17%，超市场预期",
        "latest_news_url": "#", "latest_news_source": "Bloomberg",
        "today_profit_amount": 115.0,
        # RMB 转换字段
        "profit_rmb": 750.0 * USD_RATE,
        "market_value_rmb": 11650.0 * USD_RATE,
        "today_profit_rmb": 115.0 * USD_RATE,
        "currency_display": "CNY",
    },
    {
        "symbol": "US:NVDA", "name": "NVIDIA", "market": "US", "currency": "USD",
        "total_shares": 80, "base_shares": 0, "swing_shares": 80,
        "avg_cost": 128.0, "base_cost": 128.0, "swing_cost": 128.0,
        "current_price": 108.0, "market_value": 8640.0,
        "profit": -1600.0, "profit_pct": -15.6, "position_weight": 9.8,
        "price_change_pct": -3.1,
        "advice": {"action": "HOLD", "reason": "跌幅大(-15.6%)，等待企稳信号"},
        "monitor_targets": [{"label": "目标价1", "price": 140.8, "reached": False}],
        "support_price": 121.6, "resistance_price": 147.2,
        "latest_news": "英伟达Blackwell GPU出货量超预期，数据中心需求强劲",
        "latest_news_url": "#", "latest_news_source": "Insider Monkey",
        "today_profit_amount": -248.0,
        # RMB 转换字段
        "profit_rmb": -1600.0 * USD_RATE,
        "market_value_rmb": 8640.0 * USD_RATE,
        "today_profit_rmb": -248.0 * USD_RATE,
        "currency_display": "CNY",
    },
]

# ─── 组合汇总 ─────────────────────────────────────────────────

def get_demo_portfolio() -> dict:
    hk_mv = sum(p["market_value"] for p in _HK_POSITIONS)
    hk_cost = sum(p["avg_cost"] * p["total_shares"] for p in _HK_POSITIONS)
    hk_cash = 3110.0
    hk_total = hk_mv + hk_cash

    us_mv = sum(p["market_value"] for p in _US_POSITIONS)
    us_cost = sum(p["avg_cost"] * p["total_shares"] for p in _US_POSITIONS)
    us_cash = 8970.0
    us_total = us_mv + us_cash

    hkd_rate, usd_rate = HKD_RATE, USD_RATE

    hk_rmb = hk_total * hkd_rate
    us_rmb = us_total * usd_rate
    total_rmb = hk_rmb + us_rmb

    hk_profit = hk_mv - hk_cost
    us_profit = us_mv - us_cost
    total_profit_rmb = hk_profit * hkd_rate + us_profit * usd_rate
    total_cost_rmb = hk_cost * hkd_rate + us_cost * usd_rate

    hk_today = sum(p["today_profit_amount"] for p in _HK_POSITIONS)
    us_today = sum(p["today_profit_amount"] for p in _US_POSITIONS)
    today_rmb = hk_today * hkd_rate + us_today * usd_rate

    # 重新算权重（基数只用股票市值，不含现金，和真实持仓页语义一致）
    hk_positions = [{**p, "position_weight": round(p["market_value"] / hk_mv * 100, 1) if hk_mv else 0} for p in _HK_POSITIONS]
    us_positions = [{**p, "position_weight": round(p["market_value"] / us_mv * 100, 1) if us_mv else 0} for p in _US_POSITIONS]

    return {
        "markets": {
            "HK": {
                "positions": hk_positions,
                "total_market_value": round(hk_mv, 2),
                "total_cost": round(hk_cost, 2),
                "cash": hk_cash,
                "fund_hkd": 0.0,
                "fund_usd": 0.0,
                "total_with_cash": round(hk_total, 2),
                "weight_pct": round(hk_rmb / total_rmb * 100, 1),
                "profit_pct": round((hk_mv - hk_cost) / hk_cost * 100, 2),
                "currency": "HKD",
                "cash_position": {
                    "is_cash": True, "market": "HK", "currency": "HKD",
                    "amount": hk_cash,
                    "position_weight": round(hk_cash / hk_total * 100, 1),
                },
            },
            "US": {
                "positions": us_positions,
                "total_market_value": round(us_mv, 2),
                "total_cost": round(us_cost, 2),
                "cash": us_cash,
                "fund_hkd": 0.0,
                "fund_usd": 0.0,
                "total_with_cash": round(us_total, 2),
                "weight_pct": round(us_rmb / total_rmb * 100, 1),
                "profit_pct": round((us_mv - us_cost) / us_cost * 100, 2),
                "currency": "USD",
                "cash_position": {
                    "is_cash": True, "market": "US", "currency": "USD",
                    "amount": us_cash,
                    "position_weight": round(us_cash / us_total * 100, 1),
                },
            },
        },
        "total_positions": len(hk_positions) + len(us_positions),
        "total_market_value": round(hk_mv + us_mv, 2),
        "total_market_value_rmb": round(total_rmb, 2),
        "total_cost": round(hk_cost + us_cost, 2),
        "total_profit": round(total_profit_rmb, 2),
        "total_profit_pct": round(total_profit_rmb / total_cost_rmb * 100, 2),
        "today_profit": round(today_rmb, 2),
        "fund_assets_hkd": 0.0,
        "today_profit_pct": round(today_rmb / total_rmb * 100, 3),
    }


# ─── 单只持仓查询 ────────────────────────────────────────────────

_ALL_POSITIONS = _HK_POSITIONS + _US_POSITIONS
_POS_BY_SYMBOL = {p["symbol"]: p for p in _ALL_POSITIONS}


def get_demo_position(symbol: str) -> Optional[dict]:
    """按 symbol 获取演示持仓（如 HK:00700）"""
    return _POS_BY_SYMBOL.get(symbol)


# ─── 信号 Fixture ─────────────────────────────────────────────

def get_demo_signals() -> dict:
    signals = [
        # 腾讯 - RSI接近超卖，HOLD medium（市场偏弱降级）
        {
            "symbol": "HK:00700", "name": "腾讯控股", "category": "large_tech",
            "generated_at": _today(),
            "action": "HOLD", "confidence": "MEDIUM",
            "summary": "EMA金叉持续，但ADX偏弱，市场环境偏弱，维持持有",
            "triggers": ["EMA20 > EMA60 金叉持续中"],
            "conflicts": ["ADX=18.2 低于25，趋势偏弱"],
            "indicators": {"ema20": 502.3, "ema60": 488.7, "adx14": 18.2, "rsi14": 47.3,
                           "macd_hist": 3.1, "bb_lower": 478.2, "bb_upper": 538.4,
                           "bb_mid": 508.3, "atr14": 12.8, "close": 508.0},
            "market_env": "BEAR", "market_env_note": "市场偏弱，信心从HIGH降至MEDIUM",
            "position": {"base_shares": 0, "swing_shares": 50, "base_pct": 0.0,
                         "swing_pct": 24.7, "total_pct": 24.7, "kelly_limit_pct": 30.0,
                         "available_swing_pct": 5.3},
            "stop_loss_pct": -7.5, "target_pct_1": 15.0,
            "backtest_ref": {"win_rate": 0.62, "ev_pct": 8.3, "kelly_pct": 18,
                             "credibility": "HIGH", "sample_count": 24},
        },
        # 阿里 - EMA死叉，WATCH medium
        {
            "symbol": "HK:09988", "name": "阿里巴巴-W", "category": "large_tech",
            "generated_at": _today(),
            "action": "WATCH", "confidence": "MEDIUM",
            "summary": "EMA死叉形成，短期趋势向下，观望等待企稳信号",
            "triggers": ["MACD死叉形成"],
            "conflicts": ["EMA20 < EMA60 空头排列", "RSI=38.4 偏低但未超卖"],
            "indicators": {"ema20": 120.1, "ema60": 128.5, "adx14": 22.1, "rsi14": 38.4,
                           "macd_hist": -2.3, "bb_lower": 115.3, "bb_upper": 141.7,
                           "bb_mid": 128.5, "atr14": 4.2, "close": 123.0},
            "market_env": "BEAR", "market_env_note": "市场偏弱",
            "position": {"base_shares": 0, "swing_shares": 200, "base_pct": 0.0,
                         "swing_pct": 23.9, "total_pct": 23.9, "kelly_limit_pct": 20.0,
                         "available_swing_pct": 0.0},
            "stop_loss_pct": -10.0, "target_pct_1": 18.0,
            "backtest_ref": {"win_rate": 0.55, "ev_pct": 5.1, "kelly_pct": 12,
                             "credibility": "MEDIUM", "sample_count": 18},
        },
        # 小米 - EMA金叉+ADX强，HOLD high
        {
            "symbol": "HK:01810", "name": "小米集团-W", "category": "large_tech",
            "generated_at": _today(),
            "action": "HOLD", "confidence": "HIGH",
            "summary": "EMA金叉且ADX确认趋势，多头信号明确，继续持有",
            "triggers": ["EMA20 > EMA60 金叉持续中", "ADX=31.4 趋势明确"],
            "conflicts": [],
            "indicators": {"ema20": 41.8, "ema60": 37.9, "adx14": 31.4, "rsi14": 58.7,
                           "macd_hist": 1.8, "bb_lower": 38.1, "bb_upper": 47.3,
                           "bb_mid": 42.7, "atr14": 1.5, "close": 42.5},
            "market_env": "BEAR", "market_env_note": "市场偏弱，个股趋势独立",
            "position": {"base_shares": 0, "swing_shares": 500, "base_pct": 0.0,
                         "swing_pct": 20.6, "total_pct": 20.6, "kelly_limit_pct": 25.0,
                         "available_swing_pct": 4.4},
            "stop_loss_pct": -8.0, "target_pct_1": 20.0,
            "backtest_ref": {"win_rate": 0.68, "ev_pct": 11.2, "kelly_pct": 22,
                             "credibility": "HIGH", "sample_count": 31},
        },
        # 美团 - RSI超卖触发，BUY medium
        {
            "symbol": "HK:03690", "name": "美团-W", "category": "cyclical",
            "generated_at": _today(),
            "action": "BUY", "confidence": "MEDIUM",
            "summary": "RSI跌入超卖区，布林带下轨支撑，可考虑小仓位加仓",
            "triggers": ["RSI=28.3 触及超卖阈值30", "布林带下轨支撑位 181.2"],
            "conflicts": ["市场偏弱，需控制仓位"],
            "indicators": {"ema20": 192.4, "ema60": 205.1, "adx14": 19.8, "rsi14": 28.3,
                           "macd_hist": -3.7, "bb_lower": 181.2, "bb_upper": 221.8,
                           "bb_mid": 201.5, "atr14": 6.1, "close": 185.0},
            "market_env": "BEAR", "market_env_note": "市场偏弱，信号信心降级",
            "position": {"base_shares": 0, "swing_shares": 100, "base_pct": 0.0,
                         "swing_pct": 18.0, "total_pct": 18.0, "kelly_limit_pct": 15.0,
                         "available_swing_pct": 0.0},
            "stop_loss_pct": -9.0, "target_pct_1": 15.0,
            "backtest_ref": {"win_rate": 0.48, "ev_pct": 4.8, "kelly_pct": 8,
                             "credibility": "LOW", "sample_count": 12},
        },
        # 百济 - RSI偏低观望，WATCH low
        {
            "symbol": "HK:06160", "name": "百济神州", "category": "biotech",
            "generated_at": _today(),
            "action": "WATCH", "confidence": "LOW",
            "summary": "RSI接近超卖但未触发，生物医药板块波动大，观望为主",
            "triggers": [],
            "conflicts": ["RSI=33.5 接近30但未触发", "市场偏弱"],
            "indicators": {"ema20": 172.3, "ema60": 181.8, "adx14": 15.1, "rsi14": 33.5,
                           "macd_hist": -1.9, "bb_lower": 155.4, "bb_upper": 189.2,
                           "bb_mid": 172.3, "atr14": 8.7, "close": 169.0},
            "market_env": "BEAR", "market_env_note": "",
            "position": {"base_shares": 0, "swing_shares": 60, "base_pct": 0.0,
                         "swing_pct": 9.8, "total_pct": 9.8, "kelly_limit_pct": 6.0,
                         "available_swing_pct": 0.0},
            "stop_loss_pct": -12.0, "target_pct_1": 20.0,
            "backtest_ref": {"win_rate": 0.38, "ev_pct": 3.2, "kelly_pct": 4,
                             "credibility": "LOW", "sample_count": 8},
        },
        # META - EMA金叉强势，HOLD high
        {
            "symbol": "US:META", "name": "Meta Platforms", "category": "large_tech",
            "generated_at": _today(),
            "action": "HOLD", "confidence": "HIGH",
            "summary": "EMA金叉+ADX强势确认，趋势明确，继续持有",
            "triggers": ["EMA20 > EMA60 多头排列 (+5.2%)", "ADX=34.7 趋势强劲"],
            "conflicts": [],
            "indicators": {"ema20": 583.2, "ema60": 554.4, "adx14": 34.7, "rsi14": 61.2,
                           "macd_hist": 8.3, "bb_lower": 548.1, "bb_upper": 642.3,
                           "bb_mid": 595.2, "atr14": 15.4, "close": 596.0},
            "market_env": "NEUTRAL", "market_env_note": "",
            "position": {"base_shares": 0, "swing_shares": 40, "base_pct": 0.0,
                         "swing_pct": 27.0, "total_pct": 27.0, "kelly_limit_pct": 30.0,
                         "available_swing_pct": 3.0},
            "stop_loss_pct": -7.0, "target_pct_1": 15.0,
            "backtest_ref": {"win_rate": 0.65, "ev_pct": 9.8, "kelly_pct": 20,
                             "credibility": "HIGH", "sample_count": 28},
        },
        # MSFT - 横盘整理，HOLD medium
        {
            "symbol": "US:MSFT", "name": "Microsoft", "category": "large_tech",
            "generated_at": _today(),
            "action": "HOLD", "confidence": "MEDIUM",
            "summary": "EMA金叉维持但ADX偏弱横盘，持有等待方向选择",
            "triggers": ["EMA20 > EMA60 持续中"],
            "conflicts": ["ADX=19.3 趋势动能偏弱"],
            "indicators": {"ema20": 418.7, "ema60": 407.2, "adx14": 19.3, "rsi14": 52.8,
                           "macd_hist": 2.1, "bb_lower": 396.3, "bb_upper": 443.1,
                           "bb_mid": 419.7, "atr14": 8.2, "close": 420.0},
            "market_env": "NEUTRAL", "market_env_note": "",
            "position": {"base_shares": 0, "swing_shares": 50, "base_pct": 0.0,
                         "swing_pct": 23.8, "total_pct": 23.8, "kelly_limit_pct": 25.0,
                         "available_swing_pct": 1.2},
            "stop_loss_pct": -7.0, "target_pct_1": 12.0,
            "backtest_ref": {"win_rate": 0.60, "ev_pct": 7.4, "kelly_pct": 16,
                             "credibility": "HIGH", "sample_count": 22},
        },
        # TSLA - EMA死叉，WATCH medium
        {
            "symbol": "US:TSLA", "name": "Tesla", "category": "cyclical",
            "generated_at": _today(),
            "action": "WATCH", "confidence": "MEDIUM",
            "summary": "EMA死叉形成，短期趋势向下，等待支撑位企稳",
            "triggers": ["MACD动能走弱"],
            "conflicts": ["EMA20 < EMA60 空头排列", "RSI=39.1 偏弱"],
            "indicators": {"ema20": 272.1, "ema60": 291.8, "adx14": 26.4, "rsi14": 39.1,
                           "macd_hist": -4.8, "bb_lower": 248.3, "bb_upper": 315.7,
                           "bb_mid": 282.0, "atr14": 12.1, "close": 265.0},
            "market_env": "NEUTRAL", "market_env_note": "",
            "position": {"base_shares": 0, "swing_shares": 60, "base_pct": 0.0,
                         "swing_pct": 18.0, "total_pct": 18.0, "kelly_limit_pct": 12.0,
                         "available_swing_pct": 0.0},
            "stop_loss_pct": -10.0, "target_pct_1": 18.0,
            "backtest_ref": {"win_rate": 0.44, "ev_pct": 3.8, "kelly_pct": 6,
                             "credibility": "MEDIUM", "sample_count": 16},
        },
        # AMZN - 稳健持有，HOLD medium
        {
            "symbol": "US:AMZN", "name": "Amazon", "category": "large_tech",
            "generated_at": _today(),
            "action": "HOLD", "confidence": "MEDIUM",
            "summary": "EMA金叉持续，ADX轻度趋势，AWS增长支撑，持有为主",
            "triggers": ["EMA20 > EMA60 持续中"],
            "conflicts": ["ADX=21.8 轻度趋势"],
            "indicators": {"ema20": 230.8, "ema60": 220.4, "adx14": 21.8, "rsi14": 54.3,
                           "macd_hist": 2.9, "bb_lower": 214.2, "bb_upper": 251.8,
                           "bb_mid": 233.0, "atr14": 6.3, "close": 233.0},
            "market_env": "NEUTRAL", "market_env_note": "",
            "position": {"base_shares": 0, "swing_shares": 50, "base_pct": 0.0,
                         "swing_pct": 13.2, "total_pct": 13.2, "kelly_limit_pct": 20.0,
                         "available_swing_pct": 6.8},
            "stop_loss_pct": -7.0, "target_pct_1": 15.0,
            "backtest_ref": {"win_rate": 0.58, "ev_pct": 6.9, "kelly_pct": 14,
                             "credibility": "HIGH", "sample_count": 19},
        },
        # NVDA - RSI超卖区，BUY medium
        {
            "symbol": "US:NVDA", "name": "NVIDIA", "category": "large_tech",
            "generated_at": _today(),
            "action": "BUY", "confidence": "MEDIUM",
            "summary": "RSI跌入超卖，基本面强劲，可考虑逢低加仓，止损-10%",
            "triggers": ["RSI=27.4 进入超卖区", "布林带下轨附近"],
            "conflicts": ["EMA死叉形成，短期趋势向下"],
            "indicators": {"ema20": 111.3, "ema60": 124.8, "adx14": 28.7, "rsi14": 27.4,
                           "macd_hist": -5.2, "bb_lower": 101.4, "bb_upper": 138.2,
                           "bb_mid": 119.8, "atr14": 7.8, "close": 108.0},
            "market_env": "NEUTRAL", "market_env_note": "",
            "position": {"base_shares": 0, "swing_shares": 80, "base_pct": 0.0,
                         "swing_pct": 9.8, "total_pct": 9.8, "kelly_limit_pct": 18.0,
                         "available_swing_pct": 8.2},
            "stop_loss_pct": -10.0, "target_pct_1": 20.0,
            "backtest_ref": {"win_rate": 0.61, "ev_pct": 10.4, "kelly_pct": 18,
                             "credibility": "HIGH", "sample_count": 26},
        },
    ]
    return {"count": len(signals), "signals": signals}


# ─── 演示K线数据 ──────────────────────────────────────────────────

def _gen_trading_dates(n: int) -> List[str]:
    """生成最近 n 个交易日日期（跳过周末）"""
    dates = []
    d = datetime.now().date()
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return list(reversed(dates))


def _calc_ma(closes: List[float], period: int) -> List[Optional[float]]:
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(round(sum(closes[i - period + 1: i + 1]) / period, 4))
    return result


def get_demo_kline(symbol: str) -> Dict:
    """
    生成演示用K线数据（随机游走，从均价走向当前价）
    返回格式与 /api/stock/{symbol}/kline 一致
    """
    pos = get_demo_position(symbol)
    if not pos:
        return {"symbol": symbol, "ohlcv": [], "real_trades": [], "sim_trades": []}

    avg_cost    = pos["avg_cost"]
    cur_price   = pos["current_price"]
    total_bars  = 250   # 生成250根，前70根只用于MA预热，前端显示180根

    # 用 symbol 做随机种子，确保同一 symbol 每次生成结果一致
    seed = sum(ord(c) for c in symbol)
    rng = random.Random(seed)

    # 波动率：价格的 1.5%
    vol = avg_cost * 0.015

    # 让收盘价从 avg_cost 逐渐漂移到 cur_price
    drift_per_bar = (cur_price - avg_cost) / total_bars

    closes = []
    price = avg_cost
    for i in range(total_bars):
        price += drift_per_bar + rng.gauss(0, vol)
        price = max(price, avg_cost * 0.5)  # 不低于均价一半
        closes.append(round(price, 3))

    # 最后一根强制对齐当前价
    closes[-1] = cur_price

    dates = _gen_trading_dates(total_bars)

    ohlcv = []
    for i, (d, c) in enumerate(zip(dates, closes)):
        prev_c = closes[i - 1] if i > 0 else c
        o = round(prev_c + rng.gauss(0, vol * 0.3), 3)
        h = round(max(o, c) + abs(rng.gauss(0, vol * 0.5)), 3)
        l = round(min(o, c) - abs(rng.gauss(0, vol * 0.5)), 3)
        vol_shares = int(rng.uniform(500_000, 3_000_000))
        ohlcv.append({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": vol_shares})

    # 附加均线
    for period in [5, 10, 20, 30, 60, 200]:
        ma_vals = _calc_ma(closes, period)
        for j, bar in enumerate(ohlcv):
            bar[f"ma{period}"] = ma_vals[j]

    # 演示交易打点（真实 2 笔，模拟 3 笔）
    # 真实：买入（约90天前）+ 加仓（约45天前）
    buy1_idx  = total_bars - 90
    buy2_idx  = total_bars - 45
    sell1_idx = total_bars - 15

    real_trades = [
        {"date": dates[buy1_idx],  "type": "BUY",  "price": round(closes[buy1_idx] * 0.99, 3),
         "shares": pos["total_shares"] // 2, "pct": None},
        {"date": dates[buy2_idx],  "type": "BUY",  "price": round(closes[buy2_idx] * 1.01, 3),
         "shares": pos["total_shares"] // 2, "pct": None},
    ]

    sim_buy1_price  = round(closes[buy1_idx - 5] * 0.98, 3)
    sim_sell1_price = closes[sell1_idx]
    sim_pct = round((sim_sell1_price - sim_buy1_price) / sim_buy1_price * 100, 2)

    sim_trades = [
        {"date": dates[buy1_idx - 5], "type": "BUY",  "price": sim_buy1_price,
         "shares": int(pos["total_shares"] * 1.1), "pct": None},
        {"date": dates[sell1_idx],    "type": "SELL", "price": round(sim_sell1_price, 3),
         "shares": int(pos["total_shares"] * 1.1), "pct": sim_pct},
        {"date": dates[total_bars - 8], "type": "BUY", "price": round(closes[-8] * 0.995, 3),
         "shares": int(pos["total_shares"] * 0.8), "pct": None},
    ]

    return {
        "symbol":      symbol,
        "ohlcv":       ohlcv,
        "real_trades": real_trades,
        "sim_trades":  sim_trades,
    }


# ─── 演示持仓对比 ─────────────────────────────────────────────────

def get_demo_positions_compare(symbol: str) -> Dict:
    """返回演示的实盘 vs 模拟持仓对比数据"""
    pos = get_demo_position(symbol)
    if not pos:
        return {"symbol": symbol, "current_price": None, "real": None, "sim": None, "cash": {}}

    cur = pos["current_price"]
    avg = pos["avg_cost"]
    shares = pos["total_shares"]

    real = {
        "shares":       shares,
        "avg_cost":     avg,
        "market_value": round(cur * shares, 0),
        "pnl_amount":   round((cur - avg) * shares, 0),
        "pnl_pct":      round((cur - avg) / avg * 100, 1),
    }

    # 模拟持仓：比实盘多买了10%，成本略低
    sim_shares   = int(shares * 1.1)
    sim_avg_cost = round(avg * 0.97, 3)
    sim_mv       = round(cur * sim_shares, 0)
    sim_pnl      = round((cur - sim_avg_cost) * sim_shares, 0)
    sim_pnl_pct  = round((cur - sim_avg_cost) / sim_avg_cost * 100, 1)

    sim = {
        "snapshot_date":    "2026-02-21",
        "shares":           sim_shares,
        "avg_cost":         sim_avg_cost,
        "market_value":     sim_mv,
        "pnl_amount":       sim_pnl,
        "pnl_pct":          sim_pnl_pct,
        "initial_shares":   shares,
        "initial_avg_cost": avg,
    }

    cash = {"HKD": 85200.0, "USD": 12400.0} if pos["market"] == "HK" else {"HKD": 0, "USD": 18600.0}

    return {
        "symbol":        symbol,
        "current_price": cur,
        "real":  real,
        "sim":   sim,
        "cash":  cash,
        "demo":  True,
    }


# ─── 演示交易统计 + 时间轴 ────────────────────────────────────────

def get_demo_trades(symbol: str) -> Dict:
    """返回演示的交易统计和统一时间轴"""
    pos = get_demo_position(symbol)
    if not pos:
        return {"real": {"stats": {}}, "sim": {"stats": {}}, "timeline": []}

    avg  = pos["avg_cost"]
    cur  = pos["current_price"]

    # 用 K线里算好的打点日期，直接复用
    kline = get_demo_kline(symbol)
    real_trades = kline["real_trades"]
    sim_trades  = kline["sim_trades"]

    # 统计
    real_stats = {
        "total_trades": 2,
        "win_rate": 63.0,
        "avg_win_pct": 12.4,
        "avg_loss_pct": -6.1,
        "ev_pct": 5.6,
        "profit_factor": 2.03,
        "max_consecutive_loss": 1,
    }
    sim_stats = {
        "total_trades": 3,
        "win_rate": 66.7,
        "avg_win_pct": 14.2,
        "avg_loss_pct": -5.8,
        "ev_pct": 7.1,
        "profit_factor": 2.45,
        "max_consecutive_loss": 1,
    }

    # 合并时间轴
    sim_sell = sim_trades[1]  # 已出场的模拟卖出
    all_dates = sorted(
        set([t["date"] for t in real_trades] + [t["date"] for t in sim_trades]),
        reverse=True
    )

    real_by_date = {t["date"]: t for t in real_trades}
    sim_by_date  = {t["date"]: t for t in sim_trades}

    timeline = []
    for d in all_dates:
        r = real_by_date.get(d)
        s = sim_by_date.get(d)
        timeline.append({
            "date": d,
            "real": {"direction": "买入" if r["type"] == "BUY" else "卖出",
                     "price": r["price"], "shares": r["shares"],
                     "pct": r["pct"]} if r else None,
            "sim":  {"direction": "买入" if s["type"] == "BUY" else "卖出",
                     "price": s["price"], "shares": s["shares"],
                     "pct": s["pct"]} if s else None,
        })

    return {
        "real":     {"stats": real_stats},
        "sim":      {"stats": sim_stats},
        "timeline": timeline,
        "demo":     True,
    }
