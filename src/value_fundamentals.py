"""Normalise audited public financial fields for the independent value pool."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

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
SEC_USER_AGENT = "PRStK Lab public research contact@prstklab.example"


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
    client.headers.setdefault("User-Agent", SEC_USER_AGENT)
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
        period = net["period"] if net else own["period"] if own else None
        roe = None
        if net and own and own["value"]:
            # This is an annualised latest-period estimate, not a stability claim.
            quarter = int(str(period).split("Q")[-1]) if period and "Q" in str(period) else 4
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
            "reporting_period": period,
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


def sec_value_metrics(facts: dict[str, Any]) -> dict[str, Any]:
    """Read up to three annual SEC facts and disclose insufficiency explicitly."""
    net = _annual_facts(facts, "NetIncomeLoss")
    equity = _annual_facts(facts, "StockholdersEquity") or _annual_facts(facts, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
    dividends = _annual_facts(facts, "PaymentsOfDividendsCommonStock")
    if not net:
        return {"net_income": None, "roe": None, "payout_ratio": None, "years_available": 0, "roe_stable": None,
                "three_year_eps_positive": None, "four_quarter_eps_positive": None, "three_year_dividend_paid": None}
    net_by_year = {str(row.get("fy") or row.get("end")): number(row.get("val")) for row in net}
    equity_by_year = {str(row.get("fy") or row.get("end")): number(row.get("val")) for row in equity}
    years = [year for year, value in net_by_year.items() if value is not None]
    latest_year = years[0]
    current_net = net_by_year[latest_year]
    current_equity = equity_by_year.get(latest_year)
    prior_equity = equity_by_year.get(years[1]) if len(years) > 1 else None
    denominator = (current_equity + prior_equity) / 2 if current_equity and prior_equity else current_equity
    roe = None if not denominator else round(current_net / denominator, 6)
    dividend_by_year = {str(row.get("fy") or row.get("end")): number(row.get("val")) for row in dividends}
    payout = None
    if current_net and dividend_by_year.get(latest_year) is not None:
        payout = round(dividend_by_year[latest_year] / current_net, 6)
    roe_history = []
    for index, year in enumerate(years[:3]):
        current = equity_by_year.get(year)
        previous = equity_by_year.get(years[index + 1]) if index + 1 < len(years) else None
        average = (current + previous) / 2 if current and previous else current
        if average:
            roe_history.append(net_by_year[year] / average)
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
        "three_year_dividend_paid": len(dividend_values) >= 3 and all(value is not None and value > 0 for value in dividend_values),
        "financial_year": latest_year,
        "financial_source": "SEC EDGAR CompanyFacts",
    }


def sec_ticker_ciks(session: requests.Session | None = None) -> dict[str, int]:
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", SEC_USER_AGENT)
    response = client.get(SEC_TICKERS_URL, timeout=45)
    response.raise_for_status()
    return {str(item["ticker"]).upper(): int(item["cik_str"]) for item in response.json().values()}


def sec_fundamentals(tickers: Iterable[str], session: requests.Session | None = None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", SEC_USER_AGENT)
    try:
        ciks = sec_ticker_ciks(client)
    except (OSError, ValueError, requests.RequestException) as error:
        return {}, [f"SEC ticker mapping：{type(error).__name__}"]
    output, errors = {}, []
    for ticker in tickers:
        cik = ciks.get(ticker.upper())
        if cik is None:
            errors.append(f"{ticker} 無 SEC CIK")
            continue
        try:
            response = client.get(SEC_FACTS_URL.format(cik=cik), timeout=30)
            response.raise_for_status()
            output[ticker] = sec_value_metrics(response.json())
        except (OSError, ValueError, requests.RequestException) as error:
            errors.append(f"{ticker} SEC facts：{type(error).__name__}")
    return output, errors
