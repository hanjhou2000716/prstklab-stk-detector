"""Normalise audited public financial fields for the independent value pool."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

TWSE_BASE = "https://openapi.twse.com.tw/v1"
TWSE_INCOME_ENDPOINTS = (
    "opendata/t187ap06_L_ci", "opendata/t187ap06_L_basi", "opendata/t187ap06_L_bd",
    "opendata/t187ap06_L_fh", "opendata/t187ap06_L_ins", "opendata/t187ap06_L_mim",
)
TWSE_BALANCE_ENDPOINTS = (
    "opendata/t187ap07_L_ci", "opendata/t187ap07_L_basi", "opendata/t187ap07_L_bd",
    "opendata/t187ap07_L_fh", "opendata/t187ap07_L_ins", "opendata/t187ap07_L_mim",
)
TWSE_PE_ENDPOINT = "exchangeReport/BWIBBU_ALL"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_PROJECT_URL = "https://github.com/hanjhou2000716/prstklab-stk-detector"
# SEC requires a named client plus contact information in User-Agent.  The
# project URL is sent separately because URL-only User-Agents are rejected.
SEC_USER_AGENT = "PRStK Lab public research hanjhou2000716@gmail.com"
SEC_PROJECT_HEADER = {"X-Project-URL": SEC_PROJECT_URL}
SEC_RETRY_ATTEMPTS = 3
SEC_CACHE_MAX_AGE_DAYS = 90


def _sec_get(client: requests.Session, url: str, *, timeout: int) -> requests.Response:
    """Read an SEC public endpoint with a stable identity and brief retries."""
    last_error: requests.RequestException | None = None
    for attempt in range(SEC_RETRY_ATTEMPTS):
        try:
            response = client.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            error_response = getattr(error, "response", None)
            status = getattr(error_response, "status_code", None)
            retryable = status is None or status in {429, 500, 502, 503, 504}
            if retryable and attempt + 1 < SEC_RETRY_ATTEMPTS:
                time.sleep(0.6 * (attempt + 1))
    assert last_error is not None
    raise last_error


def number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def field(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def twse_financial_snapshot(
    tickers: Iterable[str], session: requests.Session | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return latest TWSE-filed net income, equity and public P/E.

    TWSE reports values in thousands of NTD.  A current filing is not silently
    relabelled as a three-year ROE history; callers receive the source period.
    """
    wanted = set(tickers)
    client = session or requests.Session()
    client.headers["User-Agent"] = SEC_USER_AGENT
    income: dict[str, dict[str, Any]] = {}
    equity: dict[str, dict[str, Any]] = {}
    pe: dict[str, float | None] = {}
    errors: list[str] = []
    for endpoint, target, metric in (
        *((endpoint, income, "本期淨利（淨損）") for endpoint in TWSE_INCOME_ENDPOINTS),
        *((endpoint, equity, "權益總額") for endpoint in TWSE_BALANCE_ENDPOINTS),
    ):
        try:
            data = client.get(f"{TWSE_BASE}/{endpoint}", timeout=45).json()
            for row in data:
                ticker = str(field(row, "公司代號") or "").strip()
                if ticker not in wanted:
                    continue
                value = number(field(row, metric))
                if value is None:
                    continue
                period = f"{field(row, '年度') or ''}Q{field(row, '季別') or ''}"
                current = target.get(ticker)
                if current is None or period > current["period"]:
                    target[ticker] = {"value": value * 1000, "period": period, "name": field(row, "公司名稱")}
        except (OSError, ValueError, requests.RequestException) as error:
            errors.append(f"TWSE {endpoint}：{type(error).__name__}")
    try:
        for row in client.get(f"{TWSE_BASE}/{TWSE_PE_ENDPOINT}", timeout=30).json():
            ticker = str(field(row, "Code") or "").strip()
            if ticker in wanted:
                pe[ticker] = number(field(row, "PEratio"))
    except (OSError, ValueError, requests.RequestException) as error:
        errors.append(f"TWSE {TWSE_PE_ENDPOINT}：{type(error).__name__}")

    output: dict[str, dict[str, Any]] = {}
    for ticker in wanted:
        net = income.get(ticker)
        own = equity.get(ticker)
        if not net and not own and ticker not in pe:
            continue
        reporting_period = str(net["period"] if net else own["period"] if own else "") or None
        roe = None
        if net and own and own["value"]:
            # This is an annualised latest-period estimate, not a stability claim.
            quarter = int(str(reporting_period).split("Q")[-1]) if reporting_period and "Q" in str(reporting_period) else 4
            roe = round((net["value"] / max(quarter, 1) * 4) / own["value"], 6)
        output[ticker] = {
            "net_income": net["value"] if net else None,
            "roe": roe,
            "pe": pe.get(ticker),
            # TWSE OpenAPI exposes the latest filing reliably.  The historical
            # EPS/dividend checks require dated MOPS filings and therefore stay
            # explicitly unavailable until that source is present.
            "three_year_eps_positive": None,
            "four_quarter_eps_positive": None,
            "three_year_dividend_paid": None,
            "reporting_period": reporting_period,
            "roe_basis": "TWSE latest filing annualised estimate" if roe is not None else None,
            "financial_source": "TWSE OpenAPI",
        }
    return output, errors


