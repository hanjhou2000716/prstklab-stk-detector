"""Public MOPS history reader used by the Taiwan Pristine Value screen.

The MOPS web application exposes legacy public-report endpoints behind its
``redirectToOld`` route.  This module uses that documented public flow, keeps
only the derived eligibility observations, and caches them so a daily screen
does not repeatedly request the same historical filings.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable

from bs4 import BeautifulSoup
import requests


MOPS_API = "https://mops.twse.com.tw/mops/api/redirectToOld"
MOPS_OLD = "https://mopsov.twse.com.tw/mops/web"
USER_AGENT = "Mozilla/5.0 (compatible; PRStK-Lab-public-research/1.0)"
CACHE_SCHEMA = 2
CACHE_MAX_AGE_DAYS = 14
# Temporarily failing MOPS pages must not pin every later scheduled batch.
FAILURE_RETRY_HOURS = 6
REQUEST_RETRIES = 2
REQUEST_BACKOFF_SECONDS = 0.75


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace(" ", "").strip()
    if cleaned in {"", "-", "--", "不適用"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    return [
        [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        for row in soup.find_all("tr")
    ]


def parse_eps_report(html: str) -> tuple[float | None, float | None]:
    """Return current/prior basic EPS from a MOPS quarterly income statement."""
    for cells in _rows(html):
        label = " ".join(cells)
        if "基本每股盈餘" not in label:
            continue
        values: list[float] = []
        for cell in cells:
            value = _number(cell)
            if value is not None:
                values.append(value)
        if len(values) >= 2:
            return values[-2], values[-1]
    # MOPS occasionally nests the EPS cells outside a regular table row.
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    match = re.search(r"基本每股盈餘\s+(-?[\d,.]+)\s+(-?[\d,.]+)", text)
    if match:
        return _number(match.group(1)), _number(match.group(2))
    return None, None


def parse_net_income_report(html: str) -> tuple[float | None, float | None]:
    """Return current/prior net income in NTD from a MOPS income statement."""
    candidates: list[tuple[float, float]] = []
    for cells in _rows(html):
        label = " ".join(cells)
        if "本期淨利" not in label or "歸屬於" in label:
            continue
        values = [value for cell in cells if (value := _number(cell)) is not None]
        # IFRS income rows interleave amount and percentage cells.  MOPS uses
        # thousands of NTD, so the two report amounts are the significant
        # values; percentages must not be mistaken for the prior-year income.
        amounts = [value for value in values if abs(value) >= 1_000]
        if len(amounts) >= 2:
            candidates.append((amounts[0] * 1000, amounts[1] * 1000))
    return candidates[-1] if candidates else (None, None)


def parse_equity_report(html: str) -> tuple[float | None, float | None]:
    """Return current/prior equity from a MOPS quarterly balance sheet."""
    labels = ("權益總額", "權益合計", "權益總計")
    for cells in _rows(html):
        if not any(label in " ".join(cells) for label in labels):
            continue
        values = [value for cell in cells if (value := _number(cell)) is not None]
        amounts = [value for value in values if abs(value) >= 1_000]
        if len(amounts) >= 2:
            return amounts[0] * 1000, amounts[1] * 1000
    return None, None


def parse_dividend_history(html: str) -> dict[int, bool]:
    """Read annual dividend presence from MOPS board-resolution disclosures.

    MOPS may show several quarterly resolutions for the same dividend year.
    A year passes when any shareholder cash/stock dividend field is positive.
    """
    output: dict[int, bool] = {}
    for cells in _rows(html):
        if not cells or not re.fullmatch(r"\d{2,3}", cells[0].strip()):
            continue
        year = int(cells[0])
        # In t05st09_1, shareholder-dividend per-share fields begin after the
        # meeting/resolution columns.  Restricting to that block avoids treating
        # retained earnings or employee bonuses as shareholder dividends.
        dividend_cells = cells[8:13] if len(cells) >= 9 else cells[3:6]
        paid = any((value or 0) > 0 for cell in dividend_cells if (value := _number(cell)) is not None)
        output[year] = output.get(year, False) or paid
    return output


class MopsPublicClient:
    """Minimal, session-aware client for public MOPS report pages."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        # requests installs its own default UA, so setdefault would leave it in
        # place and MOPS would return a security-block page instead of JSON.
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers.setdefault("Accept-Language", "zh-TW,zh;q=0.9,en;q=0.7")

    def report(self, api_name: str, company_id: str, **parameters: str | int) -> str:
        last_error: Exception | None = None
        for attempt in range(REQUEST_RETRIES):
            try:
                return self._report_once(api_name, company_id, parameters)
            except (OSError, ValueError, requests.RequestException, RuntimeError) as error:
                last_error = error
                # The redirect endpoint is intermittently rate-limited or
                # returns an HTML security page from hosted CI.  The same
                # public report remains available through the legacy MOPS
                # endpoint, so try it before spending the next retry window.
                try:
                    return self._legacy_report_once(api_name, company_id, parameters)
                except (OSError, ValueError, requests.RequestException, RuntimeError) as fallback_error:
                    last_error = fallback_error
                if attempt + 1 < REQUEST_RETRIES:
                    time.sleep(REQUEST_BACKOFF_SECONDS * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _report_once(self, api_name: str, company_id: str, parameters: dict[str, str | int]) -> str:
        response = self.session.post(
            MOPS_API,
            json={"apiName": api_name, "parameters": {"companyId": company_id, **parameters}},
            timeout=30,
        )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as error:
            raise RuntimeError(f"MOPS {api_name} returned non-JSON response") from error
        url = body.get("result", {}).get("url") if isinstance(body, dict) else None
        if not url:
            raise RuntimeError(f"MOPS {api_name} did not return a report URL")
        # MOPS sets a short-lived session cookie on the report landing page.
        landing = self.session.get(url, timeout=30)
        landing.raise_for_status()
        form: dict[str, str] = {
            "encodeURIComponent": "1", "step": "1", "firstin": "true", "off": "1",
            "keyword4": "", "code1": "", "TYPEK2": "", "checkbtn": "",
            "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "isnew": "false",
            "co_id": company_id,
        }
        if api_name in {"t164sb04", "t164sb03"}:
            form.update({"year": str(parameters["year"]), "season": f"{int(parameters['season']):02d}"})
        elif api_name == "t05st09_1":
            form["year"] = ""
        else:
            raise ValueError(f"Unsupported MOPS report: {api_name}")
        report = self.session.post(
            f"{MOPS_OLD}/ajax_{api_name}", data=form,
            headers={"Referer": url, "X-Requested-With": "XMLHttpRequest", "Origin": "https://mopsov.twse.com.tw"},
            timeout=45,
        )
        report.raise_for_status()
        text = report.content.decode("utf-8", errors="replace")
        if "FOR SECURITY REASONS" in text:
            raise RuntimeError(f"MOPS security block for {api_name}")
        return text

    def _legacy_report_once(
        self,
        api_name: str,
        company_id: str,
        parameters: dict[str, str | int],
    ) -> str:
        """Fetch a public MOPS report without the redirect/session hop."""
        form: dict[str, str] = {
            "encodeURIComponent": "1", "step": "1", "firstin": "true", "off": "1",
            "keyword4": "", "code1": "", "TYPEK2": "", "checkbtn": "",
            "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "isnew": "false",
            "co_id": company_id,
        }
        if api_name in {"t164sb04", "t164sb03"}:
            form.update({"year": str(parameters["year"]), "season": f"{int(parameters['season']):02d}"})
        elif api_name == "t05st09_1":
            form["year"] = ""
        else:
            raise ValueError(f"Unsupported MOPS report: {api_name}")
        response = self.session.post(
            f"{MOPS_OLD}/ajax_{api_name}",
            data=form,
            headers={
                "Referer": "https://mops.twse.com.tw/",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://mopsov.twse.com.tw",
            },
            timeout=45,
        )
        response.raise_for_status()
        text = response.content.decode("utf-8", errors="replace")
        if "FOR SECURITY REASONS" in text:
            raise RuntimeError(f"MOPS security block for {api_name}")
        if not text.strip():
            raise RuntimeError(f"MOPS {api_name} legacy endpoint returned empty response")
        return text


def _recent_periods(roc_year: int) -> list[tuple[int, int]]:
    """Enough reporting periods for latest four quarters and three fiscal years."""
    periods: list[tuple[int, int]] = []
    year, quarter = roc_year, 4
    for _ in range(9):
        periods.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return periods


def fetch_pristine_history(
    ticker: str, *, client: MopsPublicClient | None = None, as_of: date | None = None,
) -> dict[str, Any]:
    """Fetch the strict MOPS history required for one Taiwan candidate."""
    client = client or MopsPublicClient()
    roc_year = (as_of or date.today()).year - 1911
    quarterly: dict[tuple[int, int], float] = {}
    annual: dict[int, float] = {}

    # Work backwards: missing future filings are normal, not substituted.
    for year, quarter in _recent_periods(roc_year):
        report = client.report("t164sb04", ticker, year=year, season=quarter, dataType="2")
        current, prior = parse_eps_report(report)
        if current is not None:
            quarterly[(year, quarter)] = current
            if quarter == 4:
                annual[year] = current
        if prior is not None:
            quarterly[(year - 1, quarter)] = prior
            if quarter == 4:
                annual[year - 1] = prior
        if len(quarterly) >= 4 and len(annual) >= 3:
            break
        time.sleep(0.08)

    dividends = parse_dividend_history(client.report("t05st09_1", ticker))
    annual_years = sorted(annual, reverse=True)[:3]
    quarter_values = [value for _, value in sorted(quarterly.items(), reverse=True)[:4]]
    dividend_years = sorted(dividends, reverse=True)[:3]
    return {
        "three_year_eps_positive": len(annual_years) >= 3 and all(annual[year] > 0 for year in annual_years),
        "four_quarter_eps_positive": len(quarter_values) >= 4 and all(value > 0 for value in quarter_values),
        "three_year_dividend_paid": len(dividend_years) >= 3 and all(dividends[year] for year in dividend_years),
        # Current ROE remains sourced from the TWSE latest filing.  A future
        # balance-sheet history enhancement may replace this with a three-year
        # ROE stability check, but it must not be fabricated meanwhile.
        "roe_stable": None,
        "annual_eps_years": annual_years,
        "quarter_eps_count": len(quarter_values),
        "dividend_years": dividend_years,
        "roe_years": 0,
        "financial_source": "MOPS historical filings (t164sb04/t05st09_1)",
        "history_checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") in {1, CACHE_SCHEMA} and isinstance(data.get("records"), dict):
            return {
                "schema": CACHE_SCHEMA,
                "records": data["records"],
                "failures": data.get("failures", {}) if isinstance(data.get("failures", {}), dict) else {},
            }
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return {"schema": CACHE_SCHEMA, "records": {}, "failures": {}}


def _fresh(record: dict[str, Any], now: datetime) -> bool:
    try:
        checked = datetime.fromisoformat(str(record["history_checked_at"]).replace("Z", "+00:00"))
        return checked >= now - timedelta(days=CACHE_MAX_AGE_DAYS)
    except (KeyError, TypeError, ValueError):
        return False


def _retry_due(failure: dict[str, Any], now: datetime) -> bool:
    """Avoid retrying a transient MOPS outage before unseen companies."""
    try:
        attempted_at = datetime.fromisoformat(str(failure["attempted_at"]).replace("Z", "+00:00"))
        return attempted_at <= now - timedelta(hours=FAILURE_RETRY_HOURS)
    except (KeyError, TypeError, ValueError):
        return True


def mops_pristine_history(
    tickers: Iterable[str], cache_path: Path, *, max_refresh: int = 0,
    client: MopsPublicClient | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return cached/verified MOPS eligibility observations for a ticker set.

    ``max_refresh=0`` means complete the requested universe. A non-zero value
    caps *attempts* (not only successful downloads), so a slow or failing MOPS
    report cannot consume the scheduled full-market time budget.
    """
    cache = _load_cache(cache_path)
    records: dict[str, dict[str, Any]] = cache["records"]
    failures: dict[str, dict[str, Any]] = cache["failures"]
    now = datetime.now(timezone.utc)
    errors: list[str] = []
    attempted = 0
    client = client or MopsPublicClient()
    ordered_tickers = list(dict.fromkeys(str(value).strip() for value in tickers if str(value).strip()))
    pending = [
        ticker for ticker in ordered_tickers
        if not (isinstance(records.get(ticker), dict) and _fresh(records[ticker], now))
    ]
    # New tickers first; cooled-down failures second; recent failures are
    # skipped until their retry window.  This guarantees each run advances.
    pending.sort(key=lambda ticker: (0 if ticker not in failures else (1 if _retry_due(failures[ticker], now) else 2), ticker))
    for ticker in pending:
        previous_failure = failures.get(ticker)
        if isinstance(previous_failure, dict) and not _retry_due(previous_failure, now):
            continue
        if max_refresh and attempted >= max_refresh:
            break
        attempted += 1
        try:
            records[ticker] = fetch_pristine_history(ticker, client=client)
            failures.pop(ticker, None)
        except (OSError, ValueError, requests.RequestException, RuntimeError) as error:
            errors.append(f"{ticker} MOPS history: {type(error).__name__}")
            failures[ticker] = {
                "attempted_at": now.isoformat(),
                "error": type(error).__name__,
                "attempts": int(previous_failure.get("attempts", 0)) + 1 if isinstance(previous_failure, dict) else 1,
            }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return {ticker: records[ticker] for ticker in tickers if ticker in records}, errors
