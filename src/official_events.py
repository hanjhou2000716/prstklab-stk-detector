"""Read-only, first-party sources used as candidates for material-event alerts.

No source headline is treated as investment advice. Each record keeps its
publisher URL and timestamp, then enters the normal event/card/de-duplication
pipeline with current market observations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
import re
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from src.finance_intel_policy import polling_rule, threshold_rule
from src.corporate_event_contract import normalize_corporate_event
from src.intel_contract import normalize_event_record
from src.value_fundamentals import SEC_USER_AGENT, sec_ticker_ciks
from src.value_universe import fetch_taiwan_0050_universe


HEADERS = {"User-Agent": SEC_USER_AGENT}
RECENCY_MINUTES = int(polling_rule("officialEventMaxAgeMinutes"))
TAIPEI = ZoneInfo("Asia/Taipei")

# First-party publishers only. Terms deliberately exclude routine notices so
# the normal official-event monitor does not turn administrative updates into
# Telegram alerts.
SOURCES = (
    {
        "key": "fed", "kind": "rss", "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "source": "Federal Reserve\uff5c\u5b98\u65b9 RSS", "label": "Fed\uff0f\u8ca8\u5e63\u653f\u7b56",
        "terms": ("fomc", "federal funds", "interest rate", "economic projections", "monetary policy"),
    },
    {
        "key": "bls-employment", "kind": "rss", "url": "https://www.bls.gov/feed/empsit.rss",
        "source": "BLS Employment Situation\uff5c\u5b98\u65b9 RSS", "label": "\u7f8e\u570b\u5c31\u696d",
        "terms": ("employment situation", "payroll", "unemployment"),
    },
    {
        "key": "bls-cpi", "kind": "rss", "url": "https://www.bls.gov/feed/cpi.rss",
        "source": "BLS CPI\uff5c\u5b98\u65b9 RSS", "label": "\u7f8e\u570b\u901a\u81a8",
        "terms": ("consumer price", "cpi"),
    },
    {
        "key": "bls-ppi", "kind": "rss", "url": "https://www.bls.gov/feed/ppi.rss",
        "source": "BLS PPI\uff5c\u5b98\u65b9 RSS", "label": "\u7f8e\u570b\u901a\u81a8",
        "terms": ("producer price", "ppi"),
    },
    {
        "key": "eia", "kind": "rss", "url": "https://www.eia.gov/rss/press_rss.xml",
        "source": "EIA\uff5c\u5b98\u65b9 RSS", "label": "\u80fd\u6e90\uff0f\u901a\u81a8",
        "terms": ("crude oil", "petroleum", "natural gas", "weekly petroleum", "energy outlook"),
    },
    {
        "key": "bea", "kind": "rss", "url": "https://apps.bea.gov/rss/rss.xml",
        "source": "BEA\uff5c\u5b98\u65b9\u767c\u5e03", "label": "\u91cd\u5927\u7e3d\u7d93",
        "terms": ("personal income and outlays", "gross domestic product", "pce", "international trade"),
    },
    {
        "key": "taifex", "kind": "html", "url": "https://www.taifex.com.tw/cht/11/pressRelease",
        "source": "\u81fa\u7063\u671f\u8ca8\u4ea4\u6613\u6240\u516c\u544a", "label": "\u53f0\u6307\u671f\uff0f\u69d3\u687f\u98a8\u96aa",
        "terms": ("\u4fdd\u8b49\u91d1", "\u81fa\u80a1\u671f\u8ca8", "\u53f0\u80a1\u671f\u8ca8", "\u76e4\u4e2d\u66ab\u505c", "\u7dca\u6025", "\u4ea4\u6613\u63aa\u65bd"),
    },
    {
        "key": "cbc", "kind": "html", "url": "https://www.cbc.gov.tw/tw/lp-302-1-391-20.html",
        "source": "\u4e2d\u592e\u9280\u884c\u65b0\u805e\u7a3f", "label": "\u53f0\u7063\u5229\u7387\uff0f\u532f\u7387",
        "terms": ("\u7406\u76e3\u4e8b", "\u8ca8\u5e63\u653f\u7b56", "\u653f\u7b56\u5229\u7387", "\u5916\u532f", "\u532f\u7387", "\u91d1\u878d\u7a69\u5b9a"),
    },
    {
        "key": "fsc", "kind": "html", "url": "https://www.fsc.gov.tw/ch/home.jsp?id=640&parentpath=0,7,478,638",
        "source": "\u91d1\u7ba1\u6703\u65b0\u805e\u7a3f", "label": "\u53f0\u7063\u8cc7\u672c\u5e02\u5834\u653f\u7b56",
        "terms": ("\u8cc7\u672c\u5e02\u5834", "\u8b49\u5238\u5e02\u5834", "\u91d1\u878d\u7a69\u5b9a", "\u5e02\u5834\u98a8\u96aa", "\u6709\u50f9\u8b49\u5238"),
    },
    {
        "key": "dgbas", "kind": "html", "url": "https://www.stat.gov.tw/",
        "source": "\u4e3b\u8a08\u7e3d\u8655\u7d71\u8a08\u767c\u5e03", "label": "\u53f0\u7063\u7e3d\u7d93\u6578\u64da",
        "terms": ("\u6d88\u8cbb\u8005\u7269\u50f9", "\u751f\u7522\u8005\u7269\u50f9", "\u570b\u5167\u751f\u7522\u6bdb\u984d", "\u7d93\u6fdf\u6210\u9577", "\u5931\u696d\u7387"),
    },
    {
        "key": "moea", "kind": "html", "url": "https://mnscdn.moea.gov.tw/Mns/dos/bulletin/BulletinQuery.aspx?menu_id=13034",
        "source": "\u7d93\u6fdf\u90e8\u7d71\u8a08\u8655\u767c\u5e03", "label": "\u53f0\u7063\u79d1\u6280\u666f\u6c23",
        "terms": ("\u5916\u92b7\u8a02\u55ae", "\u5de5\u696d\u751f\u7522", "\u88fd\u9020\u696d\u751f\u7522", "\u51fa\u53e3"),
    },
    {
        "key": "ecb", "kind": "rss", "url": "https://www.ecb.europa.eu/rss/press.html",
        "source": "ECB\uff5c\u5b98\u65b9 RSS", "label": "\u6b50\u6d32\u5229\u7387\uff0f\u6d41\u52d5\u6027",
        "terms": ("monetary policy", "interest rate", "liquidity", "financial stability"),
    },
    {
        "key": "white-house", "kind": "html", "url": "https://www.whitehouse.gov/news/",
        "source": "White House\uff5c\u5b98\u65b9\u65b0\u805e", "label": "\u7f8e\u570b\u7e3d\u7d71\uff0f\u5730\u7de3\u653f\u7b56",
        # Keep this focused on foreign-policy and security developments.  The
        # page also contains routine administrative releases that should not
        # enter the emergency-event candidate stream.
        "terms": ("iran", "attack", "strike", "military", "ceasefire", "truce", "sanction", "war", "troops", "hormuz"),
    },
    {
        "key": "cisa", "kind": "rss", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
        "source": "CISA\uff5c\u5b98\u65b9 RSS", "label": "\u8cc7\u5b89\uff0f\u4f9b\u61c9\u93c8",
        "terms": ("known exploited", "ransomware", "supply chain", "critical infrastructure"),
    },
    {
        "key": "who", "kind": "rss", "url": "https://www.who.int/rss-feeds/news-english.xml",
        "source": "WHO\uff5c\u5b98\u65b9 RSS", "label": "\u516c\u5171\u885b\u751f\u98a8\u96aa",
        "terms": ("public health emergency", "outbreak", "pandemic", "novel virus"),
    },
)

TWSE_NEWS_URL = "https://openapi.twse.com.tw/v1/news/newsList"
TWSE_NOTICE_URL = "https://openapi.twse.com.tw/v1/announcement/notice"
TWSE_PUNISH_URL = "https://openapi.twse.com.tw/v1/announcement/punish"
MOPS_DAILY_URL = "https://mops.twse.com.tw/mops/api/t05st02"
MOPS_DAILY_PAGE = "https://mops.twse.com.tw/mops/#/web/t05st02"
TWSE_TERMS = ("\u505c\u6b62\u8cb7\u8ce3", "\u6062\u5fa9\u8cb7\u8ce3", "\u66ab\u505c\u4ea4\u6613", "\u50f9\u683c\u7a69\u5b9a\u63aa\u65bd", "\u7194\u65b7")
MOPS_TERMS = (
    "\u505c\u6b62\u8cb7\u8ce3", "\u6062\u5fa9\u8cb7\u8ce3", "\u66ab\u505c\u4ea4\u6613", "\u5408\u4f75", "\u6536\u8cfc", "\u516c\u958b\u6536\u8cfc",
    "\u91cd\u5927\u707d\u5bb3", "\u706b\u707d", "\u7206\u70b8", "\u7f77\u5de5", "\u7834\u7522", "\u91cd\u6574", "\u4e0b\u5e02",
    "\u8655\u5206\u8cc7\u7522", "\u53d6\u5f97\u8cc7\u7522", "\u6e1b\u8cc7", "\u73fe\u91d1\u589e\u8cc7",
)
@lru_cache(maxsize=1)
def _taiwan_0050_codes() -> frozenset[str]:
    """Fail closed: no company Telegram alert without a current 0050 list."""
    rows, errors = fetch_taiwan_0050_universe()
    if errors:
        return frozenset()
    return frozenset(str(row.get("ticker") or "") for row in rows if str(row.get("ticker") or ""))


def _mops_brief_summary(code: str, name: str, title: str) -> str:
    """Use a classified complete fact instead of truncating a raw MOPS title."""
    categories = (
        ("合併／收購", ("合併", "收購", "公開收購")),
        ("重大災害", ("重大災害", "火災", "爆炸", "罷工")),
        ("財務重整", ("破產", "重整", "下市")),
        ("資本調整", ("減資", "現金增資")),
        ("重大資產", ("處分資產", "取得資產")),
        ("交易措施", ("停止買賣", "恢復買賣", "暫停交易")),
    )
    category = next((label for label, terms in categories if any(term in title for term in terms)), "重大訊息")
    return f"0050｜{code} {name}｜{category}"


# Attention/disposition data is high-volume. Only systemic listed names can
# become a Telegram candidate; all other entries remain available at TWSE.
TWSE_SYSTEMIC_CODES = {"2330", "2317", "2454", "2308", "2303", "2881", "2882", "2884", "2886", "2891"}
SEC_WATCHLIST = ("NVDA", "TSM", "ASML", "AMD", "AVGO")
USGS_SIGNIFICANT_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_hour.geojson"
GDACS_RSS_URL = "https://www.gdacs.org/xml/rss.xml"


def _request(url: str) -> requests.Response:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response
        except requests.HTTPError as error:
            # The policy explicitly forbids retrying rate-limited sources.
            if error.response is not None and error.response.status_code == 429:
                raise
            last_error = error
        except requests.RequestException as error:
            last_error = error
    raise RuntimeError(f"public source unavailable: {url}") from last_error


def _post_json(url: str, payload: dict[str, str]) -> dict[str, Any]:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = requests.post(url, json=payload, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 429:
                raise
            last_error = error
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


def _date_from_text(value: str) -> str | None:
    """Extract a declared Gregorian or ROC release date from page text."""
    iso_match = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", value)
    if iso_match:
        year, month, day = (int(part) for part in iso_match.groups())
    else:
        roc_match = re.search(r"(1[01]\d)[\u5e74/-](\d{1,2})[\u6708/-](\d{1,2})", value)
        if not roc_match:
            return None
        year, month, day = (int(part) for part in roc_match.groups())
        year += 1911
    try:
        return datetime(year, month, day, tzinfo=TAIPEI).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


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
        parent = link.find_parent()
        timestamp = parent.find("time") if parent else None
        released_at = timestamp.get("datetime") if timestamp else None
        if not released_at and parent:
            released_at = _date_from_text(" ".join(parent.stripped_strings))
        results.append((title, href, _iso(released_at)))
    return results


def _rss_links(xml: str, base_url: str) -> list[tuple[str, str, str | None]]:
    soup = BeautifulSoup(xml, "xml")
    results: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for item in soup.find_all("item") + soup.find_all("entry"):
        title = item.find("title")
        link = item.find("link")
        href = (link.get("href") or link.get_text(strip=True)) if link else ""
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
    age = datetime.now(timezone.utc) - published
    # A publisher can be a few minutes ahead, but a future-dated listing must
    # never become an alert candidate.
    return timedelta(minutes=-5) <= age <= timedelta(minutes=RECENCY_MINUTES)


def _source_items(source: dict[str, Any]) -> list[dict[str, str]]:
    response = _request(source["url"])
    links = _rss_links(response.text, source["url"]) if source["kind"] == "rss" else _headline_links(response.text, source["url"])
    for title, url, released_at in links:
        if any(term in title.lower() for term in source["terms"]) and _is_recent_release(released_at):
            return [{
                "title": title, "url": url, "source": source["source"], "short_label": source["label"],
                "relevance": "official", "source_tier": "official", "released_at": released_at,
                "source_key": source["key"], "topic_key": source["key"],
            }]
    return []


def _roc_date(value: str | None) -> str | None:
    raw = str(value or "")
    if len(raw) != 7 or not raw.isdigit():
        return None
    return f"{int(raw[:3]) + 1911:04d}-{raw[3:5]}-{raw[5:]}T00:00:00+00:00"


def _mops_released_at(roc_date: str, clock: str) -> str | None:
    match = re.fullmatch(r"(\d{3})[/-]?(\d{2})[/-]?(\d{2})", roc_date)
    if not match:
        return None
    try:
        published = datetime(
            int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3)),
            int(clock[:2]), int(clock[3:5]), int(clock[6:8]), tzinfo=TAIPEI,
        )
    except (ValueError, IndexError):
        return None
    return published.astimezone(timezone.utc).isoformat()


def _mops_items() -> list[dict[str, str]]:
    """Read current-day MOPS material announcements through its public API."""
    local_now = datetime.now(TAIPEI)
    data = _post_json(MOPS_DAILY_URL, {
        "year": str(local_now.year - 1911), "month": str(local_now.month), "day": str(local_now.day),
    })
    allowed_codes = _taiwan_0050_codes()
    if not allowed_codes:
        return []
    items: list[dict[str, str]] = []
    for row in data.get("result", {}).get("data", []):
        if len(row) < 5:
            continue
        date, clock, code, name, title = (str(value).strip() for value in row[:5])
        if len(code) != 4 or not code.isdigit() or code not in allowed_codes or not any(term in title for term in MOPS_TERMS):
            continue
        released_at = _mops_released_at(date, clock)
        if not _is_recent_release(released_at):
            continue
        items.append({
            "title": f"{code} {name}\uff1a{title}", "url": MOPS_DAILY_PAGE,
            "source": "MOPS \u7576\u65e5\u91cd\u5927\u8a0a\u606f", "short_label": "\u53f0\u80a1\u516c\u53f8\u91cd\u5927\u8a0a\u606f",
            "brief_summary": _mops_brief_summary(code, name, title),
            "relevance": "official", "released_at": released_at or "", "source_key": "mops",
        })
    return items[:2]


def _twse_items() -> list[dict[str, str]]:
    data = _request(TWSE_NEWS_URL).json()
    for row in data:
        title = str(row.get("Title") or "").strip()
        released_at = _roc_date(row.get("Date"))
        if title and any(term in title for term in TWSE_TERMS) and _is_recent_release(released_at):
            return [{
                "title": title, "url": str(row.get("Url") or ""),
                "source": "TWSE OpenAPI\uff5c\u5b98\u65b9\u767c\u5e03", "short_label": "\u53f0\u80a1\u5b98\u65b9\u8a0a\u606f",
                "relevance": "official", "released_at": released_at, "source_key": "twse",
            }]
    return []


def _twse_market_alert_items() -> list[dict[str, str]]:
    """Keep only recent attention/disposition events for systemic names."""
    items: list[dict[str, str]] = []
    for url, category in ((TWSE_NOTICE_URL, "\u6ce8\u610f\u4ea4\u6613"), (TWSE_PUNISH_URL, "\u8655\u7f6e\u80a1\u7968")):
        for row in _request(url).json():
            code = str(row.get("Code") or "").strip()
            released_at = _roc_date(row.get("Date"))
            if (
                len(code) != 4 or not code.isdigit() or code not in TWSE_SYSTEMIC_CODES
                or not _is_recent_release(released_at)
            ):
                continue
            name = str(row.get("Name") or "").strip()
            detail = str(row.get("ReasonsOfDisposition") or row.get("TradingInfoForAttention") or "").strip()
            items.append({
                "title": f"{category}\uff1a{code} {name} {detail}".strip(), "url": url,
                "source": "TWSE OpenAPI \u5e02\u5834\u7570\u5e38\u8cc7\u8a0a", "short_label": f"\u53f0\u80a1{category}",
                "relevance": "official", "released_at": released_at or "", "source_key": "twse_market_alert",
            })
            break
    return items


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
            items.append({
                "title": f"{ticker} SEC {form} \u8ca1\u52d9\u7533\u5831",
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}",
                "source": "SEC EDGAR\uff5c\u5b98\u65b9\u7533\u5831", "short_label": "\u534a\u5c0e\u9ad4\u8ca1\u5831",
                "relevance": "official", "released_at": released_at, "source_key": "sec",
            })
            break
    return items


def _gdacs_items() -> list[dict[str, str]]:
    """Keep only GDACS Red alerts, never ordinary global disaster headlines."""
    response = _request(GDACS_RSS_URL)
    soup = BeautifulSoup(response.text, "xml")
    items: list[dict[str, str]] = []
    for entry in soup.find_all("item"):
        title_node = entry.find("title")
        link_node = entry.find("link")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        raw = entry.get_text(" ", strip=True).lower()
        published = entry.find("pubDate") or entry.find("published") or entry.find("updated")
        released_at = _iso(published.get_text(strip=True) if published else None)
        material_hazards = ("earthquake", "tsunami", "cyclone", "flood", "volcano")
        hazard = next((value for value in material_hazards if value in raw), None)
        if "red" not in raw or hazard is None or not _is_recent_release(released_at):
            continue
        items.append({
            "title": f"GDACS Red {hazard} alert", "url": link_node.get_text(strip=True) if link_node else GDACS_RSS_URL,
            "brief_summary": f"GDACS 紅色{hazard}災害警示",
            "source": "GDACS\uff5c\u516c\u958b\u707d\u5bb3\u8b66\u793a", "short_label": "\u9ed1\u5929\u9d5d\uff0f\u91cd\u5927\u707d\u5bb3",
            "relevance": "official", "source_tier": "official", "released_at": released_at or "",
            "source_key": "gdacs", "topic_key": "gdacs", "importance": "high-risk",
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
        relevant_region = any(word in place.lower() for word in ("japan", "taiwan", "philippines", "korea"))
        tsunami = bool(properties.get("tsunami"))
        minimum = float(threshold_rule("usgsMagnitude"))
        if (
            not isinstance(magnitude, (int, float))
            or not _is_recent_release(released_at)
            or (magnitude < minimum and not tsunami and not (relevant_region and magnitude >= 6))
        ):
            continue
        items.append({
            "title": f"USGS M{magnitude:.1f} \u5730\u9707\uff1a{place}", "url": str(properties.get("url") or ""),
            "source": "USGS\uff5c\u5b98\u65b9\u5373\u6642\u5730\u9707\u8cc7\u6599", "short_label": "\u9ed1\u5929\u9d5d\uff0f\u5730\u7de3",
            "relevance": "official", "source_tier": "official", "released_at": released_at,
            "brief_summary": f"USGS M{magnitude:.1f} 地震：{place}",
            "source_key": "usgs", "topic_key": "usgs", "importance": "high-risk",
        })
    return items


def fetch_official_events() -> dict[str, Any]:
    """Fetch bounded first-party candidates with per-source health metadata."""
    items: list[dict[str, str]] = []
    errors: list[str] = []
    checked_at = datetime.now(timezone.utc).isoformat()
    source_health: list[dict[str, Any]] = []

    def collect(key: str, label: str, url: str, fetcher: Any) -> None:
        try:
            normalizer = normalize_corporate_event if key in {"mops", "twse", "twse_market", "sec"} else normalize_event_record
            fetched = [normalizer(item, fetched_at=checked_at) for item in fetcher()]
            items.extend(fetched)
            source_health.append({
                "key": key, "label": label, "source_tier": "official",
                "source_url": url, "status": "healthy", "checked_at": checked_at,
                "item_count": len(fetched), "latest_published_at": max(
                    (str(item.get("published_at") or "") for item in fetched), default=None
                ), "data_gap": None,
            })
        except Exception as exc:
            errors.append(f"{key.upper()} official source temporarily unavailable")
            source_health.append({
                "key": key, "label": label, "source_tier": "official",
                "source_url": url, "status": "failed", "checked_at": checked_at,
                "item_count": 0, "latest_published_at": None,
                "data_gap": type(exc).__name__,
            })

    for source in SOURCES:
        collect(source["key"], source["source"], source["url"], lambda source=source: _source_items(source))
    for key, fetcher in (
        ("MOPS", _mops_items),
        ("TWSE", _twse_items),
        ("TWSE_MARKET", _twse_market_alert_items),
        ("GDACS", _gdacs_items),
        ("SEC", _sec_items),
        ("USGS", _usgs_items),
    ):
        collect(key.lower(), key, "", fetcher)
    items.sort(key=lambda item: item.get("released_at") or "", reverse=True)
    return {
        "items": items[:6], "errors": errors, "checked_at": checked_at,
        "source_health": source_health,
    }
