"""Market-scoped projections for routine Taiwan and US briefings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SCOPE_VERSION = "market-projection-v1"

SLOT_SCOPE = {
    "post_close": "taiwan",
    "us_premarket": "us",
}

SCOPE_TICKERS = {
    "taiwan": frozenset({"TAIEX", "TXF"}),
    "us": frozenset({"S&P 500", "NASDAQ", "DJIA", "SOX", "ES", "NQ", "YM"}),
}

_TICKER_SCOPE = {
    "TAIEX": "taiwan",
    "TAI WAN INDEX": "taiwan",
    "台股加權": "taiwan",
    "台灣加權": "taiwan",
    "臺灣加權": "taiwan",
    "加權指數": "taiwan",
    "TXF": "taiwan",
    "台指期": "taiwan",
    "台指期近月": "taiwan",
    "S&P 500": "us",
    "SPX": "us",
    "NASDAQ": "us",
    "NASDAQ COMPOSITE": "us",
    "NASDAQ-100": "us",
    "DJIA": "us",
    "DOW JONES": "us",
    "SOX": "us",
    "費半": "us",
    "費城半導體": "us",
    "費城半導體指數": "us",
    "ES": "us",
    "NQ": "us",
    "YM": "us",
}


def market_scope_for_slot(slot: str | None) -> str | None:
    return SLOT_SCOPE.get(str(slot or "").strip())


def _market_tag(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"tw", "taiwan", "taiwan_market", "taiwan market", "台股", "台灣", "臺灣"}:
        return "taiwan"
    if text in {"us", "usa", "united_states", "united states", "us market", "us markets", "美股", "美國"}:
        return "us"
    return ""


def _ticker_scope(value: Any) -> str:
    """Resolve only explicit canonical instrument names and safe aliases."""
    text = str(value or "").strip()
    return _TICKER_SCOPE.get(text.upper(), _TICKER_SCOPE.get(text, ""))


def _event_scope(event: dict[str, Any]) -> set[str]:
    scopes: set[str] = set()
    for key in ("market_scope", "market", "market_key", "primary_market"):
        tag = _market_tag(event.get(key))
        if tag:
            scopes.add(tag)
    for key in ("markets", "linked_markets", "impact_markets", "market_tags"):
        values = event.get(key)
        if isinstance(values, (list, tuple, set)):
            scopes.update(tag for tag in (_market_tag(value) for value in values) if tag)
        else:
            tag = _market_tag(values)
            if tag:
                scopes.add(tag)
    instrument = event.get("instrument")
    if isinstance(instrument, dict):
        tag = _market_tag(instrument.get("market"))
        if tag:
            scopes.add(tag)
        ticker_scope = _ticker_scope(instrument.get("ticker"))
        if ticker_scope:
            scopes.add(ticker_scope)
    evidence = event.get("market_evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            tag = _market_tag(item.get("market"))
            if tag:
                scopes.add(tag)
            ticker_scope = _ticker_scope(item.get("ticker"))
            if ticker_scope:
                scopes.add(ticker_scope)
    return scopes


def event_belongs_to_scope(event: dict[str, Any], scope: str) -> bool:
    """Only admit explicitly market-linked events to a scoped main card."""
    scopes = _event_scope(event)
    return scope in scopes and scopes <= {scope}


def _filter_rows(value: Any, scope: str) -> Any:
    if not isinstance(value, list):
        return value
    allowed = SCOPE_TICKERS[scope]
    rows = []
    for row in value:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        market = _market_tag(row.get("market"))
        if ticker in allowed and (not market or market == scope):
            rows.append(row)
    return rows


def _filter_events(value: Any, scope: str) -> Any:
    if not isinstance(value, list):
        return value
    return [
        row for row in value
        if isinstance(row, dict) and event_belongs_to_scope(row, scope)
    ]


def scope_snapshot(snapshot: dict[str, Any], slot: str | None) -> dict[str, Any]:
    """Copy and constrain all card inputs; never use a foreign-market fallback."""
    scope = market_scope_for_slot(slot)
    if not scope:
        return snapshot
    result = deepcopy(snapshot)
    result["market_scope"] = scope
    result["market_projection_version"] = SCOPE_VERSION
    result["indices"] = _filter_rows(result.get("indices"), scope)
    result["quotes"] = _filter_rows(result.get("quotes"), scope)
    result["macro_quotes"] = []
    # Aggregated inputs cannot be safely narrowed after the fact. Routine
    # market cards derive only from target-market quotes and tagged events.
    result["macro"] = None
    result["research_report"] = {}
    result["creator_insights"] = []
    result["paper_portfolio_history"] = None
    result["phase_two"] = {}
    result["risk"] = {
        scope: result.get("risk", {}).get(scope)
    } if isinstance(result.get("risk"), dict) and isinstance(result.get("risk", {}).get(scope), dict) else {}
    if scope != "taiwan":
        result.pop("taiwan_market_statistics", None)
    if isinstance(result.get("events"), dict):
        result["events"]["items"] = _filter_events(result["events"].get("items"), scope)
    for key in (
        "financialjuice_priority_events", "financialjuice_observations",
        "external_observations", "official_events",
    ):
        if key in result:
            result[key] = _filter_events(result.get(key), scope)
    for key in ("official_events", "creator_events"):
        block = result.get(key)
        if isinstance(block, dict) and isinstance(block.get("items"), list):
            block["items"] = _filter_events(block["items"], scope)
    news = result.get("news")
    if isinstance(news, dict):
        intelligence = news.get("intelligence")
        if isinstance(intelligence, dict):
            result["news"]["intelligence"] = {
                key: value for key, value in intelligence.items()
                if _market_tag(key) == scope
            }
        markets = news.get("markets")
        if isinstance(markets, dict):
            result["news"]["markets"] = {
                key: value for key, value in markets.items()
                if _market_tag(key) == scope
            }
    market_status = result.get("markets")
    if isinstance(market_status, dict):
        result["markets"] = {
            key: value for key, value in market_status.items()
            if _market_tag(key) == scope
        }
    return result


__all__ = [
    "SCOPE_TICKERS",
    "SCOPE_VERSION",
    "event_belongs_to_scope",
    "market_scope_for_slot",
    "scope_snapshot",
]
