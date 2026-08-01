"""归一化：RawItem → 结构化条目 dict。

把各源差异收敛成统一 schema，供下游消费方稳定读取。字段：
  id          源名+标题哈希，去重用主键
  source      信源 name（sources.yaml 里的 name）
  source_label 人类可读信源名（后续从 sources.yaml 补，MVP 先用 name）
  title       标题
  url         链接
  summary     摘要
  published_at ISO8601 时间（UTC）
  published_ts 时间戳（秒，排序/新鲜度用）
  category    国内/国际
  lang        zh/en
  tier        信源梯级
  ai_score    AI 相关性分（score.py 填）
  importance  importance 分（score.py 填）
"""
import hashlib
import re
from datetime import datetime, timezone


def _normalize_title(raw_title):
    return re.sub(r"\s+", " ", raw_title).strip()


def to_entry(raw, source_cfg, ai_score=0.0, importance=0.0):
    title = _normalize_title(raw.title)
    published_ts = raw.published_ts
    published_at = None
    if published_ts is not None:
        published_at = datetime.fromtimestamp(
            published_ts, tz=timezone.utc
        ).isoformat()

    entry = {
        "id": "%s:%s" % (raw.source, hashlib.md5(title.encode("utf-8")).hexdigest()[:12]),
        "source": raw.source,
        "source_label": source_cfg.get("source_label", raw.source),
        "title": title,
        "url": raw.url,
        "summary": raw.summary,
        "published_at": published_at,
        "published_ts": published_ts,
        "category": source_cfg.get("category", "unknown"),
        "lang": source_cfg.get("lang", "en"),
        "tier": source_cfg.get("tier", 1),
        "ai_score": ai_score,
        "importance": importance,
    }
    return entry
