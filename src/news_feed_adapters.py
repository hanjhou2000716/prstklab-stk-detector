"""Fail-soft adapters for first-party market-news feeds.

The adapter boundary is intentionally small: each provider is fetched and
parsed independently, then converted to the raw story shape consumed by
``risk_news`` and the canonical News Intelligence contract.  A provider
failure is returned as health metadata and never prevents another provider
from being attempted.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests

from src.value_fundamentals import SEC_USER_AGENT

RequestFn = Callable[..., Any]

FEED_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "provider_id": "twse",
        "market": "taiwan",
        "kind": "json",
        "url": "https://openapi.twse.com.tw/v1/news/newsList",
        "timeout_seconds": 8,
        "enabled": True,
    },
    {
        "provider_id": "mops",
        "market": "taiwan",
        "kind": "json",
        "url": "https://mops.twse.com.tw/mops/api/t05st02",
        "timeout_seconds": 8,
        "enabled": True,
    },
    {
        "provider_id": "sec",
        "market": "us",
        "kind": "rss",
        "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-k&count=100&output=atom",
        "timeout_seconds": 8,
        "enabled": True,
    },
    {
        "provider_id": "fed",
        "market": "us",
        "kind": "rss",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "timeout_seconds": 8,
        "enabled": True,
    },
    # Nasdaq's public site does not expose one stable, documented RSS URL.
    # Keep it in the registry for provenance and enable it when a supported
    # endpoint is configured explicitly by deployment settings.
    {
        "provider_id": "nasdaq",
        "market": "us",
        "kind": "rss",
        "url": "",
        "timeout_seconds": 8,
        "enabled": False,
        "disabled_reason": "no stable documented public feed endpoint",
    },
)


def feed_catalog() -> list[dict[str, Any]]:
    """Return a serialisable copy suitable for source-health diagnostics."""
    return [dict(item) for item in FEED_CATALOG]


def _headers(provider_id: str) -> dict[str, str]:
    if provider_id == "sec":
        return {"User-Agent": SEC_USER_AGENT, "Accept": "application/atom+xml,application/xml"}
    return {"User-Agent": "PRStKInvestmentSystem/1.0", "Accept": "application/rss+xml,application/atom+xml,application/json"}


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return " ".join(_text(item) for item in value)
    return " ".join(str(value).split())


def _json_stories(payload: Any, provider_id: str, base_url: str, market: str) -> list[dict[str, Any]]:
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next((payload[key] for key in ("data", "results", "items", "news") if isinstance(payload.get(key), list)), [])
    else:
        rows = []
    stories: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        title = _text(row.get("title") or row.get("subject") or row.get("headline") or row.get("訊息標題") or row.get("主旨"))
        url = _text(row.get("url") or row.get("link") or row.get("web_url") or row.get("網址"))
        if url and url.startswith("/"):
            url = urljoin(base_url, url)
        if not title or not url:
            continue
        stories.append({
            "title": title,
            "url": url,
            "published_at": _date(row.get("published_at") or row.get("published") or row.get("date") or row.get("時間") or row.get("發佈時間")),
            "source": provider_id.upper(),
            "provider": provider_id,
            "source_tier": "official",
            "authority_tier": "official",
            "market": market,
            "relevance": "official",
        })
    return stories[:10]


def _rss_stories(payload: str, provider_id: str, base_url: str, market: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(payload)
    stories: list[dict[str, Any]] = []
    for entry in root.findall(".//item") + root.findall(".//{*}entry"):
        title = _text(entry.findtext("title") or entry.findtext("{*}title"))
        link = _text(entry.findtext("link") or entry.findtext("{*}link"))
        if not link:
            node = entry.find("{*}link")
            link = _text(node.attrib.get("href") if node is not None else "")
        if link and link.startswith("/"):
            link = urljoin(base_url, link)
        if not title or not link:
            continue
        published = entry.findtext("pubDate") or entry.findtext("{*}published") or entry.findtext("{*}updated")
        stories.append({
            "title": title,
            "url": link,
            "published_at": _date(published),
            "source": provider_id.upper(),
            "provider": provider_id,
            "source_tier": "official",
            "authority_tier": "official",
            "market": market,
            "relevance": "official",
        })
    return stories[:10]


def fetch_official_market_news(
    market: str,
    *,
    requester: RequestFn = requests.get,
    catalog: list[dict[str, Any]] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Fetch official stories with per-provider failure isolation.

    The return value is deliberately explicit so callers can distinguish a
    successful empty feed from a failed provider and expose that distinction
    in source-health cards.
    """
    stories: list[dict[str, Any]] = []
    health: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item in catalog or list(FEED_CATALOG):
        if item.get("market") != market:
            continue
        provider_id = str(item["provider_id"])
        url = str(item.get("url") or "")
        if not item.get("enabled", True) or not url:
            health.append({"provider": provider_id, "status": "disabled", "source_url": url or None, "reason": item.get("disabled_reason")})
            continue
        try:
            response = requester(url, headers=_headers(provider_id), timeout=float(item.get("timeout_seconds", 8)))
            response.raise_for_status()
            if item.get("kind") == "json":
                payload = response.json() if hasattr(response, "json") else json.loads(response.text)
                parsed = _json_stories(payload, provider_id, url, market)
            else:
                parsed = _rss_stories(str(getattr(response, "text", "")), provider_id, url, market)
            stories.extend(parsed)
            health.append({"provider": provider_id, "status": "healthy" if parsed else "no_event", "source_url": url, "item_count": len(parsed)})
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            status = "rate_limited" if status_code == 429 else "failed"
            health.append({"provider": provider_id, "status": status, "source_url": url, "item_count": 0})
            errors.append({"provider": provider_id, "error": status, "status_code": status_code})
        except (requests.RequestException, TimeoutError, ElementTree.ParseError, ValueError, TypeError, OSError) as exc:
            health.append({"provider": provider_id, "status": "failed", "source_url": url, "item_count": 0})
            errors.append({"provider": provider_id, "error": type(exc).__name__})
    return {"stories": stories[: max(limit, 1) * 2], "source_health": health, "errors": errors, "market": market}
