"""RSS/Atom 抓取（主干）。

用 feedparser 解析，兼容 RSS 2.0 / Atom / JSON feed 的常见字段差异，
把条目归一成 RawItem 交给 normalize 层。
"""
import feedparser

from .base import FetchError, RawItem, get, parse_datetime


def fetch(source_cfg):
    """抓单个 RSS 源，返回 RawItem 列表。失败抛 FetchError 由调用方记录。"""
    url = source_cfg["url"]
    # 个别源 TLS 证书链不完整（如 cnBeta 的 .tw 镜像缺中间证书，GH Actions Ubuntu 下
    # 验证失败而本地 macOS 能通），用 insecure_tls: true 仅对该源关闭证书校验。
    kwargs = {}
    if source_cfg.get("insecure_tls"):
        kwargs["verify"] = False
    try:
        resp = get(url, **kwargs)
    except FetchError:
        raise
    feed = feedparser.parse(resp.content)

    # feedparser 对非 XML 内容会报 bozo，且 entries 为空，提前暴露
    if feed.get("bozo") and not feed.get("entries"):
        err = getattr(feed.get("bozo_exception"), "__str__", lambda: "bozo")()
        raise FetchError("parse %s: %s" % (url, err))

    items = []
    for entry in feed.get("entries", []):
        published = entry.get("published") or entry.get("updated") or None
        items.append(
            RawItem(
                source=source_cfg["name"],
                title=(entry.get("title") or "").strip(),
                url=(entry.get("link") or "").strip(),
                summary=(entry.get("summary") or entry.get("description") or "").strip(),
                published_ts=parse_datetime(published),
                raw=entry,
            )
        )
    return items
