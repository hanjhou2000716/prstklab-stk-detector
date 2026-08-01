"""Public risk indicators and holding-related news for the dashboard."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

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
NEWS_TERMS = {
    "taiwan": ("006208", "00685L", "2330", "台積電", "台股", "半導體"),
    "us": ("QQQM", "QLD", "TSM", "NVDA", "NVIDIA", "輝達", "美股", "那斯達克"),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)"}


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
    change_percent = None if previous in (None, 0) else round((current / previous - 1) * 100, 2)
    window = close.tail(252)
    percentile = round(float((window <= current).sum() / len(window) * 100), 1) if len(window) else None
    return {
        "value": round(current, 2),
        "change_percent": change_percent,
        "percentile": percentile,
        "stage": vix_stage(current, percentile),
        "date": close.index[-1].date().isoformat(),
        "source_label": "Yahoo Finance",
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
        href = link.get("href", "")
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
    """Fetch up to three relevant public Anue headlines for one market."""
    response = requests.get(ANUE_CATEGORY_URLS[market], headers=HEADERS, timeout=15)
    response.raise_for_status()
    return _news_from_html(response.text, market)


def build_news_snapshot() -> dict[str, Any]:
    """Collect news independently so one market's outage does not hide the other."""
    checked_at = datetime.now().astimezone().isoformat()
    result: dict[str, Any] = {"taiwan": [], "us": [], "errors": [], "source_health": []}
    for market in ("taiwan", "us"):
        try:
            result[market] = fetch_market_news(market)
            result["source_health"].append({
                "key": f"news_{market}", "label": f"{market} market news",
                "source_tier": "discovery", "source_url": ANUE_CATEGORY_URLS[market],
                "status": "healthy", "checked_at": checked_at,
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
    return result
