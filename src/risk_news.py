"""Public risk indicators and holding-related news for the dashboard."""

from __future__ import annotations

from typing import Any

import requests


CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
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


def _latest_close(symbol: str) -> dict[str, Any]:
    """Fetch the latest public close for a volatility index."""
    import yfinance as yf

    history = yf.download(
        symbol, period="10d", interval="1d", auto_adjust=False,
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
    return {
        "value": round(current, 2),
        "change_percent": change_percent,
        "date": close.index[-1].date().isoformat(),
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


def _market_risk(label: str, vix_symbol: str, sentiment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a transparent market risk card from fresh public indicators."""
    result: dict[str, Any] = {"label": label, "sentiment": sentiment, "vix": None, "errors": []}
    try:
        result["vix"] = _latest_close(vix_symbol)
    except Exception:
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
    taiwan = _market_risk("台股", "^VIXTWN")
    if us_sentiment["score"] is None:
        us["errors"].append("美股情緒資料暫時無法取得")
    return {
        "notice": "情緒與波動率僅供市場風險觀察，不構成投資建議。",
        "taiwan": taiwan,
        "us": us,
    }


def _news_from_html(html: str, market: str, limit: int = 3) -> list[dict[str, str]]:
    """Extract only holding-related article links from a public Anue category page."""
    from bs4 import BeautifulSoup

    terms = tuple(term.lower() for term in NEWS_TERMS[market])
    soup = BeautifulSoup(html, "html.parser")
    stories: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in soup.select('a[href^="/news/id/"]'):
        href = link.get("href", "")
        title = " ".join(link.stripped_strings)
        if not title or href in seen or not any(term in title.lower() for term in terms):
            continue
        seen.add(href)
        stories.append({"title": title, "url": f"https://news.cnyes.com{href}", "source": "鉅亨網"})
        if len(stories) == limit:
            break
    return stories


def fetch_market_news(market: str) -> list[dict[str, str]]:
    """Fetch up to three relevant public Anue headlines for one market."""
    response = requests.get(ANUE_CATEGORY_URLS[market], headers=HEADERS, timeout=15)
    response.raise_for_status()
    return _news_from_html(response.text, market)


def build_news_snapshot() -> dict[str, Any]:
    """Collect news independently so one market's outage does not hide the other."""
    result: dict[str, Any] = {"taiwan": [], "us": [], "errors": []}
    for market in ("taiwan", "us"):
        try:
            result[market] = fetch_market_news(market)
        except Exception:
            result["errors"].append(f"{market}新聞資料暫時無法取得")
    return result
