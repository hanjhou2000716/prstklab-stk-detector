"""Public risk indicators and holding-related news for the dashboard."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import requests

from src.taiwan_macro_fgi import calculate_taiwan_macro_fgi

CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
TAIFEX_VIX_INDEX_URL = "https://www.taifex.com.tw/cht/7/vixMinNew"
TAIFEX_VIX_DATA_URL = "https://www.taifex.com.tw/cht/7/getVixData?filesname={date}"
TAIFEX_VIX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteListVIX"
ANUE_CATEGORY_URLS = {
    "taiwan": "https://news.cnyes.com/news/cat/tw_stock_news",
    "us": "https://news.cnyes.com/news/cat/us_stock",
}
NEWS_RSS_QUERIES = {
    "taiwan": "台股 OR 台積電 OR 半導體",
    "us": "美股 OR Nasdaq OR Nvidia OR Federal Reserve",
}
NEWS_TERMS = {
    "taiwan": ("006208", "00685L", "2330", "台積電", "台股", "半導體"),
    "us": ("QQQM", "QLD", "TSM", "NVDA", "NVIDIA", "輝達", "美股", "那斯達克"),
}
# Canonical market-specific queries.  These assignments intentionally follow
# the legacy constants above so a historical encoding-corrupted checkout is
# repaired at import time without changing the public module API.
NEWS_RSS_QUERIES = {
    "taiwan": "\u53f0\u80a1 OR \u53f0\u7a4d\u96fb OR \u53f0\u6307 OR \u4e0a\u5e02\u516c\u53f8",
    "us": "Nasdaq OR \"S&P 500\" OR \"Federal Reserve\" OR Nvidia OR \"US stocks\"",
}
NEWS_TERMS = {
    "taiwan": (
        "006208", "00685L", "2330", "\u53f0\u80a1", "\u53f0\u7a4d\u96fb",
        "\u53f0\u6307", "\u52a0\u6b0a\u6307\u6578", "\u4e0a\u5e02",
    ),
    "us": (
        "QQQM", "QLD", "TSM", "NVDA", "NVIDIA", "Nasdaq", "S&P 500",
        "Federal Reserve", "Fed", "FOMC", "US stocks",
    ),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)"}
NEWS_CACHE_MAX_AGE_MINUTES = int(os.getenv("NEWS_CACHE_MAX_AGE_MINUTES", "360"))

# A provider can return a valid HTTP response containing the wrong regional
# feed.  These explicit Taiwan terms are used to keep the US news tab clean;
# broad topics such as gold or semiconductors are deliberately not blocked.
TAIWAN_NEWS_TERMS = (
    "\u53f0\u80a1", "\u53f0\u7a4d\u96fb", "\u6ac3\u8cb7", "\u52a0\u6b0a\u6307\u6578",
    "\u570b\u6cf0", "\u529b\u7a4d\u96fb", "\u53f0\u6307", "\u53f0\u7063\u80a1\u5e02",
    "0050", "006208", "00878", "2330.tw", "twse", "taiex", "tpex", "twii",
)

# Market routing is intentionally evidence-based rather than driven only by
# the provider's category.  A regional feed can return a shared shell or a
# headline from the other market, so both title and summary are classified
# before an item is cached or rendered.  Keep aliases in Unicode escapes: this
# module has historically been edited under mixed code pages and the escapes
# prevent a deployment from silently corrupting matching terms.
_TAIWAN_MARKET_TERMS = (
    "\u53f0\u80a1", "\u53f0\u7063\u80a1\u5e02", "\u53f0\u6e7e\u80a1\u5e02", "\u53f0\u7a4d\u96fb",
    "\u53f0\u79ef\u7535", "\u53f0\u6307", "\u52a0\u6b0a\u6307\u6578", "\u52a0\u6743\u6307\u6570",
    "\u6ac3\u8cb7", "\u67dc\u8cb7", "\u4e0a\u6ac3", "\u4e0a\u67dc", "twse", "tpex", "taiex", "twii",
    "taiwan", "\u53f0\u7063", "\u53f0\u6e7e", "\u8cf4\u6e05\u5fb7", "\u8d56\u6e05\u5fb7", "lai ching-te",
    "0050", "006208", "00878", "2330.tw", "\u806f\u767c\u79d1", "\u8054\u53d1\u79d1",
)
_US_MARKET_TERMS = (
    "\u7f8e\u80a1", "\u7f8e\u570b", "\u7f8e\u56fd", "us stocks", "u.s. stocks", "nasdaq", "s&p 500",
    "sp500", "s&p500", "dow jones", "\u8cbb\u534a", "\u8d39\u534a", "sox", "nyse", "sec",
    "federal reserve", "fed", "fomc", "bls", "cpi", "pce", "\u806f\u6e96\u6703", "\u8054\u51c6\u4f1a",
    "\u767d\u5bae", "white house", "\u5ddd\u666e", "\u5ddd\u666e", "trump", "donald trump",
    "\u7279\u6717\u666e", "\u7279\u6717\u666e", "bessent", "nvidia", "nvda", "amd", "apple",
    "microsoft", "amazon", "meta", "alphabet", "tsm", "nasdaq-100",
)
_GLOBAL_EVENT_TERMS = (
    "\u4f0a\u6717", "iran", "\u4ee5\u8272\u5217", "israel", "\u6230\u722d", "\u6218\u4e89", "war", "\u505c\u706b",
    "ceasefire", "\u5236\u88c1", "sanctions", "\u8377\u59c6\u8332", "hormuz", "\u822a\u904b", "shipping",
    "\u539f\u6cb9", "\u77f3\u6cb9", "oil", "brent", "wti", "\u9ec3\u91d1", "\u9ec4\u91d1", "gold",
    "earthquake", "\u5730\u9707", "tsunami", "\u9ed1\u5929\u9d5d", "\u91cd\u5927\u707d\u5bb3",
)


def _news_text(story: dict[str, str]) -> str:
    """Build a normalized haystack for deterministic market classification."""
    fields = (
        story.get("title", ""), story.get("summary", ""),
        story.get("description", ""), story.get("source", ""), story.get("url", ""),
    )
    text = " ".join(str(value) for value in fields if value)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def _term_matches(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.casefold() in text]


def classify_news_market(story: dict[str, str]) -> dict[str, Any]:
    """Return market scope and matched evidence for a news story.

    ``global`` and ``cross_market`` stories may legitimately appear in both
    regional tabs.  A story with only US evidence is never allowed into the
    Taiwan tab (and vice versa); an unclassified story is retained only as a
    disclosed fallback so an outage cannot be mistaken for a regional match.
    """
    text = _news_text(story)
    taiwan = _term_matches(text, _TAIWAN_MARKET_TERMS)
    us = _term_matches(text, _US_MARKET_TERMS)
    global_terms = _term_matches(text, _GLOBAL_EVENT_TERMS)
    if taiwan and us:
        scope = "cross_market"
    elif taiwan:
        scope = "taiwan"
    elif us:
        scope = "us"
    elif global_terms:
        scope = "global"
    else:
        scope = "unclassified"
    return {
        "market_scope": scope,
        "taiwan_matches": taiwan,
        "us_matches": us,
        "global_matches": global_terms,
        "classification_status": "matched" if scope != "unclassified" else "unclassified",
        "routing_evidence": {
            "title_summary_scanned": True,
            "matched_term_count": len(taiwan) + len(us) + len(global_terms),
            "source_market_hint": story.get("market") or story.get("category"),
        },
    }


def _news_cache_path() -> Path | None:
    """Return the optional durable cache path configured by a workflow."""
    value = os.getenv("NEWS_CACHE_PATH", "").strip()
    return Path(value) if value else None


def _load_news_cache() -> dict[str, Any]:
    path = _news_cache_path()
    if path is None or not path.exists():
        return {"schema": 1, "markets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"schema": 1, "markets": {}}
    except (OSError, json.JSONDecodeError):
        return {"schema": 1, "markets": {}}


def _save_news_cache(cache: dict[str, Any]) -> None:
    path = _news_cache_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # News delivery must never fail merely because the optional cache is read-only.
        return


def _recent_cached_stories(cache: dict[str, Any], market: str) -> list[dict[str, Any]]:
    entry = (cache.get("markets") or {}).get(market)
    if not isinstance(entry, dict) or not isinstance(entry.get("stories"), list):
        return []
    try:
        fetched_at = datetime.fromisoformat(str(entry.get("fetched_at", "")))
        if datetime.now().astimezone() - fetched_at.astimezone() > timedelta(minutes=NEWS_CACHE_MAX_AGE_MINUTES):
            return []
    except (TypeError, ValueError):
        return []
    return [dict(item, stale_used=True) for item in entry["stories"] if isinstance(item, dict)]


def sentiment_label(score: float | None) -> str:
    """Classify the fixed 0–100 fear/greed scale without an action recommendation."""
    if score is None:
        return "資料暫時無法取得"
    if score < 10:
        return "極度恐慌"
    if score < 25:
        return "恐慌"
    if score <= 50:
        return "中立／偏恐慌"
    if score <= 75:
        return "貪婪"
    return "極度貪婪"


def vix_stage(value: float | None, percentile: float | None = None) -> str:
    """Classify volatility separately from the fear/greed sentiment score."""
    if value is None and percentile is None:
        return "波動階段暫時無法取得"
    if percentile is None:
        assert value is not None
        number = float(value)
        if number < 12:
            return "極度樂觀"
        if number < 16:
            return "樂觀"
        if number < 22:
            return "中立"
        if number < 30:
            return "恐慌"
        return "極度恐慌"
    if percentile <= 10:
        return "極度樂觀"
    if percentile <= 30:
        return "樂觀"
    if percentile <= 70:
        return "中立"
    if percentile <= 90:
        return "恐慌"
    return "極度恐慌"


def _latest_close(symbol: str) -> dict[str, Any]:
    """Fetch the latest public close for a volatility index."""
    import yfinance as yf

    history = yf.download(
        symbol, period="1y", interval="1d", auto_adjust=False,
        progress=False, threads=False,
    )
    close = history["Close"]
    if getattr(close, "ndim", 1) > 1:
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.empty:
        raise ValueError("沒有可用的收盤資料。")
    current = float(close.iloc[-1])
    previous = float(close.iloc[-2]) if len(close) >= 2 else None
    if previous in (None, 0):
        change_percent = None
    else:
        assert previous is not None
        change_percent = round((current / previous - 1) * 100, 2)
    window = close.tail(252)
    percentile = round(float((window <= current).sum() / len(window) * 100), 1) if len(window) else None
    return {
        "value": round(current, 2),
        "change_percent": change_percent,
        "percentile": percentile,
        "stage": vix_stage(current, percentile),
        "date": close.index[-1].date().isoformat(),
        "source_label": "Yahoo Finance",
        "fetched_at": datetime.now().astimezone().isoformat(),
        "history_points": int(len(window)),
        "percentile_as_of": close.index[-1].date().isoformat(),
        "percentile_status": "available" if percentile is not None else "unavailable",
        "stage_basis": "historical_percentile" if percentile is not None else "absolute_level_fallback",
        "freshness_state": "daily_close",
    }


def _parse_taifex_vix_file(content: bytes) -> dict[str, Any]:
    """Read the final intraday observation from a TAIFEX VIX download."""
    text = content.decode("big5", errors="replace")
    for line in reversed(text.splitlines()):
        fields = line.split()
        if len(fields) < 3 or not re.fullmatch(r"\d{8}", fields[0]):
            continue
        try:
            value = float(fields[-1])
        except ValueError:
            continue
        return {
            "value": round(value, 2),
            "date": datetime.strptime(fields[0], "%Y%m%d").date().isoformat(),
            "source_label": "臺灣期貨交易所",
            "percentile": None,
            "stage": vix_stage(value),
            "fetched_at": datetime.now().astimezone().isoformat(),
            "history_points": 0,
            "percentile_as_of": None,
            "percentile_status": "unavailable",
            "stage_basis": "absolute_level_fallback",
            "freshness_state": "daily_close",
        }
    raise ValueError("臺指波動率檔案沒有可用數值。")


def fetch_taifex_vix() -> dict[str, Any]:
    """Use TAIFEX's public VIX download as a fallback for ``^VIXTWN``."""
    index = requests.get(TAIFEX_VIX_INDEX_URL, headers=HEADERS, timeout=15)
    index.raise_for_status()
    dates = list(dict.fromkeys(re.findall(r"getVixData\?filesname=(\d{8})", index.text)))
    if not dates:
        raise ValueError("期交所未提供可下載的臺指波動率檔案。")

    def download(date: str) -> dict[str, Any]:
        response = requests.get(TAIFEX_VIX_DATA_URL.format(date=date), headers=HEADERS, timeout=15)
        response.raise_for_status()
        return _parse_taifex_vix_file(response.content)

    latest = download(dates[0])
    if len(dates) > 1:
        previous = download(dates[1])
        latest["change_percent"] = (
            None if previous["value"] == 0 else round((latest["value"] / previous["value"] - 1) * 100, 2)
        )
    else:
        latest["change_percent"] = None
    return latest