def _annual_facts(facts: dict[str, Any], name: str, unit: str = "USD") -> list[dict[str, Any]]:
    units = facts.get("facts", {}).get("us-gaap", {}).get(name, {}).get("units", {}).get(unit, [])
    rows = [row for row in units if row.get("fp") == "FY" and row.get("form") in {"10-K", "20-F", "40-F"}]
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        year = str(row.get("fy") or row.get("end") or "")
        previous = unique.get(year)
        if year and (previous is None or row.get("filed", "") > previous.get("filed", "")):
            unique[year] = row
    return sorted(unique.values(), key=lambda row: str(row.get("end", "")), reverse=True)


def _periodic_facts(facts: dict[str, Any], names: tuple[str, ...], forms: set[str]) -> list[dict[str, Any]]:
    """Read unique reported periods regardless of SEC unit naming."""
    rows: list[dict[str, Any]] = []
    for name in names:
        for unit_rows in facts.get("facts", {}).get("us-gaap", {}).get(name, {}).get("units", {}).values():
            rows.extend(row for row in unit_rows if row.get("form") in forms and row.get("val") is not None)
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        end = str(row.get("end") or "")
        previous = unique.get(end)
        if end and (previous is None or str(row.get("filed", "")) > str(previous.get("filed", ""))):
            unique[end] = row
    return sorted(unique.values(), key=lambda row: str(row.get("end", "")), reverse=True)


def _latest_shares_outstanding(facts: dict[str, Any]) -> float | None:
    """Return the latest SEC-reported share count when publicly disclosed.

    Yahoo ``floatShares`` is a useful fallback, but it is frequently delayed or
    rate-limited in hosted scans.  The SEC ``dei`` fact is a first-party,
    point-in-time value and is sufficient for the turnover-rate proxy used by
    the Pristine Value screen.  A missing fact remains ``None``; it is never
    replaced with a guessed market-cap-derived count.
    """
    units = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {})
    rows = [row for values in units.values() for row in values if row.get("val") is not None]
    if not rows:
        return None
    rows.sort(key=lambda row: (str(row.get("end") or ""), str(row.get("filed") or "")), reverse=True)
    value = number(rows[0].get("val"))
    return value if value and value > 0 else None


