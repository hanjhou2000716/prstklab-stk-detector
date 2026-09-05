"""Public MOPS history reader used by the Taiwan Pristine Value screen.

The MOPS web application exposes legacy public-report endpoints behind its
``redirectToOld`` route.  This module uses that documented public flow, keeps
only the derived eligibility observations, and caches them so a daily screen
does not repeatedly request the same historical filings.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.http_client import configure_public_source_tls

MOPS_API = "https://mops.twse.com.tw/mops/api/redirectToOld"
MOPS_OLD = "https://mopsov.twse.com.tw/mops/web"
USER_AGENT = "Mozilla/5.0 (compatible; PRStK-Lab-public-research/1.0)"
CACHE_SCHEMA = 3
CACHE_MAX_AGE_DAYS = 14
# Temporarily failing MOPS pages must not pin every later scheduled batch.
FAILURE_RETRY_HOURS = 6
REQUEST_RETRIES = 2
# MOPS intermittently throttles bursty CI traffic.  Keep retries bounded, but
# pace the historical report requests so one batch does not look like a scrape.
REQUEST_BACKOFF_SECONDS = 1.25
REPORT_INTERVAL_SECONDS = 0.35
# Hosted CI addresses are more likely to receive a temporary MOPS security
# page when several report forms are submitted in one burst.  Keep a small
# inter-request interval and rotate the session after a blocked response;
# this is still bounded and does not bypass rate limits.
MIN_REQUEST_INTERVAL_SECONDS = 0.8
# A security page is a provider-side throttle, not a normal parse failure.
# Give the WAF time to release the session before trying the legacy route and
# again before the next attempt.  This remains bounded and does not bypass
# rate limits; it only makes production retries less bursty.
SECURITY_BLOCK_BACKOFF_SECONDS = 8.0


class IncompleteMopsHistoryError(RuntimeError):
    """The public reports were reachable but did not cover the required window."""

    def __init__(self, ticker: str, record: dict[str, Any]) -> None:
        self.ticker = ticker
        self.record = record
        super().__init__(f"MOPS history incomplete for {ticker}")


class MopsDeadlineExceeded(RuntimeError):
    """The shared research-worker deadline was reached before a request finished."""


def _is_missing_report(error: Exception) -> bool:
    """Return whether MOPS simply has no report for a requested period.

    A future quarter (or a company without a legacy report) is not a provider
    outage.  It must not abort the whole ticker's historical walk, while a
    security block, timeout, or connection error must still fail closed.
    """
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "did not return a report url",
            "legacy endpoint returned empty response",
        )
    )


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
        self.session = configure_public_source_tls(session)
        self._last_request_at = 0.0
        self._session_factory = lambda: configure_public_source_tls()
        # requests installs its own default UA, so setdefault would leave it in
        # place and MOPS would return a security-block page instead of JSON.
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers.setdefault("Accept-Language", "zh-TW,zh;q=0.9,en;q=0.7")

    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MopsDeadlineExceeded("MOPS research deadline exceeded")
        return remaining

    def _pace(self, deadline: float | None = None) -> None:
        remaining = self._remaining(deadline)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            pause = MIN_REQUEST_INTERVAL_SECONDS - elapsed
            if remaining is not None and pause >= remaining:
                raise MopsDeadlineExceeded("MOPS research deadline exceeded while pacing")
            time.sleep(pause)
        self._last_request_at = time.monotonic()

    def _rotate_session(self) -> None:
        """Start a clean public session after a provider security page.

        MOPS uses short-lived cookies and can attach a block to one session.
        Rotating only after a failed request avoids retaining a poisoned
        cookie jar while keeping request volume bounded.
        """
        session = self._session_factory()
        session.headers["User-Agent"] = USER_AGENT
        session.headers.setdefault("Accept-Language", "zh-TW,zh;q=0.9,en;q=0.7")
        self.session = session

    @staticmethod
    def _is_security_block(error: Exception) -> bool:
        return "security block" in str(error).lower()

    def report(self, api_name: str, company_id: str, **parameters: str | int | float | None) -> str:
        deadline = parameters.pop("deadline", None)
        deadline_value = float(deadline) if deadline is not None else None
        last_error: Exception | None = None
        for attempt in range(REQUEST_RETRIES):
            try:
                self._pace(deadline_value)
                return self._report_once(api_name, company_id, parameters, deadline=deadline_value)
            except MopsDeadlineExceeded:
                raise
            except (OSError, ValueError, requests.RequestException, RuntimeError) as error:
                last_error = error
                # The redirect endpoint is intermittently rate-limited or
                # returns an HTML security page from hosted CI.  The same
                # public report remains available through the legacy MOPS
                # endpoint, so try it before spending the next retry window.
                if self._is_security_block(error):
                    self._deadline_sleep(SECURITY_BLOCK_BACKOFF_SECONDS, deadline_value)
                try:
                    self._pace(deadline_value)
                    return self._legacy_report_once(api_name, company_id, parameters, deadline=deadline_value)
                except MopsDeadlineExceeded:
                    raise
                except (OSError, ValueError, requests.RequestException, RuntimeError) as fallback_error:
                    last_error = fallback_error
                    self._rotate_session()
                    if self._is_security_block(fallback_error):
                        self._deadline_sleep(SECURITY_BLOCK_BACKOFF_SECONDS, deadline_value)
                if attempt + 1 < REQUEST_RETRIES:
                    self._deadline_sleep(REQUEST_BACKOFF_SECONDS * (attempt + 1), deadline_value)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _deadline_sleep(seconds: float, deadline: float | None) -> None:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or seconds >= remaining:
                raise MopsDeadlineExceeded("MOPS research deadline exceeded while waiting")
        time.sleep(seconds)

    @staticmethod
    def _timeout(default: float, deadline: float | None) -> float:
        if deadline is None:
            return default
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MopsDeadlineExceeded("MOPS research deadline exceeded before request")
        return max(0.5, min(default, remaining))

    def _report_once(
        self, api_name: str, company_id: str, parameters: dict[str, str | int | float | None], *, deadline: float | None = None,
    ) -> str:
        response = self.session.post(
            MOPS_API,
            json={"apiName": api_name, "parameters": {"companyId": company_id, **parameters}},
            timeout=self._timeout(30, deadline),
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
        landing = self.session.get(url, timeout=self._timeout(30, deadline))
        landing.raise_for_status()
        form: dict[str, str] = {
            "encodeURIComponent": "1", "step": "1", "firstin": "true", "off": "1",
            "keyword4": "", "code1": "", "TYPEK2": "", "checkbtn": "",
            "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "isnew": "false",
            "co_id": company_id,
        }
        if api_name in {"t164sb04", "t164sb03"}:
            form.update({"year": str(parameters["year"]), "season": f"{int(str(parameters['season'])):02d}"})
        elif api_name == "t05st09_1":
            # Query one ROC fiscal year at a time.  An explicit "查無資料"
            # response is a valid zero-dividend observation, not a provider
            # outage or an incomplete history record.
            form["year"] = str(parameters.get("year") or "")
        else:
            raise ValueError(f"Unsupported MOPS report: {api_name}")
        report = self.session.post(
            f"{MOPS_OLD}/ajax_{api_name}", data=form,
            headers={"Referer": url, "X-Requested-With": "XMLHttpRequest", "Origin": "https://mopsov.twse.com.tw"},
            timeout=self._timeout(45, deadline),
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
        parameters: dict[str, str | int | float | None],
        *,
        deadline: float | None = None,
    ) -> str:
        """Fetch a public MOPS report without the redirect/session hop."""
        form: dict[str, str] = {
            "encodeURIComponent": "1", "step": "1", "firstin": "true", "off": "1",
            "keyword4": "", "code1": "", "TYPEK2": "", "checkbtn": "",
            "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "isnew": "false",
            "co_id": company_id,
        }
        if api_name in {"t164sb04", "t164sb03"}:
            form.update({"year": str(parameters["year"]), "season": f"{int(str(parameters['season'])):02d}"})
        elif api_name == "t05st09_1":
            form["year"] = str(parameters.get("year") or "")
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
            timeout=self._timeout(45, deadline),
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
    deadline: float | None = None, progress: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fetch the strict MOPS history required for one Taiwan candidate."""
    client = client or MopsPublicClient()
    progress = progress if isinstance(progress, dict) else {}
    roc_year = (as_of or date.today()).year - 1911
    quarterly: dict[tuple[int, int], float] = {}
    annual: dict[int, float] = {}
    missing_periods: list[str] = []

    def progress_key(api_name: str, parameters: dict[str, str | int | float | None]) -> str:
        stable_parameters = {key: value for key, value in parameters.items() if key != "deadline"}
        return f"{ticker}|{api_name}|{json.dumps(stable_parameters, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"

    def mark_progress(
        api_name: str, parameters: dict[str, str | int | float | None], status: str, **values: Any,
    ) -> None:
        stable_parameters = {key: value for key, value in parameters.items() if key != "deadline"}
        entry = {
            "ticker": ticker,
            "api_name": api_name,
            "parameters": stable_parameters,
            "status": status,
            "checked_at": datetime.now(UTC).isoformat(),
            **values,
        }
        progress[progress_key(api_name, parameters)] = entry
        if progress_callback is not None:
            progress_callback(entry)

    def cached_period(api_name: str, parameters: dict[str, str | int | float | None]) -> dict[str, Any] | None:
        entry = progress.get(progress_key(api_name, parameters))
        if not isinstance(entry, dict) or entry.get("status") not in {"verified", "missing"}:
            return None
        expected = {key: value for key, value in parameters.items() if key != "deadline"}
        if entry.get("parameters") != expected:
            return None
        return entry

    # Work backwards: missing future filings are normal, not substituted.
    for year, quarter in _recent_periods(roc_year):
        if deadline is not None and time.monotonic() >= deadline:
            raise MopsDeadlineExceeded(f"MOPS history deadline exceeded for {ticker}")
        parameters: dict[str, str | int | float | None] = {"year": year, "season": quarter, "dataType": "2"}
        cached = cached_period("t164sb04", parameters)
        if cached is not None:
            current = cached.get("current")
            prior = cached.get("prior")
            if isinstance(current, (int, float)):
                quarterly[(year, quarter)] = float(current)
                if quarter == 4:
                    annual[year] = float(current)
            if isinstance(prior, (int, float)):
                quarterly[(year - 1, quarter)] = float(prior)
                if quarter == 4:
                    annual[year - 1] = float(prior)
            if cached.get("status") == "missing":
                missing_periods.append(f"{year}Q{quarter}")
            if len(quarterly) >= 4 and len(annual) >= 3:
                break
            continue
        try:
            if deadline is not None:
                parameters["deadline"] = deadline
            report = client.report("t164sb04", ticker, **parameters)
        except (RuntimeError, ValueError) as error:
            # MOPS normally has no current-year Q4 report yet.  Continue to
            # older periods; only a security/transport failure should abort.
            if _is_missing_report(error):
                missing_periods.append(f"{year}Q{quarter}")
                mark_progress("t164sb04", parameters, "missing")
                continue
            mark_progress("t164sb04", parameters, "failed", error_class=type(error).__name__, detail=str(error)[:240])
            raise
        current, prior = parse_eps_report(report)
        mark_progress("t164sb04", parameters, "verified", current=current, prior=prior)
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
        if deadline is not None and time.monotonic() + REPORT_INTERVAL_SECONDS >= deadline:
            raise MopsDeadlineExceeded(f"MOPS history deadline exceeded for {ticker}")
        time.sleep(REPORT_INTERVAL_SECONDS)

    # The unscoped dividend endpoint commonly returns only the latest two
    # rows.  Query each required fiscal year explicitly so a "查無資料"
    # response can be recorded as a real no-dividend result rather than
    # incorrectly blocking the entire production universe.
    dividend_results: dict[int, bool] = {}
    dividend_history_years = [roc_year - offset for offset in range(3)]
    for dividend_year in dividend_history_years:
        if deadline is not None and time.monotonic() >= deadline:
            raise MopsDeadlineExceeded(f"MOPS history deadline exceeded for {ticker}")
        dividend_parameters: dict[str, str | int | float | None] = {"year": dividend_year}
        cached_dividend = cached_period("t05st09_1", dividend_parameters)
        if cached_dividend is not None:
            dividend_results[dividend_year] = bool(cached_dividend.get("paid"))
            continue
        try:
            if deadline is not None:
                dividend_parameters["deadline"] = deadline
            dividend_report = client.report("t05st09_1", ticker, **dividend_parameters)
            dividend_results[dividend_year] = bool(parse_dividend_history(dividend_report).get(dividend_year, False))
            mark_progress("t05st09_1", dividend_parameters, "verified", paid=dividend_results[dividend_year])
        except (RuntimeError, ValueError) as error:
            # Unlike a year-specific HTML page containing "查無資料", an
            # endpoint/transport failure is not evidence of zero dividend.
            # Preserve fail-closed semantics by letting the ticker fail and
            # retry on the next batch.
            mark_progress("t05st09_1", dividend_parameters, "failed", error_class=type(error).__name__, detail=str(error)[:240])
            raise
    annual_years = sorted(annual, reverse=True)[:3]
    quarter_values = [value for _, value in sorted(quarterly.items(), reverse=True)[:4]]
    dividend_years = [year for year in dividend_history_years if dividend_results.get(year, False)]
    history_data_complete = (
        len(annual_years) >= 3
        and len(quarter_values) >= 4
        and all(year in dividend_results for year in dividend_history_years)
    )
    return {
        "three_year_eps_positive": len(annual_years) >= 3 and all(annual[year] > 0 for year in annual_years),
        "four_quarter_eps_positive": len(quarter_values) >= 4 and all(value > 0 for value in quarter_values),
        "three_year_dividend_paid": history_data_complete and all(dividend_results[year] for year in dividend_history_years),
        # Current ROE remains sourced from the TWSE latest filing.  A future
        # balance-sheet history enhancement may replace this with a three-year
        # ROE stability check, but it must not be fabricated meanwhile.
        "roe_stable": None,
        "annual_eps_years": annual_years,
        "quarter_eps_count": len(quarter_values),
        "dividend_years": dividend_years,
        "dividend_history_years": dividend_history_years,
        "roe_years": 0,
        "financial_source": "MOPS historical filings (t164sb04/t05st09_1)",
        "history_checked_at": datetime.now(UTC).isoformat(),
        "history_data_complete": history_data_complete,
        "missing_periods": missing_periods,
    }