def fetch_taifex_vix_quote() -> dict[str, Any]:
    """Fetch current Taiwan VIX from TAIFEX's official MIS quote endpoint.

    TAIFEX's former download page no longer exposes stable file links. This
    endpoint is the public data source used by its volatility quote page and
    provides the latest index, reference price, and quote date.
    """
    response = requests.post(
        TAIFEX_VIX_QUOTE_URL,
        json={"SortColumn": "", "AscDesc": "A"},
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    quotes = response.json().get("RtData", {}).get("QuoteList", [])
    if not quotes:
        raise ValueError("TAIFEX did not return a Taiwan VIX quote.")

    quote = next((item for item in quotes if item.get("SymbolID") == "TAIWANVIX"), quotes[0])
    value = float(quote["CLastPrice"])
    reference = float(quote["CRefPrice"])
    quote_date = datetime.strptime(str(quote["CDate"]), "%Y%m%d").date().isoformat()
    change_percent = None if reference == 0 else round((value / reference - 1) * 100, 2)
    return {
        "value": round(value, 2),
        "date": quote_date,
        "change_percent": change_percent,
        # The official live endpoint does not publish enough history to compute
        # a percentile. Keep this explicit rather than manufacturing one.
        "percentile": None,
        "stage": vix_stage(value),
        "source_label": "TAIFEX",
        "source_url": "https://mis.taifex.com.tw/futures/VolatilityQuotes/",
        "fetched_at": datetime.now().astimezone().isoformat(),
        "history_points": 0,
        "percentile_as_of": None,
        "percentile_status": "unavailable",
        "stage_basis": "absolute_level_fallback",
        "freshness_state": "intraday",
    }


def fetch_cnn_fear_greed() -> dict[str, Any]:
    """Fetch CNN's public Fear & Greed reading; never return a cached value."""
    response = requests.get(CNN_FEAR_GREED_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()
    payload = response.json()["fear_and_greed"]
    score = round(float(payload["score"]), 1)
    return {
        "score": score,
        "label": sentiment_label(score),
        "source_label": "CNN Fear & Greed",
        "source_url": "https://www.cnn.com/markets/fear-and-greed",
        "updated_at": payload.get("timestamp"),
    }


def _market_risk(
    label: str,
    vix_symbol: str,
    sentiment: dict[str, Any] | None = None,
    fallback: Any | None = None,
) -> dict[str, Any]:
    """Build a transparent market risk card from fresh public indicators."""
    result: dict[str, Any] = {"label": label, "sentiment": sentiment, "vix": None, "errors": []}
    try:
        result["vix"] = _latest_close(vix_symbol)
    except Exception:
        try:
            result["vix"] = fallback() if fallback else None
        except Exception:
            result["vix"] = None
        if result["vix"] is None:
            result["errors"].append("波動率資料暫時無法取得")
    if sentiment is None:
        result["summary"] = "波動率觀察"
    else:
        result["summary"] = f"情緒：{sentiment['label']}"
    return result


def build_risk_snapshot() -> dict[str, Any]:
    """Collect fresh risk data. A failed provider is explicitly disclosed."""
    try:
        us_sentiment = fetch_cnn_fear_greed()
    except Exception:
        us_sentiment = {
            "score": None,
            "label": "資料暫時無法取得",
            "source_label": "CNN Fear & Greed",
            "source_url": "https://www.cnn.com/markets/fear-and-greed",
            "updated_at": None,
        }
    us = _market_risk("美股", "^VIX", us_sentiment)
    try:
        taiwan_sentiment = calculate_taiwan_macro_fgi()
    except Exception:
        # Never substitute an old score. The Mini App will say explicitly that
        # this particular public source could not be refreshed.
        taiwan_sentiment = {
            "score": None,
            "label": "資料暫時無法取得",
            "source_label": "TAIEX Macro FGI",
            "date": None,
            "index_level": None,
            "sub_scores": {},
        }
    taiwan = _market_risk("台股", "^VIXTWN", taiwan_sentiment, fallback=fetch_taifex_vix_quote)
    if us_sentiment["score"] is None:
        us["errors"].append("美股情緒資料暫時無法取得")
    if taiwan_sentiment["score"] is None:
        taiwan["errors"].append("台股 Macro FGI 資料暫時無法取得")
    return {
        "notice": "情緒與波動率僅供市場風險觀察，不構成投資建議。",
        "taiwan": taiwan,
        "us": us,
    }


def _news_from_html(html: str, market: str, limit: int = 5) -> list[dict[str, str]]:
    """Extract holding-related headlines, falling back to disclosed market focus."""
    from bs4 import BeautifulSoup

    terms = tuple(term.lower() for term in NEWS_TERMS[market])
    soup = BeautifulSoup(html, "html.parser")
    related: list[dict[str, str]] = []
    market_focus: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in soup.select('a[href^="/news/id/"]'):
        href = str(link.get("href", ""))
        title = " ".join(link.stripped_strings)
        if not title or href in seen:
            continue
        seen.add(href)
        story = {"title": title, "url": f"https://news.cnyes.com{href}"}
        if any(term in title.lower() for term in terms):
            related.append({**story, "source": "鉅亨網｜持股關聯", "relevance": "holding"})
        else:
            market_focus.append({**story, "source": "鉅亨網｜市場焦點", "relevance": "market"})
        if len(related) >= limit:
            break
    if related:
        return related[:limit] + market_focus[: max(0, limit - len(related))]
    return market_focus[:limit]


def fetch_market_news(market: str) -> list[dict[str, str]]:
    """Fetch up to five relevant public Anue headlines for one market."""
    response = requests.get(ANUE_CATEGORY_URLS[market], headers=HEADERS, timeout=15)
    response.raise_for_status()
    return _news_from_html(response.text, market)


def _market_news_rss_url(market: str) -> str:
    """Build a market-specific Google News RSS discovery URL.

    This is a discovery fallback only.  It is deliberately queried with a
    different vocabulary for each tab so a provider returning a shared HTML
    shell cannot make Taiwan and US panels display the same stories.
    """
    if market == "us":
        params = {
            "q": "Nasdaq OR S&P 500 OR Federal Reserve OR Nvidia OR US stocks",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
    else:
        params = {
            "q": NEWS_RSS_QUERIES[market],
            "hl": "zh-TW",
            "gl": "TW",
            "ceid": "TW:zh-Hant",
        }
    return "https://news.google.com/rss/search?" + urlencode(params)


def _news_from_rss(xml: str, market: str, limit: int = 5) -> list[dict[str, str]]:
    """Extract a bounded list of market-specific Google News RSS stories."""
    root = ElementTree.fromstring(xml)
    stories: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url or url in seen:
            continue
        seen.add(url)
        stories.append({
            "title": title,
            "url": url,
            "source": "Google News｜台股線索" if market == "taiwan" else "Google News｜美股線索",
            "relevance": "market",
        })
        if len(stories) >= limit:
            break
    return stories


def fetch_market_news_fallback(market: str) -> list[dict[str, str]]:
    """Fetch a category-specific discovery fallback when the primary feeds collide."""
    response = requests.get(_market_news_rss_url(market), headers=HEADERS, timeout=15)
    response.raise_for_status()
    return _news_from_rss(response.text, market)


def _filter_market_news(stories: list[dict[str, str]], market: str) -> list[dict[str, str]]:
    """Reject cross-market headlines before they reach the cache or UI.

    URL collision detection cannot catch two different URLs copied from the
    same regional feed.  Classify the complete story before accepting it so a
    Taiwan card cannot contain a Fed-only headline and a US card cannot contain
    a Taiwan-politics-only headline.  Global/cross-market stories remain
    eligible for both tabs, while the classification evidence is retained for
    the Mini App audit trail.
    """
    valid: list[dict[str, str]] = []
    for story in stories:
        title = str(story.get("title", "")).strip()
        url = str(story.get("url", "")).strip()
        if not title or not url:
            continue
        enriched = dict(story)
        classification = classify_news_market(enriched)
        scope = classification["market_scope"]
        enriched["market_classification"] = classification
        # Unknown headlines have no auditable market scope.  Keeping them in
        # both tabs creates the exact false-routing failure this filter is
        # designed to prevent, so fail closed and let the source-health card
        # distinguish an empty scan from a provider failure.
        if scope == "unclassified":
            continue
        if scope in {"taiwan", "us"} and scope != market:
            continue
        enriched.update(classification)
        valid.append(enriched)
    return valid[:5]


def _news_identity(stories: list[dict[str, str]]) -> frozenset[str]:
    """Return order-independent article identities for collision detection."""
    return frozenset(story.get("url") or story.get("title", "") for story in stories)


def _news_lists_collide(left: list[dict[str, str]], right: list[dict[str, str]]) -> bool:
    """Detect identical or near-identical payloads despite provider reordering."""
    first, second = _news_identity(left), _news_identity(right)
    if not first or not second:
        return False
    return len(first & second) / min(len(first), len(second)) >= 0.8


def _build_news_snapshot_primary() -> dict[str, Any]:
    """Collect news independently so one market's outage does not hide the other."""
    checked_at = datetime.now().astimezone().isoformat()
    result: dict[str, Any] = {"taiwan": [], "us": [], "errors": [], "diagnostics": [], "source_health": []}
    for market in ("taiwan", "us"):
        try:
            result[market] = _filter_market_news(fetch_market_news(market), market)
            result["source_health"].append({
                "key": f"news_{market}", "label": f"{market} market news",
                "source_tier": "discovery", "source_url": ANUE_CATEGORY_URLS[market],
                "status": "healthy" if result[market] else "no_event", "checked_at": checked_at,
                "item_count": len(result[market]), "data_gap": None,
            })
        except Exception:
            result["errors"].append(f"{market}新聞資料暫時無法取得")
            result["source_health"].append({
                "key": f"news_{market}", "label": f"{market} market news",
                "source_tier": "discovery", "source_url": ANUE_CATEGORY_URLS[market],
                "status": "failed", "checked_at": checked_at,
                "item_count": 0, "data_gap": "request_failed",
            })

    # A transient CDN/cache response must never be presented as two different
    # markets.  If both lists are identical (or nearly identical), refresh both from
    # market-specific RSS queries; if that still fails, disclose the affected
    # feed instead of showing misleading duplicate headlines.
    if result["taiwan"] and result["us"] and _news_lists_collide(result["taiwan"], result["us"]):
        result["diagnostics"].append("台股與美股新聞來源回傳相同內容，已啟用市場分流備援")
        for market in ("taiwan", "us"):
            try:
                fallback = _filter_market_news(fetch_market_news_fallback(market), market)
                if fallback:
                    result[market] = fallback
                    health = next(item for item in result["source_health"] if item["key"] == f"news_{market}")
                    health.update({
                        "source_url": _market_news_rss_url(market),
                        "source_tier": "discovery",
                        "fallback_used": True,
                        "item_count": len(fallback),
                        "data_gap": None,
                    })
            except Exception:
                # Keep the original list until the final collision check so a
                # single fallback outage does not erase otherwise useful data.
                continue
        if result["taiwan"] and result["us"] and _news_lists_collide(result["taiwan"], result["us"]):
            result["us"] = []
            result["errors"].append("美股新聞資料暫時無法與台股來源區分")
            health = next(item for item in result["source_health"] if item["key"] == "news_us")
            health.update({"status": "failed", "item_count": 0, "data_gap": "duplicate_market_payload"})
    return result


def build_news_snapshot() -> dict[str, Any]:
    """Add durable, bounded fallback without ever reusing another market's news."""
    checked_at = datetime.now().astimezone().isoformat()
    result = _build_news_snapshot_primary()
    cache = _load_news_cache()
    markets = cache.setdefault("markets", {})
    for market in ("taiwan", "us"):
        health = next((item for item in result.get("source_health", [])
                       if item.get("key") == f"news_{market}"), None)
        if health is None:
            health = {"key": f"news_{market}", "status": "failed", "item_count": 0}
            result.setdefault("source_health", []).append(health)
        if result.get(market):
            stories = _filter_market_news(result[market], market)
            # A polluted primary feed may leave only one or two valid US
            # headlines after semantic filtering.  Treat that as incomplete,
            # not healthy: try the market-specific RSS feed before caching the
            # partial payload.  If the fallback is unavailable, retain the
            # valid subset rather than inventing or borrowing another market.
            if len(stories) < 5:
                try:
                    fallback = _filter_market_news(fetch_market_news_fallback(market), market)
                except Exception:
                    fallback = []
                other = result.get("us" if market == "taiwan" else "taiwan", [])
                if fallback and not _news_lists_collide(fallback, other):
                    stories = fallback
                    health.update({"status": "healthy", "item_count": len(stories),
                                   "source_url": _market_news_rss_url(market),
                                   "fallback_used": True, "data_gap": None})
            result[market] = stories
            if not any(item.get("stale_used") for item in stories):
                markets[market] = {"fetched_at": checked_at, "stories": stories}
            continue

        # A final category-specific attempt is useful when the primary provider
        # returned a shared shell or failed transiently.
        try:
            fallback = _filter_market_news(fetch_market_news_fallback(market), market)
        except Exception:
            fallback = []
        other = result.get("us" if market == "taiwan" else "taiwan", [])
        if fallback and not _news_lists_collide(fallback, other):
            result[market] = fallback
            health.update({"status": "healthy", "item_count": len(fallback),
                           "source_url": _market_news_rss_url(market),
                           "fallback_used": True, "data_gap": None})
            markets[market] = {"fetched_at": checked_at, "stories": fallback}
            continue

        cached = _filter_market_news(_recent_cached_stories(cache, market), market)
        if cached and not _news_lists_collide(cached, other):
            result[market] = cached
            health.update({"status": "stale", "item_count": len(cached),
                           "stale_used": True, "data_gap": "using_recent_news_cache"})
            result.setdefault("diagnostics", []).append(f"{market} news cache used")
        else:
            if health.get("status") == "no_event":
                health.update({"item_count": 0, "data_gap": None,
                               "no_event": True})
                result.setdefault("diagnostics", []).append(f"{market} news scan completed with no matching event")
            else:
                health.update({"status": "failed", "item_count": 0,
                               "data_gap": health.get("data_gap") or "request_failed"})
                result.setdefault("errors", []).append(f"{market} news unavailable")
    _save_news_cache(cache)
    return result