def sec_value_metrics(facts: dict[str, Any]) -> dict[str, Any]:
    """Read up to three annual SEC facts and disclose insufficiency explicitly."""
    net = _annual_facts(facts, "NetIncomeLoss")
    equity = _annual_facts(facts, "StockholdersEquity") or _annual_facts(facts, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
    dividends = _annual_facts(facts, "PaymentsOfDividendsCommonStock")
    shares_outstanding = _latest_shares_outstanding(facts)
    if not net:
        return {"net_income": None, "roe": None, "payout_ratio": None, "years_available": 0, "roe_stable": None,
                "three_year_eps_positive": None, "four_quarter_eps_positive": None, "three_year_dividend_paid": None,
                "shares_outstanding": shares_outstanding}
    net_by_year = {str(row.get("fy") or row.get("end")): number(row.get("val")) for row in net}
    equity_by_year = {str(row.get("fy") or row.get("end")): number(row.get("val")) for row in equity}
    years = [year for year, value in net_by_year.items() if value is not None]
    latest_year = years[0]
    current_net = net_by_year[latest_year]
    assert current_net is not None
    current_equity = equity_by_year.get(latest_year)
    prior_equity = equity_by_year.get(years[1]) if len(years) > 1 else None
    denominator = (current_equity + prior_equity) / 2 if current_equity and prior_equity else current_equity
    roe = None if not denominator else round(current_net / denominator, 6)
    dividend_by_year = {str(row.get("fy") or row.get("end")): number(row.get("val")) for row in dividends}
    payout = None
    if current_net and dividend_by_year.get(latest_year) is not None:
        # SEC cash-flow facts are reported as outflows (negative values).
        # Dividend-paid is a presence test, so use the absolute amount.
        dividend_value = dividend_by_year[latest_year]
        assert dividend_value is not None
        payout = round(abs(dividend_value) / abs(current_net), 6)
    roe_history = []
    for index, year in enumerate(years[:3]):
        current = equity_by_year.get(year)
        previous = equity_by_year.get(years[index + 1]) if index + 1 < len(years) else None
        average = (current + previous) / 2 if current and previous else current
        if average:
            net_value = net_by_year[year]
            assert net_value is not None
            roe_history.append(net_value / average)
    annual_eps = _periodic_facts(facts, ("EarningsPerShareDiluted", "EarningsPerShareBasic"), {"10-K", "20-F", "40-F"})
    quarterly_eps = _periodic_facts(facts, ("EarningsPerShareDiluted", "EarningsPerShareBasic"), {"10-Q", "10-K", "20-F", "40-F"})
    annual_eps_values = [number(row.get("val")) for row in annual_eps[:3]]
    quarter_eps_values = [number(row.get("val")) for row in quarterly_eps[:4]]
    dividend_values = [dividend_by_year.get(year) for year in years[:3]]
    return {
        "net_income": current_net,
        "roe": roe,
        "payout_ratio": payout,
        "years_available": len(years[:3]),
        "roe_stable": len(roe_history) >= 3 and all(value >= 0.17 for value in roe_history),
        "three_year_eps_positive": len(annual_eps_values) >= 3 and all(value is not None and value > 0 for value in annual_eps_values),
        "four_quarter_eps_positive": len(quarter_eps_values) >= 4 and all(value is not None and value > 0 for value in quarter_eps_values),
        "three_year_dividend_paid": len(dividend_values) >= 3 and all(value is not None and abs(value) > 0 for value in dividend_values),
        "shares_outstanding": shares_outstanding,
        "financial_year": latest_year,
        "financial_source": "SEC EDGAR CompanyFacts",
    }


def sec_ticker_ciks(session: requests.Session | None = None) -> dict[str, int]:
    client = session or requests.Session()
    client.headers["User-Agent"] = SEC_USER_AGENT
    client.headers.update(SEC_PROJECT_HEADER)
    response = _sec_get(client, SEC_TICKERS_URL, timeout=45)
    return {str(item["ticker"]).upper(): int(item["cik_str"]) for item in response.json().values()}


def sec_fundamentals(
    tickers: Iterable[str], session: requests.Session | None = None, *, cik_overrides: dict[str, str | int] | None = None,
    cache_path: str | Path | None = None, max_cache_age_days: int = SEC_CACHE_MAX_AGE_DAYS,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    client = session or requests.Session()
    client.headers["User-Agent"] = SEC_USER_AGENT
    client.headers.update(SEC_PROJECT_HEADER)
    ticker_list = list(tickers)
    cache_file = Path(cache_path) if cache_path else None
    cache: dict[str, dict[str, Any]] = {}
    if cache_file and cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            cache = payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            cache = {}
    overrides = {str(key).upper(): int(value) for key, value in (cik_overrides or {}).items() if str(value).isdigit()}
    if all(ticker.upper() in overrides for ticker in ticker_list):
        # The S&P 500 public roster supplies CIKs for the VOO proxy.  Avoid a
        # redundant SEC mapping request, which some hosted runners reject.
        ciks, mapping_error = {}, None
    else:
        try:
            ciks = sec_ticker_ciks(client)
        except (OSError, ValueError, requests.RequestException) as error:
            ciks = {}
            mapping_error = f"SEC ticker mapping：{type(error).__name__}"
        else:
            mapping_error = None
    output, errors = {}, []
    cache_changed = False
    for ticker in ticker_list:
        cik = overrides.get(ticker.upper()) or ciks.get(ticker.upper())
        if cik is None:
            errors.append(f"{ticker} 無 SEC CIK")
            continue
        try:
            response = _sec_get(client, SEC_FACTS_URL.format(cik=cik), timeout=30)
            metrics = sec_value_metrics(response.json())
            fetched_at = datetime.now(UTC).isoformat()
            metrics["sec_data_fetched_at"] = fetched_at
            metrics["sec_cache_used"] = False
            output[ticker] = metrics
            if cache_file:
                cache[ticker.upper()] = {"cik": cik, "fetched_at": fetched_at, "metrics": metrics}
                cache_changed = True
            # SEC asks automated clients to remain under ten requests/second.
            time.sleep(0.11)
        except (OSError, ValueError, requests.RequestException) as error:
            cached = cache.get(ticker.upper())
            cached_at = cached.get("fetched_at") if isinstance(cached, dict) else None
            try:
                cache_time = datetime.fromisoformat(str(cached_at).replace("Z", "+00:00")) if cached_at else None
            except ValueError:
                cache_time = None
            if cache_time and cache_time >= datetime.now(UTC) - timedelta(days=max_cache_age_days) and isinstance(cached, dict):
                metrics = dict(cached.get("metrics") or {})
                metrics["financial_source"] = "SEC EDGAR CompanyFacts (cached)"
                metrics["sec_cache_used"] = True
                metrics["sec_data_fetched_at"] = cached_at
                output[ticker] = metrics
            else:
                errors.append(f"{ticker} SEC facts：{type(error).__name__}")
    if mapping_error and len(overrides) < len({ticker.upper() for ticker in ticker_list}):
        errors.insert(0, mapping_error)
    if cache_file and cache_changed:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return output, errors
