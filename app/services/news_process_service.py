"""
新闻 LLM 处理服务
一次 Kimi 调用，批量完成英文标题翻译 + 重要度打分
"""
import json
import logging
import os

logger = logging.getLogger(__name__)


def process_news(items: list[dict]) -> list[dict]:
    """
    批量翻译标题 + 打分。

    Args:
        items: list of {"title": str, "summary": str, ...}

    Returns:
        同样的 list，每条新增 title_zh 和 importance 字段。
        调用失败时 importance 降级为 MEDIUM，title_zh = title。
    """
    if not items:
        return items

    try:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if not api_key:
            logger.warning("未设置 ANTHROPIC_API_KEY，跳过翻译")
            for it in items:
                it["title_zh"] = it.get("title", "")
                it["importance"] = "MEDIUM"
            return items

        # 初始化 Anthropic 客户端，支持 Kimi Code 中转
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)

        lines = []
        for i, it in enumerate(items):
            title = it.get("title", "")
            summary = (it.get("summary") or "")[:120]
            lines.append(f"{i+1}. 标题：{title}\n   摘要：{summary}")

        news_text = "\n\n".join(lines)

        prompt = f"""你是财经新闻分析助手。对以下{len(items)}条新闻，分别完成：
1. 将英文标题翻译成中文（简洁准确，不超过30字）
2. 评估对股价的重要度：
   - HIGH：财报/监管处罚/重大收购/CEO变动/产品大事件等直接影响股价
   - MEDIUM：行业动态/分析师评级/市场趋势等间接影响
   - LOW：背景资讯/公司介绍/无实质影响

{news_text}

严格按 JSON 数组返回，不要其他文字：
[{{"title_zh":"...","importance":"HIGH"}},{{"title_zh":"...","importance":"MEDIUM"}},...] """

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # 提取 JSON（防止模型在前后加文字）
        start = raw.find("[")
        end = raw.rfind("]") + 1
        parsed = json.loads(raw[start:end])

        for i, it in enumerate(items):
            if i < len(parsed):
                it["title_zh"]   = parsed[i].get("title_zh") or it.get("title", "")
                it["importance"] = parsed[i].get("importance", "MEDIUM")
            else:
                it["title_zh"]   = it.get("title", "")
                it["importance"] = "MEDIUM"

        return items

    except Exception as e:
        logger.warning(f"新闻 LLM 处理失败，降级处理: {e}")
        for it in items:
            it["title_zh"]   = it.get("title", "")
            it["importance"] = "MEDIUM"
        return items
