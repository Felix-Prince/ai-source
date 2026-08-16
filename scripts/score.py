"""评分：AI 相关性分 + importance 分 + 人物内容排除。

AI 相关性用关键词表粗筛（规则、可复现、零模型 token）。
importance = tier 权重 × AI 相关性分 × 新鲜度。
低于阈值的条目不进产物（在 collect.py 里过滤）。
人物驱动的内容（公众人物 + 动作）不进产物，除非同时是强 AI 技术新闻。
"""
import re
import time

# AI 相关性关键词表。命中一个加 1 分，封顶 3 分（有多个词并不代表更相关）。
# 中英都覆盖，匹配标题+摘要（小写化处理英文）。
AI_KEYWORDS = [
    # 模型与厂商
    "gpt", "claude", "gemini", "llama", "mistral", "qwen", "deepseek",
    "openai", "anthropic", "google ai", "meta ai", "mistral ai",
    "sora", "whisper", "dall-e", "midjourney", "stable diffusion",
    "glm", "grok", "phi", "kimi", "doubao", "minimax", "bailian",
    # 领域
    "large language model", "llm", "foundation model", "multimodal",
    "machine learning", "deep learning", "neural network", "transformer",
    "diffusion model", "rag", "fine-tune", "fine tuning", "prompt",
    "agent", "autonomous", "reasoning", "inference",
    "embedding", "token", "context window", "mixture of experts", "moe",
    # 基础设施
    "gpu", "tpu", "h100", "a100", "cuda", "api",
    "training", "inference", "quantization", "open-source model", "open source model",
    # 中文
    "大模型", "人工智能", "机器学习", "深度学习", "神经网络", "智能体",
    "多模态", "推理", "算力", "芯片", "提示词", "上下文",
    "模型", "算法", "数据集", "开源模型", "训练", "微调",
]

# ---- 人物排除（2026-08-15 新增）----
# 公众人物名单（科技/AI 领域高频）。命中名单 + 命中动作词 → 人物驱动内容。
PUBLIC_FIGURES = [
    # 中文名
    "奥特曼", "山姆·奥特曼", "马斯克", "埃隆·马斯克", "黄仁勋", "李开复",
    "周鸿祎", "雷军", "李彦宏", "马化腾", "张一鸣", "刘强东", "马云",
    "杨立昆", "杰弗里·辛顿", "辛顿", "吴恩达", "陆奇", "王小川", "傅盛",
    "李飞飞", "姚期智", "朱啸虎", "徐小平", "余承东", "任正非", "张朝阳",
    # 英文名（小写匹配）
    "sam altman", "altman", "elon musk", "jensen huang",
    "yann lecun", "geoffrey hinton", "hinton",
    "sundar pichai", "satya nadella", "tim cook",
    "mark zuckerberg", "mira murati", "ilya sutskever",
    "dario amodei", "demis hassabis",
]

# 人物动作词：与人物名单组合判定「人物驱动内容」
FIGURE_ACTIONS = [
    # 中文
    "称", "表示", "宣布", "回应", "透露", "谈", "认为", "预言", "警告",
    "炮轰", "怒批", "点赞", "看好", "看空", "离职", "加盟", "专访",
    "对话", "观点", "建议", "呼吁", "驳斥", "辟谣", "被曝", "被传",
    "澄清", "吐槽", "评价", "回应了", "在个人社交",
    # 英文（小写匹配，含 in/with 分隔，如 "talks about" / "speaks on"）
    "says", "said", "announces", "announced", "talks", "talked", "spoke",
    "speaks", "claims", "predicts", "warns", "calls for", "quits", "leaves",
    "leaving", "joins", "interview", "interviewed", "opinion", "urges",
    "responds", "responded", "denies", "denied", "suggests", "suggested",
]

_FIGURES_LOWER = [f.lower() for f in PUBLIC_FIGURES]
_AI_KEYWORDS_LOWER = [k.lower() for k in AI_KEYWORDS]

# 排除豁免：人物内容里命中 ≥2 个 AI 技术词视为技术新闻，不排除。
# 例："OpenAI CEO 宣布发布 GPT-5" 保留；"马斯克回应特斯拉剥离业务" 排除。
_TECH_EXEMPT = 2


def is_figure_content(title, summary=""):
    """人物驱动内容判定：命中公众人物名单 + 动作词 → True（应排除）。

    例外：同时命中 >= _TECH_EXEMPT 个 AI 技术词时视为技术新闻，返回 False（保留）。
    """
    text = "%s %s" % (title, summary)
    text_lower = text.lower()
    has_figure = any(f in text_lower for f in _FIGURES_LOWER)
    if not has_figure:
        return False
    has_action = any(a in text for a in FIGURE_ACTIONS)
    if not has_action:
        return False
    tech_hits = sum(1 for kw in _AI_KEYWORDS_LOWER if kw in text_lower)
    return tech_hits < _TECH_EXEMPT


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
