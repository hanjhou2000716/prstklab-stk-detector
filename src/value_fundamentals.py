"""Normalise audited public financial fields for the independent value pool."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from math import isfinite
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
TW_VALUE_RULE_VERSION = "tw_value_current_quality_v2"
TW_VALUE_PARAMETER_HASH = hashlib.sha256(
    b"eps_ytd>0|annualized_quality_ratio>=0.17|heat_percentile<90|heat_passes>=3|bars=63|min_valid_bars=40"
).hexdigest()[:16]
TWSE_FINANCIAL_PARSE_VERSION = "twse-batch-financial-v1"
TWSE_FINANCIAL_CACHE_SCHEMA = 1
TWSE_FINANCIAL_CACHE_MAX_AGE_DAYS = 7
TWSE_FINANCIAL_PERIOD_MAX_AGE_DAYS = 200
TWSE_FINANCIAL_RETRIES = 1
TWSE_FINANCIAL_MAX_WORKERS = 4

# These are intentionally exact regulator field names.  Similar-looking
# group equity/net-income columns are not interchangeable with the parent
# owner's columns required by the Taiwan quality rule.
TWSE_EPS_FIELDS = ("基本每股盈餘（元）", "基本每股盈餘")
TWSE_PARENT_NET_FIELDS = ("淨利（淨損）歸屬於母公司業主",)
TWSE_PARENT_EQUITY_FIELDS = (
    "歸屬於母公司業主之權益合計",
    "歸屬於母公司業主之權益總額",
)
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


def _finite_number(value: Any) -> float | None:
    """Parse a regulator number without allowing NaN/Infinity into a report."""
    parsed = number(value)
    return parsed if parsed is not None and isfinite(parsed) else None


def _twse_year(value: Any) -> int | None:
    text = str(value or "").strip()
    try:
        year = int(text)
    except (TypeError, ValueError):
        return None
    return year + 1911 if 90 <= year <= 200 else year if 1900 <= year <= 2200 else None


def _twse_quarter(value: Any) -> int | None:
    text = str(value or "").strip().upper().replace("Q", "")
    digits = "".join(character for character in text if character.isdigit())
    try:
        quarter = int(digits)
    except (TypeError, ValueError):
        return None
    return quarter if 1 <= quarter <= 4 else None


def _twse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) == 7 and 90 <= int(digits[:3]) <= 200:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text or None


def _twse_period(row: dict[str, Any]) -> tuple[int, int, str] | None:
    year = _twse_year(field(row, "年度", "財報年度", "FiscalYear"))
    quarter = _twse_quarter(field(row, "季別", "季度", "Quarter"))
    if year is None or quarter is None:
        return None
    return year, quarter, f"{year}Q{quarter}"


def _twse_response_payload(response: Any) -> tuple[Any, str]:
    raise_for_status = getattr(response, "raise_for_status", None)
    if callable(raise_for_status):
        raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload or not all(isinstance(item, dict) for item in payload):
        raise ValueError("TWSE response is not a row list")
    raw = getattr(response, "content", b"")
    if not raw:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return payload, hashlib.sha256(raw).hexdigest()


def _twse_endpoint_request(
    endpoint: str, *, session: requests.Session | None, deadline: float | None,
) -> dict[str, Any]:
    """Fetch one official batch endpoint with one bounded retry."""
    client = session or requests.Session()
    client.headers["User-Agent"] = "PRStK-Lab-public-research/1.0"
    url = f"{TWSE_BASE}/{endpoint}"
    last_error: Exception | None = None
    for attempt in range(TWSE_FINANCIAL_RETRIES + 1):
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 2:
            raise TimeoutError("deadline_exceeded")
        timeout = max(1.0, min(45.0, remaining - 1 if remaining is not None else 45.0))
        try:
            response = client.get(url, timeout=timeout)
            payload, source_hash = _twse_response_payload(response)
            return {
                "endpoint": endpoint, "url": url, "rows": payload,
                "source_sha256": source_hash,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        except (OSError, ValueError, requests.RequestException, TimeoutError) as error:
            last_error = error
            status = getattr(getattr(error, "response", None), "status_code", None)
            retryable = isinstance(error, (OSError, requests.RequestException, TimeoutError)) and (
                status is None or status in {429, 500, 502, 503, 504}
            )
            if attempt >= TWSE_FINANCIAL_RETRIES or not retryable:
                break
            retry_after = getattr(getattr(error, "response", None), "headers", {}).get("Retry-After")
            try:
                wait = min(5.0, max(0.25, float(retry_after))) if retry_after else 0.5
            except (TypeError, ValueError):
                wait = 0.5
            if deadline is not None and time.monotonic() + wait >= deadline - 1:
                break
            time.sleep(wait)
    assert last_error is not None
    raise last_error


def _twse_cache_load(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _twse_cache_record_valid(record: Any, *, now: datetime, expected_period: str | None) -> bool:
    if not isinstance(record, dict) or record.get("parse_version") != TWSE_FINANCIAL_PARSE_VERSION:
        return False
    if expected_period and record.get("reporting_period") != expected_period:
        return False
    try:
        fetched = datetime.fromisoformat(str(record.get("last_checked_at")).replace("Z", "+00:00")).astimezone(UTC)
        period_end = datetime.fromisoformat(str(record.get("period_end")).replace("Z", "+00:00")).astimezone(UTC)
    except (TypeError, ValueError):
        return False
    required = ("eps_ytd", "parent_net_income_ytd", "parent_equity", "source_sha256")
    if any(_finite_number(record.get(key)) is None for key in required[:3]) or not record.get("source_sha256"):
        return False
    return (
        now - fetched <= timedelta(days=TWSE_FINANCIAL_CACHE_MAX_AGE_DAYS)
        and now - period_end <= timedelta(days=TWSE_FINANCIAL_PERIOD_MAX_AGE_DAYS)
    )


def _twse_cache_save(path: Path | None, records: dict[str, dict[str, Any]], metadata: dict[str, Any]) -> str | None:
    if path is None:
        return None
    payload = {
        "schema_version": TWSE_FINANCIAL_CACHE_SCHEMA,
        "parse_version": TWSE_FINANCIAL_PARSE_VERSION,
        "saved_at": datetime.now(UTC).isoformat(),
        "records": records,
        "endpoint_hashes": metadata.get("endpoint_hashes", {}),
    }
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return type(error).__name__
    return None


def twse_current_quality_snapshot(
    tickers: Iterable[str], session: requests.Session | None = None, *,
    cache_path: str | Path | None = None, deadline: float | None = None,
    expected_period: str | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, Any]]:
    """Read Taiwan current-quality fundamentals from official TWSE batches.

    The twelve industry endpoints are fetched at most once per run and merged
    only when the same issuer and fiscal period are present.  Parent-company
    net income and parent-company equity are required; consolidated totals are
    deliberately not substituted.  ``session`` is accepted for deterministic
    tests and uses serial requests, while production uses at most four workers.
    """
    wanted = {str(ticker).strip() for ticker in tickers if str(ticker).strip()}
    endpoints = tuple((item, "income") for item in TWSE_INCOME_ENDPOINTS) + tuple((item, "balance") for item in TWSE_BALANCE_ENDPOINTS)
    fetched: list[dict[str, Any]] = []
    endpoint_errors: list[str] = []
    if session is not None:
        for endpoint, category in endpoints:
            try:
                result = _twse_endpoint_request(endpoint, session=session, deadline=deadline)
                result["category"] = category
                fetched.append(result)
            except Exception as error:
                endpoint_errors.append(f"TWSE {endpoint}: {type(error).__name__}")
    else:
        with ThreadPoolExecutor(max_workers=TWSE_FINANCIAL_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_twse_endpoint_request, endpoint, session=None, deadline=deadline): (endpoint, category)
                for endpoint, category in endpoints
            }
            for future in as_completed(futures):
                endpoint, category = futures[future]
                try:
                    result = future.result()
                    result["category"] = category
                    fetched.append(result)
                except Exception as error:
                    endpoint_errors.append(f"TWSE {endpoint}: {type(error).__name__}")

    # Merge only rows with an explicit fiscal period.  A row from an income
    # endpoint and a row from a balance endpoint can contribute to one record
    # only when their issuer and period match exactly.
    periods: dict[tuple[str, tuple[int, int]], dict[str, Any]] = {}
    endpoint_hashes: dict[str, str] = {}
    for result in fetched:
        endpoint_hashes[result["endpoint"]] = result["source_sha256"]
        for raw_row in result["rows"]:
            ticker = str(field(raw_row, "公司代號", "CompanyCode", "Code") or "").strip()
            period_info = _twse_period(raw_row)
            if ticker not in wanted or period_info is None:
                continue
            year, quarter, period = period_info
            key = (ticker, (year, quarter))
            target = periods.setdefault(key, {
                "ticker": ticker, "name": field(raw_row, "公司名稱", "CompanyName") or ticker,
                "reporting_period": period, "fiscal_year": year, "quarter": quarter,
                "period_end": f"{year:04d}-{quarter * 3:02d}-{(31 if quarter in {1, 4} else 30):02d}T00:00:00+00:00",
                "first_seen_at": datetime.now(UTC).isoformat(),
                "filing_date": _twse_date(field(raw_row, "出表日期", "資料日期", "Date")),
                "source_endpoints": [], "source_urls": [], "source_hashes": [],
            })
            target["name"] = target.get("name") or field(raw_row, "公司名稱", "CompanyName") or ticker
            target["source_endpoints"].append(result["endpoint"])
            target["source_urls"].append(f"{TWSE_BASE}/{result['endpoint']}")
            target["source_hashes"].append(result["source_sha256"])
            target["source_url"] = target["source_urls"][0]
            eps = _finite_number(field(raw_row, *TWSE_EPS_FIELDS))
            parent_net = _finite_number(field(raw_row, *TWSE_PARENT_NET_FIELDS))
            parent_equity = _finite_number(field(raw_row, *TWSE_PARENT_EQUITY_FIELDS))
            if eps is not None:
                target["eps_ytd"] = eps
                target["eps_field"] = next(name for name in TWSE_EPS_FIELDS if name in raw_row)
            if parent_net is not None:
                target["parent_net_income_ytd"] = parent_net * 1000
                target["parent_net_income_field"] = next(name for name in TWSE_PARENT_NET_FIELDS if name in raw_row)
            if parent_equity is not None:
                target["parent_equity"] = parent_equity * 1000
                target["parent_equity_field"] = next(name for name in TWSE_PARENT_EQUITY_FIELDS if name in raw_row)

    latest: dict[str, dict[str, Any]] = {}
    for (ticker, _period_key), period_record in periods.items():
        current = latest.get(ticker)
        if current is None or (period_record["fiscal_year"], period_record["quarter"]) > (current["fiscal_year"], current["quarter"]):
            latest[ticker] = period_record
    now = datetime.now(UTC)
    cache_payload = _twse_cache_load(Path(cache_path) if cache_path else None)
    cache_records = cache_payload.get("records", {}) if isinstance(cache_payload.get("records"), dict) else {}
    output: dict[str, dict[str, Any]] = {}
    cache_used = 0
    for ticker in sorted(wanted):
        record: dict[str, Any] | None = latest.get(ticker)
        if record is None or any(record.get(key) is None for key in ("eps_ytd", "parent_net_income_ytd", "parent_equity")):
            cached = cache_records.get(ticker)
            if isinstance(cached, dict) and _twse_cache_record_valid(cached, now=now, expected_period=expected_period):
                record = dict(cached)
                record["financial_source"] = "TWSE official batch (bounded cache)"
                record["cache_used"] = True
                cache_used += 1
            else:
                if record is None:
                    continue
        if expected_period and record.get("reporting_period") != expected_period:
            continue
        eps = _finite_number(record.get("eps_ytd"))
        parent_net = _finite_number(record.get("parent_net_income_ytd"))
        parent_equity = _finite_number(record.get("parent_equity"))
        quarter = int(record.get("quarter") or 0)
        quality_ratio = None if parent_net is None or parent_equity is None or parent_equity <= 0 or quarter <= 0 else parent_net * 4 / quarter / parent_equity
        if parent_equity is None or parent_net is None or quarter <= 0:
            quality_pass: bool | None = None
        elif parent_equity <= 0:
            quality_pass = False
        else:
            assert quality_ratio is not None
            quality_pass = quality_ratio >= 0.17
        record.update({
            "eps_ytd": eps, "parent_net_income_ytd": parent_net, "parent_equity": parent_equity,
            "annualized_quality_ratio": quality_ratio,
            "current_eps_positive": None if eps is None else eps > 0,
            "current_quality_pass": quality_pass,
            "quality_rule_version": TW_VALUE_RULE_VERSION,
            "parameter_hash": TW_VALUE_PARAMETER_HASH,
            "quality_basis": "同年度累計歸屬母公司淨利×4÷季別÷同季末歸屬母公司權益",
            "net_income": parent_net, "roe": quality_ratio,
            "pe": None, "roe_basis": "年化獲利／期末權益估算（非全年 ROE）",
            "financial_source": record.get("financial_source") or "TWSE official batch",
            "financial_parse_version": TWSE_FINANCIAL_PARSE_VERSION,
            "parse_version": TWSE_FINANCIAL_PARSE_VERSION,
            "calculation_basis": "parent_net_income_ytd × 4 ÷ quarter ÷ parent_equity",
            "source_sha256": record.get("source_sha256") or hashlib.sha256(
                "|".join(sorted(set(record.get("source_hashes", [])))).encode("utf-8")
            ).hexdigest(),
            "last_checked_at": record.get("last_checked_at") or now.isoformat(),
            "amount_unit": "TWD_thousands_normalized_to_TWD",
            "three_year_eps_positive": None,
            "four_quarter_eps_positive": None,
            "three_year_dividend_paid": None,
        })
        output[ticker] = record

    diagnostics = {
        "rule_version": TW_VALUE_RULE_VERSION,
        "parse_version": TWSE_FINANCIAL_PARSE_VERSION,
        "requested_tickers": len(wanted),
        "valid_records": len(output),
        "endpoint_count": len(endpoints),
        "successful_endpoint_count": len(fetched),
        "endpoint_errors": sorted(endpoint_errors),
        "endpoint_hashes": endpoint_hashes,
        "cache_used_count": cache_used,
        "mops_calls": 0,
        "mops_history_used": False,
    }
    cache_records_out = {ticker: dict(record) for ticker, record in cache_records.items() if isinstance(record, dict)}
    cache_records_out.update({ticker: {
        **record, "last_checked_at": record.get("last_checked_at") or now.isoformat(),
        "parse_version": TWSE_FINANCIAL_PARSE_VERSION,
    } for ticker, record in output.items() if not record.get("cache_used")})
    cache_error = _twse_cache_save(Path(cache_path) if cache_path else None, cache_records_out, diagnostics)
    diagnostics["cache_saved"] = cache_error is None if cache_path else False
    diagnostics["cache_write_error"] = cache_error
    errors = list(endpoint_errors)
    if cache_error:
        errors.append(f"TWSE cache save: {cache_error}")
    return output, errors, diagnostics


def twse_financial_snapshot(
    tickers: Iterable[str], session: requests.Session | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Backward-compatible wrapper for callers that only need latest metrics."""
    output, errors, _diagnostics = twse_current_quality_snapshot(tickers, session=session)
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
    mapping_failed_without_fallback = False
    cache_changed = False
    for ticker in ticker_list:
        ticker_key = ticker.upper()
        cik = overrides.get(ticker_key) or ciks.get(ticker_key)
        if cik is None:
            # The SEC ticker mapping endpoint is an external dependency and
            # can temporarily return 403/429 or omit a recently changed
            # listing.  A recent cache entry already contains the immutable
            # CIK used to fetch its CompanyFacts payload; use that identity
            # before declaring the row unavailable.  This keeps a transient
            # mapping outage from suppressing the entire US value scan while
            # preserving the freshness gate on the cached fundamentals.
            cached_identity = cache.get(ticker_key)
            cached_cik = cached_identity.get("cik") if isinstance(cached_identity, dict) else None
            if str(cached_cik or "").isdigit():
                cik = int(str(cached_cik))
        if cik is None:
            mapping_failed_without_fallback = bool(mapping_error)
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
    if mapping_error and mapping_failed_without_fallback:
        errors.insert(0, mapping_error)
    if cache_file and cache_changed:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return output, errors
