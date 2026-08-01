"""源健康：写 source-status.json 看板。

每条源记录最近一轮的状态：ok / failed / disabled / skipped(网络失败但没到抛错级别)。
持续失败的源在 sources.yaml 里 enabled:false 关掉即可。
"""
import json
import time
from datetime import datetime, timezone


def update(source_status, source_cfg, status, error=None, item_count=0):
    """更新单源本轮状态。status: ok|failed|disabled|skipped"""
    name = source_cfg["name"]
    now_ts = time.time()
    now_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
    rec = source_status.setdefault(name, {})
    rec["status"] = status
    rec["last_run_at"] = now_iso
    rec["last_run_ts"] = now_ts
    rec["url"] = source_cfg["url"]
    if status == "failed":
        rec["error"] = error
        rec["fail_count"] = rec.get("fail_count", 0) + 1
    else:
        rec["error"] = None
        rec["fail_count"] = 0
    if status == "ok":
        rec["item_count"] = item_count
    return source_status


def write(path, source_status):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(source_status, f, ensure_ascii=False, indent=2)
