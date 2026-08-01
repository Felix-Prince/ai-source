"""去重：精确去重（哈希）+ 近似去重（SequenceMatcher 相似度）。

MVP 只去重，不做完整故事线合并（留 hook：_story_key 预留）。
精确去重基于 entry['id']（源+标题哈希）。
近似去重对标题相似度 > SIMILARITY_THRESHOLD 的条目保留 importance 更高者。
"""
from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.8  # 标题相似度阈值


def exact_dedupe(entries):
    """按 id 去重，保留首次出现。"""
    seen = set()
    out = []
    for e in entries:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append(e)
    return out


def _title_pair(e1, e2):
    return (e1.get("title") or "").lower(), (e2.get("title") or "").lower()


def fuzzy_dedupe(entries):
    """近似去重：相似标题只保留 importance 最高的一条。

    O(n^2)，条目量小（单轮几百条）可接受；量大时再考虑索引。
    """
    entries = sorted(entries, key=lambda e: e.get("importance", 0), reverse=True)
    keep = []
    for e in entries:
        dup = False
        for kept in keep:
            t1, t2 = _title_pair(e, kept)
            if not t1 or not t2:
                continue
            if SequenceMatcher(None, t1, t2).ratio() > SIMILARITY_THRESHOLD:
                dup = True
                break
        if not dup:
            keep.append(e)
    return keep


def dedupe(entries):
    return fuzzy_dedupe(exact_dedupe(entries))


# ---- 故事线合并 hook（MVP 不用，预留） ----
def _story_key(entry):
    return entry.get("title", "").lower()
