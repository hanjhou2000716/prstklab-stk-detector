"""Public, issuer-owned constituent universes for value research.

The value engine must not inherit its universe from momentum or price-action
screens.  It begins with the public constituent lists selected by the product
owner: 0050 + 0051 in Taiwan, and VOO in the United States.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.http_client import configure_public_source_tls
from src.us_universe import (
    NASDAQ100_REFERER,
    NASDAQ100_URL,
    SEMICONDUCTOR_CORE,
    parse_nasdaq100_constituents,
)

YUANTA_PCF_URL = "https://www.yuantaetfs.com/tradeInfo/pcf/{fund}"
YUANTA_PCF_API_URL = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"
VANGUARD_VOO_URL = "https://investor.vanguard.com/investment-products/etfs/profile/voo"
SP500_CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "PRStK-Lab-public-research/1.0 contact: prstklab@example.invalid"

# Issued ordinary shares are the only Taiwan turnover denominator accepted by
# the value screen.  Both endpoints are issuer/regulator operated and return
# the same semantic field (TWSE in Chinese, TPEx in English).
TWSE_ISSUED_SHARES_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_ISSUED_SHARES_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _display_name(value: Any, fallback: Any, ticker: str) -> str:
    """Prefer readable issuer names when a provider returns replacement chars."""
    name = _text(value)
    if name and "�" not in name:
        return name
    return _text(fallback) or ticker


def _taiwan_code(value: Any) -> str | None:
    match = re.fullmatch(r"\s*(\d{4})\s*", _text(value))
    return match.group(1) if match else None


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _roc_or_iso_date(value: Any) -> str | None:
    """Normalise regulator dates without treating a quote date as a time."""
    text = _text(value)
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) == 7 and 90 <= int(digits[:3]) <= 200:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def _official_share_row(row: dict[str, Any], *, source: str, fetched_at: str) -> tuple[str, dict[str, Any]] | None:
    """Parse one TWSE/TPEx issued-common-share row."""
    ticker = _taiwan_code(
        row.get("公司代號") or row.get("SecuritiesCompanyCode")
        or row.get("證券代號") or row.get("Code")
    )
    shares = _number(
        row.get("已發行普通股數或TDR原股發行股數")
        or row.get("IssueShares") or row.get("IssuedShares")
        or row.get("普通股已發行股數")
    )
    as_of = _roc_or_iso_date(row.get("出表日期") or row.get("Date") or row.get("資料日期"))
    if not ticker or shares is None:
        return None
    return ticker, {
        "value": shares,
        "shares_value": shares,
        "shares_basis": "issued_common_shares",
        "shares_source": source,
        "shares_as_of": as_of,
        "source": source,
        "source_tier": "official",
        "fetched_at": fetched_at,
        "freshness": "fresh",
        "fallback_used": False,
        "fallback_source": None,
        "fallback_basis": None,
    }


def _official_share_payload(response: requests.Response) -> list[dict[str, Any]]:
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "Data", "aaData", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def fetch_taiwan_official_share_records(
    candidates: list[dict[str, str]], *, session: requests.Session | None = None,
    cache_path: str | Path | None = None, max_cache_age_days: int = 7,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Fetch one consistent Taiwan issued-share denominator for every candidate.

    Yahoo float/outstanding shares are intentionally not a Taiwan fallback:
    they are different bases and would make cross-sectional turnover rankings
    incomparable.  A bounded cache is permitted only when it contains the
    same official ``issued_common_shares`` basis.
    """
    client = configure_public_source_tls(session)
    client.headers.setdefault("User-Agent", USER_AGENT)
    now = datetime.now(UTC)
    cache_file = Path(cache_path) if cache_path else None
    cache: dict[str, Any] = {}
    if cache_file and cache_file.exists():
        try:
            loaded = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cache = loaded
        except (OSError, ValueError, TypeError):
            cache = {}
    records: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for url, source in ((TWSE_ISSUED_SHARES_URL, "TWSE official issued common shares"),
                        (TPEX_ISSUED_SHARES_URL, "TPEx official issued common shares")):
        try:
            for row in _official_share_payload(client.get(url, timeout=30)):
                parsed = _official_share_row(row, source=source, fetched_at=now.isoformat())
                if parsed:
                    records.setdefault(parsed[0], parsed[1])
        except (OSError, ValueError, requests.RequestException) as exc:
            errors.append(f"{source} unavailable: {type(exc).__name__}")
    wanted = {_taiwan_code(item.get("ticker")) for item in candidates}
    wanted.discard(None)
    output = {f"{ticker}.TW": record for ticker, record in records.items() if ticker in wanted}
    # Preserve the market suffix used by the candidate (TPEx often uses .TWO).
    for item in candidates:
        ticker = _taiwan_code(item.get("ticker"))
        if not ticker or ticker not in records:
            continue
        output[item["symbol"]] = dict(records[ticker])
        output.pop(f"{ticker}.TW", None) if item["symbol"] != f"{ticker}.TW" else None
    if cache_file and output:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    missing = []
    for item in candidates:
        symbol = item["symbol"]
        if symbol in output:
            continue
        cached = cache.get(symbol)
        if isinstance(cached, dict) and cached.get("value") and cached.get("shares_basis") == "issued_common_shares":
            try:
                fetched = datetime.fromisoformat(str(cached.get("fetched_at")).replace("Z", "+00:00")).astimezone(UTC)
            except (TypeError, ValueError):
                fetched = None
            if fetched and now - fetched <= timedelta(days=max_cache_age_days):
                output[symbol] = {**cached, "freshness": "bounded_cache", "fallback_used": True,
                                  "fallback_source": "official_cache", "fallback_basis": "issued_common_shares"}
                continue
        missing.append(item.get("ticker", symbol))
    if missing:
        errors.append(f"official issued-share records missing: {len(missing)}")
    return output, errors


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
        cik_col = columns.get("cik")
        if ticker_col is None or name_col is None:
            continue
        for _, row in table.fillna("").iterrows():
            ticker = _text(row[ticker_col]).upper().replace(".", "-")
            if not re.fullmatch(r"[A-Z-]{1,8}", ticker):
                continue
            row_data = {
                "ticker": ticker, "symbol": ticker,
                "name": _text(row[name_col]) or ticker,
                "pool": "VOO-proxy",
                "source": "Public S&P 500 roster (VOO proxy)",
            }
            if cik_col is not None:
                cik = _text(row[cik_col]).replace(".0", "")
                if cik.isdigit():
                    row_data["cik"] = cik
            rows[ticker] = row_data
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
            "name": _display_name(item.get("name"), item.get("ename"), ticker),
            "pool": fund, "source": f"Yuanta {fund} PCF API",
        }
    if not rows:
        raise ValueError(f"{fund} PCF payload returned no ordinary shares")
    return list(rows.values())


