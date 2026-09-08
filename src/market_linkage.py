"""Resolve event entities to already-collected market observations.

This module is deliberately a deterministic lookup layer.  It does not fetch
prices and it never treats a resolved market as proof that the market reacted.
The latter remains the responsibility of the existing synchronization gate.
"""

from __future__ import annotations

import re
from typing import Any

_TAIWAN_MARKET_ALIASES = {
    "台股加權": "TAIEX",
    "台灣加權": "TAIEX",
    "加權指數": "TAIEX",
    "台股大盤": "TAIEX",
    "台指": "TAIEX",
    "台指期": "TXF",
    "台指期貨": "TXF",
    "TAIEX": "TAIEX",
    "TAIEX INDEX": "TAIEX",
    "櫃買": "TPEx",
    "櫃買指數": "TPEx",
    "TPEx": "TPEx",
}

# This is an intentionally small, auditable alias table.  It can grow from
# the existing instrument registry, but must not become a fuzzy web search.
_COMPANY_ALIASES: dict[str, dict[str, str]] = {
    "6505": {"code": "6505", "name": "台塑化", "market": "taiwan", "listed_market": "twse"},
    "台塑化": {"code": "6505", "name": "台塑化", "market": "taiwan", "listed_market": "twse"},
    "台塑石化": {"code": "6505", "name": "台塑化", "market": "taiwan", "listed_market": "twse"},
    "2330": {"code": "2330", "name": "台積電", "market": "taiwan", "listed_market": "twse"},
    "台積電": {"code": "2330", "name": "台積電", "market": "taiwan", "listed_market": "twse"},
    "台積": {"code": "2330", "name": "台積電", "market": "taiwan", "listed_market": "twse"},
}

_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _text(event: dict[str, Any]) -> str:
    return " ".join(
        str(event.get(key) or "")
        for key in (
            "issuer", "company", "company_name", "issuer_name", "ticker",
            "stock_code", "company_code", "affected_company", "title",
            "summary", "brief_summary", "event", "what_happened",
        )
    ).strip()


def _quote_by_ticker(indices: list[dict[str, Any]], ticker: str) -> dict[str, Any] | None:
    return next(
        (item for item in indices
         if str(item.get("ticker") or "").upper() == ticker.upper()),
        None,
    )


