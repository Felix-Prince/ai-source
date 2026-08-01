"""评分：AI 相关性分 + importance 分。

AI 相关性用关键词表粗筛（规则、可复现、零模型 token）。
importance = tier 权重 × AI 相关性分 × 新鲜度。
低于阈值的条目不进产物（在 collect.py 里过滤）。
"""
import re
import time

# AI 相关性关键词表。命中一个加 1 分，封顶 3 分（有多个词并不代表更相关）。
# 中英都覆盖，匹配标题+摘要（小写化处理英文）。
AI_KEYWORDS = [
    # 模型与厂商
    "gpt", "claude", "gemini", "llama", "mistral", "qwen", "deepseek",
    "openai", "anthropic", "google ai", "meta ai", "mistral ai",
    # 领域
    "large language model", "llm", "foundation model", "multimodal",
    "machine learning", "deep learning", "neural network", "transformer",
    "diffusion model", "rag", "fine-tune", "fine tuning", "prompt",
    "agent", "autonomous", "reasoning", "inference",
    # 基础设施
    "gpu", "tpu", "h100", "a100", "cuda", "api",
    # 中文
    "大模型", "人工智能", "机器学习", "深度学习", "神经网络", "智能体",
    "多模态", "推理", "算力", "芯片", "提示词", "上下文",
]

_AI_KEYWORDS_LOWER = [k.lower() for k in AI_KEYWORDS]


def ai_score(title, summary=""):
    """返回 0.0 ~ 3.0 的 AI 相关性分。"""
    text = "%s %s" % (title, summary)
    text_lower = text.lower()
    hits = 0
    for kw in _AI_KEYWORDS_LOWER:
        if re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(kw), text_lower) or kw in text_lower:
            hits += 1
    return float(min(hits, 3))


def importance(tier, ai_score_value, published_ts=None, now=None):
    """tier权重 × AI相关性 × 新鲜度。新鲜度按 (now-published) 指数衰减。

    约 24h 内新鲜度因子从 1.0 降到 ~0.37，7 天降到 ~0.01，几乎淘汰。
    """
    tier_w = {0: 1.5, 1: 1.0, 2: 0.6}[tier]
    now = now or time.time()
    freshness = 1.0
    if published_ts is not None:
        age_hours = max(0.0, (now - published_ts) / 3600.0)
        freshness = 2.0 ** (-age_hours / 24.0)
    return round(tier_w * ai_score_value * freshness, 3)
