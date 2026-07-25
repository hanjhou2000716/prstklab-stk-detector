"""Read-only, first-party macro release sources for material-event context."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)"}
SOURCES = (
    {
        "key": "fed",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
        "source": "Federal Reserve｜官方發布",
        "label": "Fed／貨幣政策",
        "terms": ("fomc", "federal funds", "interest rate", "economic projections", "federal reserve issues"),
    },
    {
        "key": "bls",
        "url": "https://www.bls.gov/bls/newsrels.htm",
        "source": "BLS｜官方發布",
        "label": "重大總經",
        "terms": ("consumer price index", "employment situation", "nonfarm", "producer price index"),
    },
    {
        "key": "bea",
        "url": "https://www.bea.gov/news/current-releases",
        "source": "BEA｜官方發布",
        "label": "重大總經",
        "terms": ("personal income and outlays", "gross domestic product"),
    },
)


def _headline_links(html: str, base_url: str) -> list[tuple[str, str, str | None]]:
    """Return de-duplicated visible links without copying article bodies."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        title = " ".join(link.stripped_strings)
        href = urljoin(base_url, link.get("href", ""))
        if not title or not href.startswith("https://") or href in seen:
            continue
        seen.add(href)
        timestamp = link.find_parent().find("time") if link.find_parent() else None
        released_at = timestamp.get("datetime") if timestamp else None
        results.append((title, href, released_at))
    return results


def _is_recent_release(released_at: str | None) -> bool:
    """Do not turn an older official release into a current market event."""
    if not released_at:
        return False
    try:
        published = datetime.fromisoformat(released_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - published <= timedelta(hours=72)


def fetch_official_events() -> dict[str, Any]:
    """Fetch a bounded list of first-party Fed, BLS and BEA release headlines."""
    items: list[dict[str, str]] = []
    errors: list[str] = []
    for source in SOURCES:
        try:
            response = requests.get(source["url"], headers=HEADERS, timeout=15)
            response.raise_for_status()
            for title, url, released_at in _headline_links(response.text, source["url"]):
                if any(term in title.lower() for term in source["terms"]) and _is_recent_release(released_at):
                    items.append({
                        "title": title,
                        "url": url,
                        "source": source["source"],
                        "short_label": source["label"],
                        "relevance": "official",
                        "released_at": released_at,
                    })
                    break
        except Exception:
            errors.append(f"{source['key'].upper()} 官方發布暫時無法取得")
    return {"items": items, "errors": errors}
