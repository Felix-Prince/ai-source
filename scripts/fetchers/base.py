"""公共抓取层：重试 / 超时 / 伪装 UA / 限并发 → RawItem。

所有 fetcher 统一从这里拿 session 与失败语义，保证单源失败不阻断整轮。
"""
import threading
import time
import warnings
from collections import namedtuple

import requests

# 个别源（如 cnbeta）用 insecure_tls: true 关闭证书校验，
# 抑制由此产生的 InsecureRequestWarning，避免每轮日志刷屏。
requests.packages.urllib3.disable_warnings(
    requests.packages.urllib3.exceptions.InsecureRequestWarning
)

# ---- 条目中间结构 ----
RawItem = namedtuple(
    "RawItem",
    ["source", "title", "url", "summary", "published_ts", "raw"],
)

# 伪装浏览器 UA，规避简单 UA 屏蔽
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

TIMEOUT = 60          # 单请求超时(秒)
MAX_RETRIES = 3       # 重试次数
RETRY_BACKOFF = 2.0   # 重试退避基数(秒)
MAX_CONCURRENT = 4    # 全局并发上限

# 简单并发闸：所有 fetcher 共享，限制同时进行的 HTTP 请求数
_semaphore = threading.Semaphore(MAX_CONCURRENT)


class FetchError(Exception):
    """抓取失败（网络/解析），携带原因供 source-status 记录。"""


def get(url, **kwargs):
    """带重试+并发闸的 GET，返回 requests.Response；多次失败抛 FetchError。"""
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("headers", {"User-Agent": UA})
    last_err = None
    for attempt in range(MAX_RETRIES):
        with _semaphore:
            try:
                resp = requests.get(url, **kwargs)
                if resp.status_code == 200:
                    return resp
                last_err = "HTTP %d" % resp.status_code
            except requests.RequestException as exc:
                last_err = "%s: %s" % (type(exc).__name__, exc)
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    raise FetchError("GET %s failed after %d tries: %s" % (url, MAX_RETRIES, last_err))


def parse_datetime(value):
    """把 feedparser/dateutil 解析不了的值兜底转成 timestamp；失败返回 None。

    各源时间格式差异在这里收敛，Normalizer 无需关心原始格式。
    """
    if not value:
        return None
    # 已是最常见的 datetime 对象（feedparser 已解析过）
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from dateutil import parser as dtparser
        return dtparser.parse(value).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None