def _load_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") in {1, 2, CACHE_SCHEMA} and isinstance(data.get("records"), dict):
            return {
                "schema": CACHE_SCHEMA,
                "records": data["records"],
                "failures": data.get("failures", {}) if isinstance(data.get("failures", {}), dict) else {},
                "progress": data.get("progress", {}) if isinstance(data.get("progress", {}), dict) else {},
            }
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return {"schema": CACHE_SCHEMA, "records": {}, "failures": {}, "progress": {}}


def _save_cache(
    path: Path, records: dict[str, Any], failures: dict[str, Any], progress: dict[str, Any] | None = None,
) -> None:
    """Persist incremental MOPS progress without exposing a partial JSON file.

    A hosted research worker can be terminated by its bounded timeout while a
    single ticker is still being fetched.  Saving only after the complete
    batch would discard every ticker processed before that timeout and make
    the next scheduled run start over.  Write after each ticker attempt via a
    sibling temporary file, then atomically replace the cache so an
    interruption can leave either the previous complete cache or the newest
    complete snapshot, never truncated JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = {"schema": CACHE_SCHEMA, "records": records, "failures": failures, "progress": progress or {}}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


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
    client: MopsPublicClient | None = None, deadline: float | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return cached/verified MOPS eligibility observations for a ticker set.

    ``max_refresh=0`` means complete the requested universe, including retrying
    previously failed records. A non-zero value caps *attempts* (not only
    successful downloads), so a slow or failing MOPS report cannot consume the
    scheduled full-market time budget. This distinction matters for production:
    a zero limit must not silently skip records in the six-hour retry cooldown,
    otherwise the release can remain ``building`` forever even when the next
    run has enough time to verify the pool.
    """
    cache = _load_cache(cache_path)
    records: dict[str, dict[str, Any]] = cache["records"]
    failures: dict[str, dict[str, Any]] = cache["failures"]
    progress: dict[str, Any] = cache.get("progress", {}) if isinstance(cache.get("progress", {}), dict) else {}
    now = datetime.now(UTC)
    errors: list[str] = []
    attempted = 0
    client = client or MopsPublicClient()
    progress_save_failed = False

    def persist() -> bool:
        nonlocal progress_save_failed
        try:
            _save_cache(cache_path, records, failures, progress)
        except OSError:
            errors.append("cache: write_failed")
            progress_save_failed = True
            return False
        return True

    def persist_period(entry: dict[str, Any]) -> None:
        progress_key = f"{entry.get('ticker', '')}|{entry.get('api_name', '')}|{json.dumps(entry.get('parameters', {}), ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        progress[progress_key] = entry
        persist()

    ordered_tickers = list(dict.fromkeys(str(value).strip() for value in tickers if str(value).strip()))
    pending = [
        ticker for ticker in ordered_tickers
        if not (isinstance(records.get(ticker), dict) and _fresh(records[ticker], now))
    ]
    # New tickers first; cooled-down failures second; recent failures are
    # skipped until their retry window.  This guarantees each run advances.
    pending.sort(key=lambda ticker: (0 if ticker not in failures else (1 if _retry_due(failures[ticker], now) else 2), ticker))
    for ticker in pending:
        if deadline is not None and time.monotonic() >= deadline:
            break
        previous_failure = failures.get(ticker)
        if max_refresh and isinstance(previous_failure, dict) and not _retry_due(previous_failure, now):
            continue
        if max_refresh and attempted >= max_refresh:
            break
        attempted += 1
        try:
            if deadline is None:
                try:
                    record = fetch_pristine_history(
                        ticker, client=client, progress=progress, progress_callback=persist_period,
                    )
                except TypeError as error:
                    if "unexpected keyword argument" not in str(error):
                        raise
                    # Keep compatibility with injected legacy test/worker adapters.
                    record = fetch_pristine_history(ticker, client=client)
            else:
                record = fetch_pristine_history(
                    ticker, client=client, deadline=deadline, progress=progress,
                    progress_callback=persist_period,
                )
            if progress_save_failed:
                raise OSError("cache_write_failed")
            if not record.get("history_data_complete"):
                raise IncompleteMopsHistoryError(ticker, record)
            records[ticker] = record
            failures.pop(ticker, None)
            # Persist each verified ticker immediately.  This keeps progress
            # across the worker's bounded timeout and later scheduled runs.
            if not persist():
                records.pop(ticker, None)
                failures[ticker] = {
                    "attempted_at": now.isoformat(),
                    "error": "cache_write_failed",
                    "attempts": int(previous_failure.get("attempts", 0)) + 1 if isinstance(previous_failure, dict) else 1,
                }
        except IncompleteMopsHistoryError as error:
            errors.append(f"{ticker} MOPS history: incomplete")
            failures[ticker] = {
                "attempted_at": now.isoformat(),
                "error": "incomplete_history",
                "missing_periods": error.record.get("missing_periods", []),
                "attempts": int(previous_failure.get("attempts", 0)) + 1 if isinstance(previous_failure, dict) else 1,
            }
            persist()
        except (OSError, ValueError, requests.RequestException, RuntimeError) as error:
            errors.append(f"{ticker} MOPS history: {type(error).__name__}")
            failures[ticker] = {
                "attempted_at": now.isoformat(),
                "error": type(error).__name__,
                "detail": str(error)[:240],
                "attempts": int(previous_failure.get("attempts", 0)) + 1 if isinstance(previous_failure, dict) else 1,
            }
            persist()
    # Keep the final write for compatibility with callers that provide an
    # empty pending set; it also normalizes legacy cache files to schema 2.
    persist()
    return {ticker: records[ticker] for ticker in tickers if ticker in records}, errors