def fetch_taiwan_value_universe(session: requests.Session | None = None) -> tuple[list[dict[str, str]], list[str]]:
    client = configure_public_source_tls(session)
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
    client = configure_public_source_tls(session)
    client.headers.setdefault("User-Agent", USER_AGENT)
    try:
        rows = _yuanta_pcf_rows(client, "0050")
    except (OSError, ValueError, requests.RequestException) as error:
        return [], [f"0050 constituent source unavailable: {type(error).__name__}"]
    return rows, ([] if rows else ["0050 constituent source returned no ordinary shares"])


def _fetch_us_value_universe_from_vanguard_page(session: requests.Session | None = None) -> tuple[list[dict[str, str]], list[str]]:
    client = configure_public_source_tls(session)
    client.headers.setdefault("User-Agent", USER_AGENT)
    try:
        rows = parse_vanguard_holdings(_read_tables(client.get(VANGUARD_VOO_URL, timeout=30)))
        return rows, ([] if rows else ["VOO 官方持股表無可辨識普通股"])
    except (OSError, ValueError, requests.RequestException) as error:
        return [], [f"VOO 官方持股表取得失敗：{type(error).__name__}"]


def fetch_us_value_universe(session: requests.Session | None = None) -> tuple[list[dict[str, str]], list[str]]:
    """Return the strict US value pool: Nasdaq-100 plus semiconductor core.

    The previous VOO/S&P 500 fallback requested roughly 500 SEC CompanyFacts
    documents in one run.  That made a transient SEC block look like an empty
    value scan and regularly exceeded the hosted job's time budget.  The
    product scope is now the smaller, explicit Nasdaq-100 + semiconductor/AI
    core pool; SEC remains the only formal financial-data source.
    """
    client = configure_public_source_tls(session)
    client.headers.setdefault("User-Agent", USER_AGENT)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)", "Referer": NASDAQ100_REFERER}
    errors: list[str] = []
    nasdaq_rows: list[dict[str, str]] = []
    try:
        for offset in range(7):
            trade_date = (datetime.now(UTC).date() - timedelta(days=offset)).isoformat()
            response = client.post(
                NASDAQ100_URL,
                data={"id": "NDX", "tradeDate": trade_date, "timeOfDay": "SOD"},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            try:
                nasdaq_rows = parse_nasdaq100_constituents(response.json())
                break
            except ValueError:
                continue
    except (OSError, ValueError, requests.RequestException) as error:
        errors.append(f"Nasdaq-100 constituents unavailable: {type(error).__name__}")
    if not nasdaq_rows:
        return [], errors or ["Nasdaq-100 constituents returned no rows"]

    combined = [
        {**row, "pool": "NASDAQ-100", "source": "Nasdaq public weighting data"}
        for row in nasdaq_rows
    ]
    combined.extend(
        {"ticker": ticker, "symbol": ticker, "name": name, "pool": "semiconductor-core", "source": "PRStK public semiconductor core"}
        for ticker, name in SEMICONDUCTOR_CORE
    )
    unique: dict[str, dict[str, str]] = {}
    for row in combined:
        unique.setdefault(row["ticker"], row)
    return list(unique.values()), errors


def universe_snapshot(market: str, rows: list[dict[str, str]], errors: list[str]) -> dict[str, Any]:
    return {
        "market": market,
        "as_of": datetime.now(UTC).isoformat(),
        "source_status": "healthy" if rows and not errors else "partial" if rows else "unavailable",
        "candidate_count": len(rows),
        "errors": errors,
        "candidates": rows,
    }
