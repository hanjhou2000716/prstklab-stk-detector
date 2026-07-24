"""Public, link-only update feed for the macro program requested by the user."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import requests


YUTINGHAO_CHANNEL_ID = "UC0lbAQVpenvfA2QqzsRtL_g"
YUTINGHAO_FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YUTINGHAO_CHANNEL_ID}"
ATOM = "{http://www.w3.org/2005/Atom}"


def fetch_yutinghao_latest_program() -> dict[str, Any]:
    """Return the latest public program metadata, not a transcript or inference."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = requests.get(YUTINGHAO_FEED_URL, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            break
        except (requests.RequestException, ET.ParseError) as exc:
            last_error = exc
    else:
        raise ValueError("公開節目來源暫時無法取得。") from last_error
    entry = root.find(f"{ATOM}entry")
    if entry is None:
        raise ValueError("公開節目來源沒有可用更新。")
    link = next(
        (item.get("href") for item in entry.findall(f"{ATOM}link") if item.get("rel", "alternate") == "alternate"),
        None,
    )
    title = entry.findtext(f"{ATOM}title")
    published = entry.findtext(f"{ATOM}published")
    if not title or not link:
        raise ValueError("公開節目來源缺少標題或連結。")
    return {
        "title": title.strip(),
        "url": link,
        "published_at": published,
        "source": "游庭皓的財經皓角｜YouTube",
    }
