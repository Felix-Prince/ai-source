#!/usr/bin/env python3
"""采集主入口。

用法：
  python scripts/collect.py [--output-dir data] [--window-hours 24]

流程：读 sources.yaml → 逐个抓源(RSS优先) → 归一 → AI评分 → 去重 →
     过滤时间窗+低分 → 写 latest-24h.json + 滚动 archive.json + source-status.json。

单源失败不阻断整轮，失败原因进 source-status.json。
零模型依赖、零密钥。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    sys.exit("缺少依赖 yaml，请先: python -m pip install -r requirements.txt")

# 允许从任意 cwd 运行：以本文件所在目录为项目根
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.fetchers import rss
from scripts.fetchers.base import FetchError
from scripts import dedupe, health, normalize, score

AI_SCORE_THRESHOLD = 1.5   # AI 相关性分低于此值不进产物（2026-08-13 从 1.0 调高，提升 latest-24h 质量）
MAX_ARCHIVE_DAYS = 30      # archive 滚动天数
MAX_BATCH_DAYS = 30        # batches 滚动天数（时间轴深度）
MAX_ITEMS_PER_SOURCE = 50  # 单源每轮最多保留的条目（防全历史 feed 灌入）


def load_sources(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return [s for s in cfg.get("sources", []) if s.get("enabled")]


def fetch_source(source_cfg):
    """抓单源。返回 (items, ok, error)。"""
    ftype = source_cfg.get("type", "rss")
    try:
        if ftype == "rss":
            items = rss.fetch(source_cfg)
        else:
            raise FetchError("unsupported type: %s" % ftype)
        return items, True, None
    except FetchError as exc:
        return [], False, str(exc)


def load_archive(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except (OSError, ValueError):
        return []


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=os.path.join(PROJECT_ROOT, "data"))
    parser.add_argument("--window-hours", type=float, default=24.0)
    args = parser.parse_args()

    outdir = args.output_dir
    os.makedirs(outdir, exist_ok=True)
    sources_path = os.path.join(PROJECT_ROOT, "config", "sources.yaml")
    latest_path = os.path.join(outdir, "latest-24h.json")
    archive_path = os.path.join(outdir, "archive.json")
    status_path = os.path.join(outdir, "source-status.json")

    sources = load_sources(sources_path)
    if not sources:
        sys.exit("sources.yaml 里没有 enabled:true 的源，退出")

    now = time.time()
    now_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    window = args.window_hours * 3600.0

    source_status = {}
    entries = []
    for cfg in sources:
        items, ok, err = fetch_source(cfg)
        if not ok:
            health.update(source_status, cfg, "failed", error=err)
            continue
        # 归一 + 评分
        # 单源截断：全历史 feed（如 OpenAI 1100+ 条）按发布时间取最新 N 条，防历史内容每轮灌入
        items = sorted(items, key=lambda it: it.published_ts or 0, reverse=True)[:MAX_ITEMS_PER_SOURCE]
        for it in items:
            a = score.ai_score(it.title, it.summary)
            imp = score.importance(cfg.get("tier", 1), a, it.published_ts, now)
            entry = normalize.to_entry(it, cfg, ai_score=a, importance=imp)
            entries.append(entry)
        health.update(source_status, cfg, "ok", item_count=len(items))

    # 去重（含与 archive 的精确+近似去重）
    archive_items = load_archive(archive_path)
    dedup_input = archive_items + entries
    deduped_all = dedupe.dedupe(dedup_input)
    # 本轮相对 archive 真正新增的条目（id 不在旧 archive 里）
    archive_ids = {e["id"] for e in archive_items}
    deduped_new = [e for e in deduped_all if e["id"] in {x["id"] for x in entries}
                   and e["id"] not in archive_ids]

    # 过滤：AI 相关性 >= 阈值 且 在时间窗内（基于"本轮新增"，跨批次不重复）
    # 这是时间轴每轮展示的内容（方案A：每轮只记新增）
    fresh = [
        e for e in deduped_new
        if e.get("ai_score", 0) >= AI_SCORE_THRESHOLD
        and (e.get("published_ts") is None or now - e["published_ts"] <= window)
    ]
    fresh.sort(key=lambda e: e.get("importance", 0), reverse=True)

    # latest-24h.json：截至本轮，24h 窗口内全部去重后的 AI 条目
    # （本轮新增 + archive 中仍在窗口内的旧条目），给消费方完整视图
    latest_items = [
        e for e in deduped_all
        if e.get("ai_score", 0) >= AI_SCORE_THRESHOLD
        and (e.get("published_ts") is None or now - e["published_ts"] <= window)
    ]
    latest_items.sort(key=lambda e: e.get("importance", 0), reverse=True)

    latest = {
        "meta": {
            "generated_at": now_iso,
            "generated_ts": now,
            "window_hours": args.window_hours,
            "total": len(latest_items),
        },
        "items": latest_items,
    }
    write_json(latest_path, latest)

    # 滚动 archive：合并本轮 + 旧 archive（去重后），裁剪到 MAX_ARCHIVE_DAYS
    merged = {e["id"]: e for e in deduped_all}
    cutoff = now - MAX_ARCHIVE_DAYS * 86400
    merged = {k: v for k, v in merged.items()
              if v.get("published_ts") is None or v["published_ts"] >= cutoff}
    write_json(archive_path, {
        "meta": {"generated_at": now_iso, "max_days": MAX_ARCHIVE_DAYS},
        "items": sorted(merged.values(), key=lambda e: e.get("published_ts") or 0),
    })

    # 采集批次日志：每轮一条，供可视化时间轴（每 2h 一个刻度，段内展示该轮条目）
    # 只存轻量字段控制体积，滚动保留 MAX_BATCH_DAYS
    batch_path = os.path.join(outdir, "batches.json")
    try:
        with open(batch_path, "r", encoding="utf-8") as f:
            batches = json.load(f).get("batches", [])
    except (OSError, ValueError):
        batches = []
    batch_items = [{
        "id": e["id"], "title": e["title"], "source": e["source"],
        "source_label": e["source_label"], "importance": e["importance"],
        "url": e["url"], "published_at": e["published_at"],
        "summary": (e.get("summary") or "")[:300],  # 截断摘要控体积
    } for e in fresh]
    batches.append({
        "generated_at": now_iso,
        "generated_ts": now,
        "sources": {name: v.get("item_count", 0) for name, v in source_status.items()
                    if v["status"] == "ok"},
        "items": batch_items,
    })
    batch_cutoff = now - MAX_BATCH_DAYS * 86400
    batches = [b for b in batches if b.get("generated_ts", 0) >= batch_cutoff]
    write_json(batch_path, {
        "meta": {"generated_at": now_iso, "max_days": MAX_BATCH_DAYS},
        "batches": batches,
    })

    health.write(status_path, source_status)

    print("sources ok=%d failed=%d" % (
        sum(1 for s in source_status.values() if s["status"] == "ok"),
        sum(1 for s in source_status.values() if s["status"] == "failed"),
    ))
    print("fetched=%d  new=%d  latest24h=%d  batch_new=%d  (window %.0fh, ai_score>=%.1f)" % (
        len(entries), len(deduped_new), len(latest_items), len(fresh),
        args.window_hours, AI_SCORE_THRESHOLD,
    ))


if __name__ == "__main__":
    main()
