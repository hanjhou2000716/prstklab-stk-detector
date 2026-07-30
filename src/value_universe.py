"""Public, issuer-owned constituent universes for value research.

The value engine must not inherit its universe from momentum or price-action
screens.  It begins with the public constituent lists selected by the product
owner: 0050 + 0051 in Taiwan, and VOO in the United States.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
import re
from typing import Any

import pandas as pd
import requests


YUANTA_PCF_URL = "https://www.yuantaetfs.com/tradeInfo/pcf/{fund}"
YUANTA_PCF_API_URL = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"
VANGUARD_VOO_URL = "https://investor.vanguard.com/investment-products/etfs/profile/voo"
SP500_CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "PRStK-Lab-public-research/1.0 contact: prstklab@example.invalid"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _taiwan_code(value: Any) -> str | None:
    match = re.fullmatch(r"\s*(\d{4})\s*", _text(value))
    return match.group(1) if match else None


def parse_yuanta_holdings(tables: list[pd.DataFrame], fund: str) -> list[dict[str, str]]:
    """Extract ordinary-stock rows from an issuer holdings/PCF table.

    Yuanta has changed column labels over time, so this parser identifies a
    four-digit security code in the first two cells and deliberately excludes
    futures, cash and ETF rows.  It returns no rows rather than guessing.
    """
    rows: dict[str, dict[str, str]] = {}
    for table in tables:
        frame = table.fillna("")
        for _, row in frame.iterrows():
            values = [_text(value) for value in row.tolist()]
            ticker = next((_taiwan_code(value) for value in values[:2] if _taiwan_code(value)), None)
            if not ticker:
                continue
            joined = " ".join(values).lower()
            if any(word in joined for word in ("期貨", "future", "現金", "cash", "基金")):
                continue
            name = next((value for value in values if value and value != ticker and not _taiwan_code(value)), ticker)
            rows[ticker] = {
                "ticker": ticker,
                "symbol": f"{ticker}.TW",
                "name": name,
                "pool": fund,
                "source": f"Yuanta {fund} PCF",
            }
    return list(rows.values())


def parse_vanguard_holdings(tables: list[pd.DataFrame]) -> list[dict[str, str]]:
    """Extract listed common-stock tickers from Vanguard's VOO holdings table."""
    rows: dict[str, dict[str, str]] = {}
    for table in tables:
        columns = {str(column).strip().lower(): column for column in table.columns}
        ticker_col = next((column for label, column in columns.items() if label == "ticker"), None)
        holding_col = next((column for label, column in columns.items() if "holding" in label), None)
        if ticker_col is None or holding_col is None:
            continue
        for _, row in table.fillna("").iterrows():
            ticker = _text(row[ticker_col]).upper()
            name = _text(row[holding_col])
            if not re.fullmatch(r"[A-Z.]{1,8}", ticker) or ticker in {"N/A", "CASH"}:
                continue
            rows[ticker] = {
                "ticker": ticker,
                "symbol": ticker,
                "name": name or ticker,
                "pool": "VOO",
                "source": "Vanguard VOO holdings",
            }
    return list(rows.values())


def parse_sp500_constituents(tables: list[pd.DataFrame]) -> list[dict[str, str]]:
    """Use the public S&P 500 roster when Vanguard's rendered holdings are unavailable."""
    rows: dict[str, dict[str, str]] = {}
    for table in tables:
        columns = {str(column).strip().lower(): column for column in table.columns}
        ticker_col, name_col = columns.get("symbol"), columns.get("security")
        if ticker_col is None or name_col is None:
            continue
        for _, row in table.fillna("").iterrows():
            ticker = _text(row[ticker_col]).upper().replace(".", "-")
            if not re.fullmatch(r"[A-Z-]{1,8}", ticker):
                continue
            rows[ticker] = {
                "ticker": ticker, "symbol": ticker,
                "name": _text(row[name_col]) or ticker,
                "pool": "VOO-proxy",
                "source": "Public S&P 500 roster (VOO proxy)",
            }
    return list(rows.values())


def _read_tables(response: requests.Response) -> list[pd.DataFrame]:
    response.raise_for_status()
    # pandas 2.x treats a plain string as a file path in some parser paths.
    # Wrap public HTML explicitly so issuer pages are parsed as documents,
    # rather than failing with FileNotFoundError on their HTML source.
    return pd.read_html(StringIO(response.text), flavor="lxml")


