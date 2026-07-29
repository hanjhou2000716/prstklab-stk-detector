"""Read-only, first-party sources used as candidates for material-event alerts.

No source headline is treated as investment advice.  Each record keeps its
publisher URL and timestamp, then enters the normal event/card/de-duplication
pipeline with current market observations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.value_fundamentals import SEC_USER_AGENT, sec_ticker_ciks


HEADERS = {"User-Agent": SEC_USER_AGENT}
RECENCY_HOURS = 72
SOURCES = (
    {
        "key": "fed", "kind": "rss", "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "source": "Federal Reserve｜官方 RSS", "label": "Fed／貨幣政策",
        "terms": ("fomc", "federal funds", "interest rate", "economic projections", "monetary policy"),
    },
    {
        "key": "bls", "kind": "rss", "url": "https://www.bls.gov/feed/bls_latest.rss",
        "source": "BLS｜官方 RSS", "label": "重大總經",
        "terms": ("consumer price index", "employment situation", "nonfarm", "producer price index", "import and export price"),
    },
    {
        "key": "eia", "kind": "rss", "url": "https://www.eia.gov/rss/press_rss.xml",
        "source": "EIA｜官方 RSS", "label": "能源／通膨",
        "terms": ("crude oil", "petroleum", "natural gas", "weekly petroleum", "energy outlook"),
    },
    {
        "key": "bea", "kind": "html", "url": "https://www.bea.gov/news/current-releases",
        "source": "BEA｜官方發布", "label": "重大總經",
        "terms": ("personal income and outlays", "gross domestic product"),
    },
)
TWSE_NEWS_URL = "https://openapi.twse.com.tw/v1/news/newsList"
# Avoid generic words such as "市場" or "指數": they appear in routine listing
# notices and would turn administrative exchange news into a false alert.
TWSE_TERMS = ("重大訊息", "停止買賣", "暫停交易", "台積電", "半導體", "價格穩定措施", "熔斷")
SEC_WATCHLIST = ("NVDA", "TSM", "ASML", "AMD", "AVGO")
USGS_SIGNIFICANT_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_hour.geojson"


def _request(url: str) -> requests.Response:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
    raise RuntimeError(f"public source unavailable: {url}") from last_error


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            timestamp = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


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
        results.append((title, href, _iso(released_at)))
    return results


def _rss_links(xml: str, base_url: str) -> list[tuple[str, str, str | None]]:
    soup = BeautifulSoup(xml, "xml")
    results: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for item in soup.find_all("item") + soup.find_all("entry"):
        title = item.find("title")
        link = item.find("link")
        href = ""
        if link:
            href = link.get("href") or link.get_text(strip=True)
        title_text = title.get_text(" ", strip=True) if title else ""
        timestamp = item.find("pubDate") or item.find("published") or item.find("updated")
        absolute_url = urljoin(base_url, href)
        if not title_text or not absolute_url.startswith("https://") or absolute_url in seen:
            continue
        seen.add(absolute_url)
        results.append((title_text, absolute_url, _iso(timestamp.get_text(strip=True) if timestamp else None)))
    return results


def _is_recent_release(released_at: str | None) -> bool:
    if not released_at:
        return False
    try:
        published = datetime.fromisoformat(released_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - published <= timedelta(hours=RECENCY_HOURS)


def _source_items(source: dict[str, Any]) -> list[dict[str, str]]:
    response = _request(source["url"])
    links = _rss_links(response.text, source["url"]) if source["kind"] == "rss" else _headline_links(response.text, source["url"])
    for title, url, released_at in links:
        if any(term in title.lower() for term in source["terms"]) and _is_recent_release(released_at):
            return [{
                "title": title, "url": url, "source": source["source"], "short_label": source["label"],
                "relevance": "official", "released_at": released_at, "source_key": source["key"],
            }]
    return []


def _roc_date(value: str | None) -> str | None:
    raw = str(value or "")
    if len(raw) != 7 or not raw.isdigit():
        return None
    return f"{int(raw[:3]) + 1911:04d}-{raw[3:5]}-{raw[5:]}T00:00:00+00:00"


def _twse_items() -> list[dict[str, str]]:
    data = _request(TWSE_NEWS_URL).json()
    for row in data:
        title = str(row.get("Title") or "").strip()
        released_at = _roc_date(row.get("Date"))
        if title and any(term in title for term in TWSE_TERMS) and _is_recent_release(released_at):
            return [{
                "title": title, "url": str(row.get("Url") or ""), "source": "TWSE OpenAPI｜官方發布",
                "short_label": "台股官方訊息", "relevance": "official", "released_at": released_at, "source_key": "twse",
            }]
    return []


def _sec_items() -> list[dict[str, str]]:
    session = requests.Session()
    session.headers.update(HEADERS)
    ciks = sec_ticker_ciks(session)
    items: list[dict[str, str]] = []
    for ticker in SEC_WATCHLIST:
        cik = ciks.get(ticker)
        if cik is None:
            continue
        response = session.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", timeout=20)
        response.raise_for_status()
        recent = response.json().get("filings", {}).get("recent", {})
        for index, form in enumerate(recent.get("form", [])):
            filing_date = str(recent.get("filingDate", [""])[index])
            released_at = _iso(f"{filing_date}T00:00:00+00:00")
            if not _is_recent_release(released_at) or form not in {"10-K", "10-Q", "8-K", "6-K"}:
                continue
            item_codes = str(recent.get("items", [""])[index])
            if form in {"8-K", "6-K"} and "2.02" not in item_codes:
                continue
            accession = str(recent.get("accessionNumber", [""])[index]).replace("-", "")
            document = str(recent.get("primaryDocument", [""])[index])
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
            items.append({
                "title": f"{ticker} SEC {form} 財務申報", "url": url, "source": "SEC EDGAR｜官方申報",
                "short_label": "半導體財報", "relevance": "official", "released_at": released_at, "source_key": "sec",
            })
            break
    return items


def _usgs_items() -> list[dict[str, str]]:
    data = _request(USGS_SIGNIFICANT_URL).json()
    items: list[dict[str, str]] = []
    for feature in data.get("features", []):
        properties = feature.get("properties") or {}
        magnitude = properties.get("mag")
        occurred = properties.get("time")
        released_at = datetime.fromtimestamp(float(occurred) / 1000, tz=timezone.utc).isoformat() if occurred else None
        place = str(properties.get("place") or "")
        # M7 globally, or M6 in the Taiwan/Japan supply-chain region.
        relevant_region = any(word in place.lower() for word in ("japan", "taiwan", "philippines", "korea"))
        if not isinstance(magnitude, (int, float)) or not _is_recent_release(released_at) or (magnitude < 7 and not (relevant_region and magnitude >= 6)):
            continue
        items.append({
            "title": f"USGS M{magnitude:.1f} 地震：{place}", "url": str(properties.get("url") or ""),
            "source": "USGS｜官方即時地震資料", "short_label": "黑天鵝／地緣", "relevance": "official",
            "released_at": released_at, "source_key": "usgs",
        })
    return items


def fetch_official_events() -> dict[str, Any]:
    """Fetch bounded first-party candidates; failures never fabricate a release."""
    items: list[dict[str, str]] = []
    errors: list[str] = []
    for source in SOURCES:
        try:
            items.extend(_source_items(source))
        except Exception:
            errors.append(f"{source['key'].upper()} 官方來源暫時無法取得")
    for key, fetcher in (("TWSE", _twse_items), ("SEC", _sec_items), ("USGS", _usgs_items)):
        try:
            items.extend(fetcher())
        except Exception:
            errors.append(f"{key} 官方來源暫時無法取得")
    items.sort(key=lambda item: item.get("released_at") or "", reverse=True)
    return {"items": items[:6], "errors": errors}