def _txf_from_taiex(indices: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Expose the existing TAIFEX direction check as a quote-shaped row."""
    taiex = _quote_by_ticker(indices, "TAIEX")
    if not taiex:
        return None
    sources = taiex.get("crosscheck_sources")
    if isinstance(sources, dict):
        candidate = sources.get("taifex")
    elif isinstance(sources, list):
        candidate = next(
            (item for item in sources if isinstance(item, dict)
             and str(item.get("provider") or item.get("label") or "").upper() == "TAIFEX"),
            None,
        )
    else:
        candidate = None
    if not isinstance(candidate, dict):
        return None
    return {
        **candidate,
        "ticker": "TXF",
        "name": "台指期",
        "market": "taiwan",
        "currency": candidate.get("currency") or "點",
        "quote_source": candidate.get("quote_source") or "TAIFEX official cross-check",
        "source_label": candidate.get("source_label") or "TAIFEX",
    }


def _company_match(event: dict[str, Any]) -> tuple[dict[str, str] | None, str]:
    explicit_values = [
        event.get("stock_code"), event.get("company_code"), event.get("issuer_ticker"),
        event.get("ticker"), event.get("company_name"), event.get("issuer"),
        event.get("company"), event.get("affected_company"),
    ]
    for field in ("instrument", "company"):
        value = event.get(field)
        if isinstance(value, dict):
            explicit_values.extend((
                value.get("ticker"), value.get("symbol"), value.get("stock_code"),
                value.get("company_code"), value.get("name"), value.get("company_name"),
            ))
    for value in explicit_values:
        key = str(value or "").strip().casefold()
        if key in _COMPANY_ALIASES:
            return _COMPANY_ALIASES[key], "explicit_company_alias"
    text = _text(event)
    code_match = _CODE_RE.search(text)
    if code_match and code_match.group(1) in _COMPANY_ALIASES:
        return _COMPANY_ALIASES[code_match.group(1)], "headline_company_code"
    for alias, match in _COMPANY_ALIASES.items():
        if not alias.isdigit() and alias in text:
            return match, "headline_company_alias"
    return None, "unresolved_company"


def _structured_company(event: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """Read an explicit non-index instrument without fuzzy company guessing."""
    values = [event.get("instrument"), event.get("company")]
    values.extend(value for value in (event.get("related") or []) if isinstance(value, dict))
    for value in values:
        if not isinstance(value, dict):
            continue
        ticker = str(value.get("ticker") or value.get("symbol") or value.get("stock_code") or "").strip()
        market = str(value.get("market") or value.get("exchange") or "").strip().casefold()
        asset_type = str(value.get("asset_type") or value.get("type") or "equity").strip().casefold()
        if not ticker or ticker.upper() in {"TAIEX", "TPEX", "TXF"} or asset_type in {"index", "future", "futures"}:
            continue
        if market in {"taiwan", "twse", "tpex", "上市", "上櫃"}:
            listed_market = "tpex" if market in {"tpex", "上櫃"} else "twse"
            return ticker, str(value.get("name") or ticker).strip(), listed_market, "structured_instrument"
    return None


def _market_refs(event: dict[str, Any], indices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(ticker: str, *, role: str, basis: str, entity: str = "") -> None:
        canonical = ticker.upper()
        if canonical in seen:
            return
        seen.add(canonical)
        quote = _quote_by_ticker(indices, canonical) or (
            _txf_from_taiex(indices) if canonical == "TXF" else None
        )
        refs.append({
            "ticker": "TPEx" if canonical == "TPEX" else canonical,
            "role": role,
            "match_basis": basis,
            "matched_entity": entity,
            "market": "taiwan" if canonical in {"TAIEX", "TXF", "TPEX"} else "unknown",
            "quote_available": bool(quote and quote.get("price") is not None),
            "market_sync_confirmed": bool(quote and quote.get("market_sync_confirmed") is True),
            "quote": quote,
        })

    # Existing structured links always win over inference.
    existing = event.get("linked_markets")
    if isinstance(existing, list):
        for value in existing:
            ticker = str(value or "").strip()
            if ticker:
                add(_TAIWAN_MARKET_ALIASES.get(ticker, ticker), role="market", basis="existing_structured_link")
    for field in ("market_evidence", "related", "instrument"):
        values = event.get(field)
        values = values if isinstance(values, list) else [values]
        for value in values:
            if not isinstance(value, dict):
                continue
            ticker = str(value.get("ticker") or value.get("symbol") or "").strip()
            if ticker:
                add(_TAIWAN_MARKET_ALIASES.get(ticker, ticker), role="market", basis="existing_structured_link")

    company, company_basis = _company_match(event)
    if company:
        code = company.get("code") or str(event.get("ticker") or "").strip()
        if code:
            add(code, role="company", basis=company_basis, entity=company.get("name", code))
        listed_market = company.get("listed_market")
        if listed_market == "tpex":
            add("TPEx", role="market_index", basis="listed_market", entity=company.get("name", ""))
        else:
            add("TAIEX", role="market_index", basis="listed_market", entity=company.get("name", ""))
        add("TXF", role="futures", basis="taiwan_company_market_baseline", entity=company.get("name", ""))

    structured_company = _structured_company(event)
    if structured_company and not company:
        ticker, name, listed_market, basis = structured_company
        add(ticker, role="company", basis=basis, entity=name)
        add("TPEx" if listed_market == "tpex" else "TAIEX", role="market_index", basis="listed_market", entity=name)
        add("TXF", role="futures", basis="taiwan_company_market_baseline", entity=name)

    explicit_market = str(event.get("market") or event.get("exchange") or "").strip().casefold()
    explicit_code = str(event.get("stock_code") or event.get("company_code") or "").strip()
    if not company and not structured_company and explicit_code and explicit_market in {"taiwan", "twse", "tpex", "上市", "上櫃"}:
        add(explicit_code, role="company", basis="explicit_company_code_and_market")
    if not company and not structured_company and explicit_market in {"taiwan", "twse", "tpex", "上市", "上櫃"}:
        add("TPEx" if explicit_market in {"tpex", "上櫃"} else "TAIEX", role="market_index", basis="explicit_market")
        add("TXF", role="futures", basis="taiwan_market_baseline")
    return refs


def resolve_event_market_links(event: dict[str, Any], indices: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return deterministic market references without asserting reaction."""
    rows = _market_refs(event, indices or [])
    return {
        "linked_markets": [str(item["ticker"]) for item in rows],
        "linked_market_details": [
            {key: value for key, value in item.items() if key != "quote"}
            for item in rows
        ],
        "market_linkage_basis": sorted({str(item["match_basis"]) for item in rows}),
        "market_linkage_status": "resolved" if rows else "unresolved",
        "market_sync_confirmed": any(item["market_sync_confirmed"] for item in rows),
        "diagnostics": [] if rows else ["未能由公司代碼、名稱、上市市場或既有結構化標的解析關聯市場"],
        "quote_rows": [item["quote"] for item in rows if isinstance(item.get("quote"), dict)],
    }


def linked_market_quotes(event: dict[str, Any], indices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return at most the two primary quote rows for an event card."""
    resolved = resolve_event_market_links(event, indices)
    by_ticker = {
        str(item.get("ticker") or "").upper(): item
        for item in resolved["quote_rows"] if isinstance(item, dict)
    }
    preferred = ("TAIEX", "TXF", "TPEx")
    return [by_ticker[ticker] for ticker in preferred if ticker in by_ticker][:2]


__all__ = ["linked_market_quotes", "resolve_event_market_links"]