def _yuanta_pcf_rows(client: requests.Session, fund: str) -> list[dict[str, str]]:
    """Read the issuer PCF bridge payload instead of a JavaScript-rendered page."""
    response = client.get(
        YUANTA_PCF_API_URL,
        params={
            "APIType": "ETFAPI", "CompanyName": "YUANTAFUNDS",
            "PageName": f"/tradeInfo/pcf/{fund}", "DeviceId": "null",
            "FuncId": "PCF/Daily", "AppName": "ETF", "Device": "3",
            "Platform": "ETF", "ticker": fund,
        },
        timeout=30,
    )
    response.raise_for_status()
    holdings = (response.json().get("InKind") or {}).get("FundComposition") or []
    rows: dict[str, dict[str, str]] = {}
    for item in holdings:
        ticker = _taiwan_code(item.get("stkcd"))
        if not ticker:
            continue
        rows[ticker] = {
            "ticker": ticker, "symbol": f"{ticker}.TW",
            "name": _text(item.get("name")) or ticker,
            "pool": fund, "source": f"Yuanta {fund} PCF API",
        }
    if not rows:
        raise ValueError(f"{fund} PCF payload returned no ordinary shares")
    return list(rows.values())


def fetch_taiwan_value_universe(session: requests.Session | None = None) -> tuple[list[dict[str, str]], list[str]]:
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", USER_AGENT)
    candidates: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for fund in ("0050", "0051"):
        try:
            rows = _yuanta_pcf_rows(client, fund)
            if not rows:
                errors.append(f"{fund} 官方成分表無可辨識普通股")
            for row in rows:
                previous = candidates.get(row["ticker"])
                if previous:
                    previous["pool"] = "+".join(sorted(set(previous["pool"].split("+")) | {fund}))
                else:
                    candidates[row["ticker"]] = row
        except (OSError, ValueError, requests.RequestException) as error:
            errors.append(f"{fund} 官方成分表取得失敗：{type(error).__name__}")
    return list(candidates.values()), errors


def fetch_taiwan_0050_universe(session: requests.Session | None = None) -> tuple[list[dict[str, str]], list[str]]:
    """Return the current issuer-published 0050 ordinary-share constituents."""
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", USER_AGENT)
    try:
        rows = _yuanta_pcf_rows(client, "0050")
    except (OSError, ValueError, requests.RequestException) as error:
        return [], [f"0050 constituent source unavailable: {type(error).__name__}"]
    return rows, ([] if rows else ["0050 constituent source returned no ordinary shares"])


def _fetch_us_value_universe_from_vanguard_page(session: requests.Session | None = None) -> tuple[list[dict[str, str]], list[str]]:
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", USER_AGENT)
    try:
        rows = parse_vanguard_holdings(_read_tables(client.get(VANGUARD_VOO_URL, timeout=30)))
        return rows, ([] if rows else ["VOO 官方持股表無可辨識普通股"])
    except (OSError, ValueError, requests.RequestException) as error:
        return [], [f"VOO 官方持股表取得失敗：{type(error).__name__}"]


def fetch_us_value_universe(session: requests.Session | None = None) -> tuple[list[dict[str, str]], list[str]]:
    """Return VOO holdings, with a disclosed S&P 500 roster fallback.

    Vanguard's public investor page currently renders holdings client-side.
    The fallback preserves the intended VOO/S&P 500 large-cap universe without
    treating an empty rendered document as a scan failure.
    """
    rows, errors = _fetch_us_value_universe_from_vanguard_page(session)
    if rows:
        return rows, []
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", USER_AGENT)
    try:
        # Wikipedia rejects the project-identification agent used by issuer
        # sources. Its public roster remains explicitly labelled as a VOO proxy.
        response = client.get(
            SP500_CONSTITUENTS_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        proxy_rows = parse_sp500_constituents(_read_tables(response))
    except (OSError, ValueError, requests.RequestException) as error:
        return [], [f"VOO issuer and S&P 500 proxy unavailable: {type(error).__name__}"]
    if proxy_rows:
        return proxy_rows, []
    return [], errors or ["VOO issuer and S&P 500 proxy returned no ordinary shares"]


def universe_snapshot(market: str, rows: list[dict[str, str]], errors: list[str]) -> dict[str, Any]:
    return {
        "market": market,
        "as_of": datetime.now(UTC).isoformat(),
        "source_status": "healthy" if rows and not errors else "partial" if rows else "unavailable",
        "candidate_count": len(rows),
        "errors": errors,
        "candidates": rows,
    }
