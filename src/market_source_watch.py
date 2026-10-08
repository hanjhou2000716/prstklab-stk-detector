"""Bounded, read-only pre-queue watch for official Taiwan close publication."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from datetime import time as wall_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

TAIPEI = ZoneInfo("Asia/Taipei")
WATCH_DURATION = timedelta(minutes=12)
FINAL_SOURCE_CHECK_OFFSET = timedelta(minutes=20)
POLL_SECONDS = 120


def _parse_anchor(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("scheduled_for_must_include_timezone")
    return parsed.astimezone(TAIPEI)


def _latest_twse_session(anchor: datetime) -> str | None:
    from src.market_data import get_market_status

    candidate = anchor.date()
    for _ in range(20):
        status = get_market_status("taiwan", today=candidate)
        if status.get("calendar_status") == "confirmed_open":
            if candidate < anchor.date() or anchor.time() >= wall_time(13, 30):
                return candidate.isoformat()
        elif status.get("calendar_status") != "confirmed_closed":
            return None
        candidate -= timedelta(days=1)
    return None


def _latest_taifex_session(anchor: datetime) -> str | None:
    from src.taifex_calendar import get_taifex_index_futures_status

    candidate = anchor.date()
    for _ in range(20):
        status = get_taifex_index_futures_status(
            today=candidate,
            now=datetime.combine(candidate, anchor.timetz().replace(tzinfo=None), TAIPEI),
        )
        if status.get("calendar_status") == "confirmed_open":
            if candidate < anchor.date() or anchor.time() >= wall_time(13, 45):
                return candidate.isoformat()
        elif status.get("calendar_status") != "confirmed_closed":
            return None
        candidate -= timedelta(days=1)
    return None


def _probe(
    cash_target: str, futures_target: str, *, reference_now: datetime | None = None,
) -> dict[str, Any]:
    from src.taifex_daily import fetch_latest_verified_txf
    from src.taiwan_market_statistics import fetch_twse_taiex_recent_close

    session = requests.Session()
    cash_attempts: list[dict[str, str]] = []
    futures_attempts: list[dict[str, str]] = []
    cash_quote = fetch_twse_taiex_recent_close(
        target_date=cash_target, session=session, diagnostics=cash_attempts,
    )
    futures_quote = fetch_latest_verified_txf(
        session=session, now=reference_now or datetime.now(TAIPEI),
        diagnostics=futures_attempts, target_date=futures_target,
    )
    cash_date = str(cash_quote.get("quote_date") or "")[:10] if cash_quote else ""
    futures_date = str(futures_quote.get("quote_date") or "")[:10] if futures_quote else ""

    def compact_quote(quote: dict[str, Any] | None) -> dict[str, Any] | None:
        if not quote:
            return None
        fields = (
            "ticker", "quote_date", "price", "change", "change_percent",
            "previous_close", "quote_time", "quote_basis", "instrument_id", "freshness",
            "data_status", "source", "source_tier", "quote_source", "source_label", "source_url",
            "contract_month", "session", "contract_basis", "quote_delayed", "backup_used",
            "official_fallback_used", "routine_eligible", "alert_eligible",
        )
        compact = {key: quote[key] for key in fields if key in quote}
        attempts = cash_attempts if str(quote.get("ticker") or "") == "TAIEX" else futures_attempts
        compact["source_attempts"] = attempts
        return compact

    return {
        "checked_at": datetime.now(TAIPEI).isoformat(),
        "cash_target_date": cash_target,
        "cash_observed_date": cash_date or None,
        "cash_target_available": cash_date == cash_target,
        "cash_quote": compact_quote(cash_quote),
        "cash_attempts": cash_attempts,
        "futures_target_date": futures_target,
        "futures_observed_date": futures_date or None,
        "futures_target_available": futures_date == futures_target,
        "futures_quote": compact_quote(futures_quote),
        "futures_attempts": futures_attempts,
    }


def watch_quotes_supersede_snapshot(watch_result: dict[str, Any], snapshot_path: str) -> bool:
    """Return whether the final official probe contains a newer/different quote."""
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    rows = snapshot.get("indices") if isinstance(snapshot, dict) else None
    if not isinstance(rows, list):
        return False
    probe = watch_result.get("last_probe")
    if isinstance(probe, dict):
        watch_result = probe
    existing = {
        str(row.get("ticker") or "").upper(): row
        for row in rows if isinstance(row, dict)
    }
    for ticker, key in (("TAIEX", "cash_quote"), ("TXF", "futures_quote")):
        candidate = watch_result.get(key)
        previous = existing.get(ticker)
        if not isinstance(candidate, dict) or not isinstance(previous, dict):
            if isinstance(candidate, dict) and candidate.get("quote_date"):
                return True
            continue
        candidate_date = str(candidate.get("quote_date") or "")[:10]
        previous_date = str(previous.get("quote_date") or "")[:10]
        if not candidate_date:
            continue
        if not previous_date or candidate_date > previous_date:
            return True
        if candidate_date < previous_date:
            continue
        quote_fields = ("price", "change", "change_percent")
        for field in quote_fields:
            candidate_value = _rounded_number(candidate.get(field))
            previous_value = _rounded_number(previous.get(field))
            if candidate_value is not None and candidate_value != previous_value:
                return True
        if ticker == "TXF" and any(
            candidate.get(field)
            and str(candidate.get(field)) != str(previous.get(field) or "")
            for field in ("contract_month", "session")
        ):
            return True
    return False


def _rounded_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (parsed == parsed and abs(parsed) != float("inf")):
        return None
    return round(parsed, 2)


def watch_until(
    *, deadline: datetime, probe: Callable[[], dict[str, Any]],
    now: Callable[[], datetime] = lambda: datetime.now(TAIPEI),
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: int = POLL_SECONDS,
    stop_when_complete: bool = True,
) -> dict[str, Any]:
    """Probe immediately, then at a bounded cadence through the fixed cutoff."""
    started = now()
    attempts = 0
    last: dict[str, Any] = {}
    while True:
        current = now()
        if current > deadline:
            return {
                "status": "source_watch_cutoff_reached",
                "attempts": attempts,
                "last_probe": last,
                "watch_started_at": started.isoformat(),
                "watch_finished_at": current.isoformat(),
            }
        attempts += 1
        try:
            last = probe()
        except Exception as exc:  # A read-only probe must never bypass normal prepare.
            last = {"probe_error": type(exc).__name__}
        if (
            stop_when_complete
            and last.get("cash_target_available") is True
            and last.get("futures_target_available") is True
        ):
            return {
                "status": "both_official_closes_available",
                "attempts": attempts,
                "last_probe": last,
                "watch_started_at": started.isoformat(),
                "watch_finished_at": now().isoformat(),
            }
        current = now()
        remaining = (deadline - current).total_seconds()
        if remaining <= 0:
            return {
                "status": "source_watch_cutoff_reached",
                "attempts": attempts,
                "last_probe": last,
                "watch_started_at": started.isoformat(),
                "watch_finished_at": current.isoformat(),
            }
        sleep(min(float(interval_seconds), remaining))


def run_watch(
    scheduled_for: str, *, probe: Callable[..., dict[str, Any]] = _probe,
    final_source_check: bool = False,
) -> dict[str, Any]:
    anchor = _parse_anchor(scheduled_for)
    cash_target = _latest_twse_session(anchor)
    futures_target = _latest_taifex_session(anchor)
    if not cash_target or not futures_target:
        return {
            "status": "exchange_calendar_unverified",
            "cash_target_date": cash_target,
            "futures_target_date": futures_target,
            "attempts": 0,
        }
    deadline = anchor + (
        FINAL_SOURCE_CHECK_OFFSET if final_source_check else WATCH_DURATION
    )
    # A closed-market anchor has no new same-day close to wait for. Still make
    # one read-only check so the final snapshot can reuse safely available data.
    if cash_target < anchor.date().isoformat() and futures_target < anchor.date().isoformat():
        try:
            result = probe(cash_target, futures_target)
            return {"status": "no_same_day_session_to_wait_for", "attempts": 1, "last_probe": result}
        except Exception as exc:
            return {"status": "read_only_probe_failed", "attempts": 1, "error": type(exc).__name__}
    probe_call = (
        (lambda: probe(cash_target, futures_target, reference_now=anchor))
        if probe is _probe
        else (lambda: probe(cash_target, futures_target))
    )
    return watch_until(
        deadline=deadline,
        probe=probe_call,
        stop_when_complete=not final_source_check,
    ) | {"cash_target_date": cash_target, "futures_target_date": futures_target, "cutoff_at": deadline.isoformat()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheduled-for", required=True)
    parser.add_argument(
        "--final-source-check", action="store_true",
        help="Continue a preparation-overlapped read-only watch to anchor +20 minutes.",
    )
    parser.add_argument("--result-file")
    args = parser.parse_args()
    try:
        result = run_watch(args.scheduled_for, final_source_check=args.final_source_check)
    except (ValueError, OverflowError) as exc:
        result = {"status": "invalid_schedule_anchor", "error": type(exc).__name__, "attempts": 0}
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(rendered)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("### 台股官方收盤唯讀查詢\n\n```json\n" + rendered + "\n```\n")
    if args.result_file:
        with open(args.result_file, "w", encoding="utf-8") as result_file:
            result_file.write(rendered)
    outputs_path = os.environ.get("GITHUB_OUTPUT") if not args.result_file else None
    if outputs_path:
        with open(outputs_path, "a", encoding="utf-8") as output:
            output.write(f"status={result.get('status', 'unknown')}\n")
            output.write(f"attempts={result.get('attempts', 0)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
