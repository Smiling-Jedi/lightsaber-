"""
信号今日小结服务

调用 Anthropic API 为每只股票生成自然语言解读。
缓存策略：(symbol, date, action, market_env) 相同时复用，不重复生成。
"""
import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# 内存缓存：key=(symbol, date_str, action, market_env) → summary_text
_cache: dict = {}


def _build_prompt(sig: dict) -> str:
    ind = sig.get("indicators", {})
    category = sig.get("category", "large_tech")
    action = sig.get("action", "HOLD")
    confidence = sig.get("confidence", "MEDIUM")
    market_env = sig.get("market_env", "NEUTRAL")
    market_note = sig.get("market_env_note", "")
    stop = sig.get("stop_loss_pct")
    target = sig.get("target_pct_1")

    # 策略标签
    strategy_map = {
        "large_tech": "EMA金叉策略",
        "cyclical":   "RSI超卖策略",
        "defensive":  "布林均值策略",
        "biotech":    "RSI极值策略",
    }
    strategy = strategy_map.get(category, category)

    # 信号文字
    action_map = {"BUY": "买入", "SELL": "卖出", "WATCH": "观察", "HOLD": "持有"}
    conf_map = {"HIGH": "高", "MEDIUM": "中等", "LOW": "低"}
    env_map = {"BEAR": "偏弱", "BULL": "偏强", "NEUTRAL": "中性"}

    # 构建指标摘要
    indicator_lines = []
    if category == "large_tech":
        ema20 = ind.get("ema20")
        ema60 = ind.get("ema60")
        adx = ind.get("adx14")
        if ema20 and ema60:
            diff = (ema20 - ema60) / ema60 * 100
            cross = "金叉（多头排列）" if ema20 > ema60 else f"死叉（空头排列 {diff:.1f}%）"
            indicator_lines.append(f"EMA20/60：{cross}，EMA20={ema20:.1f}，EMA60={ema60:.1f}")
        if adx:
            indicator_lines.append(f"ADX={adx:.1f}（趋势强度，>25为明确趋势）")
    elif category in ("cyclical", "defensive"):
        rsi = ind.get("rsi14")
        bb_lower = ind.get("bb_lower")
        close = ind.get("close")
        if rsi:
            indicator_lines.append(f"RSI={rsi:.1f}")
        if close and bb_lower:
            near = close <= bb_lower * 1.02
            indicator_lines.append(f"布林下轨={bb_lower:.2f}，当前价={close:.2f}，{'已触下轨' if near else '未触下轨'}")
    elif category == "biotech":
        rsi = ind.get("rsi14")
        atr = ind.get("atr14")
        close = ind.get("close")
        if rsi:
            indicator_lines.append(f"RSI={rsi:.1f}（极值阈值<30）")
        if atr and close:
            indicator_lines.append(f"ATR日波动={atr/close*100:.1f}%")

    if market_note:
        indicator_lines.append(f"大盘：{market_note}")
    elif market_env != "NEUTRAL":
        indicator_lines.append(f"大盘：{env_map.get(market_env, market_env)}")

    stop_target = ""
    if stop and target:
        stop_target = f"\n止损参考：{stop:.1f}%，目标：+{target:.0f}%"

    indicators_text = "\n".join(f"  {l}" for l in indicator_lines)

    prompt = f"""你是一个股票交易助手，帮助分析持仓信号。

股票：{sig.get('name', sig.get('symbol'))}（{strategy}）
当前信号：{action_map.get(action, action)}，信心{conf_map.get(confidence, confidence)}，市场{env_map.get(market_env, market_env)}
指标状态：
{indicators_text}{stop_target}

请用1-2句话写"今日小结"，要求：
1. 直接说当前操作建议（底仓/波段怎么做）
2. 关键数据自然嵌入句子里（不要另起一行列数字）
3. 如有等待条件，说清楚等什么
4. 不超过60字
只输出小结正文，不要任何前缀。"""

    return prompt


def generate_summary(sig: dict) -> Optional[str]:
    """
    为单只股票生成今日小结。
    sig 为 SignalResult 序列化后的 dict。
    """
    symbol = sig.get("symbol", "")
    action = sig.get("action", "HOLD")
    market_env = sig.get("market_env", "NEUTRAL")
    today = str(date.today())

    cache_key = (symbol, today, action, market_env)
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if not api_key:
            logger.warning(f"未设置 ANTHROPIC_API_KEY，跳过小结生成")
            return None

        # 初始化 Anthropic 客户端，支持 Kimi Code 中转
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)

        prompt = _build_prompt(sig)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        _cache[cache_key] = text
        return text

    except Exception as e:
        logger.warning(f"生成今日小结失败 {symbol}: {e}")
        return None
