import json
from datetime import UTC, datetime

from src import scheduled_slot_audit as audit


def _cash(is_open=False, next_date="2026-09-29"):
    return {
        "is_trading_day": is_open,
        "calendar_status": "confirmed_open" if is_open else "confirmed_closed",
        "calendar": "XTAI",
        "calendar_provider": "pandas_market_calendars",
        "next_trading_date": next_date,
    }


def _futures(is_open=False, next_date="2026-09-29"):
    return {
        "is_trading_day": is_open,
        "calendar_status": "confirmed_open" if is_open else "confirmed_closed",
        "calendar": "TAIFEX",
        "calendar_provider": "TAIFEX",
        "calendar_version": "TAIFEX-2026",
        "calendar_coverage_start": "2026-01-01",
        "calendar_coverage_end": "2026-12-31",
        "calendar_source_urls": ["https://www.taifex.com.tw/calendar.pdf"],
        "calendar_source_published_on": ["2025-10-30"],
        "calendar_source_document": "115年度期貨集中交易市場開休市日期表",
        "calendar_verified_on": "2026-09-25",
        "next_trading_date": next_date,
    }


def _write_ledger(path, slot, slot_date, *, status="delivered", delivered=None):
    anchor = f"{'us' if slot == 'us_premarket' else 'taiwan'}:{slot_date}:{slot}"
    payload = {
        "delivery_claims": {
            f"scheduled-anchor:{anchor}": {
                "kind": "scheduled_brief",
                "anchor_key": anchor,
                "status": status,
                "recipient_hashes": ["hash-a", "hash-b"],
                "delivered_recipient_hashes": delivered if delivered is not None else ["hash-a", "hash-b"],
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _audit(monkeypatch, tmp_path, schedule, created, now, snapshot):
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda _slot, _day: snapshot)
    return audit.audit_slot(
        ledger_path=tmp_path / "event-ledger.json",
        schedule=schedule,
        run_created_at=created,
        now=now,
    )


def test_four_anchor_audit_crons_map_to_exchange_local_deadlines():
    cases = [
        ("45 22 * * *", "2026-09-25T06:45:00+08:00", "morning"),
        ("30 1 * * 1-5", "2026-09-28T09:30:00+08:00", "pre_open"),
        ("5 7 * * 1-5", "2026-09-28T15:05:00+08:00", "post_close"),
        ("45 13 * * 1-5", "2026-09-25T09:45:00-04:00", "us_premarket"),
    ]
    for schedule, expected_time, expected_slot in cases:
        occurrence = audit._candidate_occurrence(
            schedule, datetime.fromisoformat(expected_time).astimezone(UTC),
        )
        assert occurrence is not None
        selected = audit._candidate_slot(schedule, occurrence)
        assert selected is not None
        assert selected[0] == expected_slot
        assert selected[1].isoformat() == expected_time


def test_delayed_audit_uses_original_run_created_slot_not_latest_slot(monkeypatch, tmp_path):
    path = tmp_path / "event-ledger.json"
    _write_ledger(path, "morning", "2026-09-25")
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: {
        "markets": {"taiwan_cash": _cash(False), "taiwan_futures": _futures(False)}
    })
    result = audit.audit_slot(
        ledger_path=path,
        schedule="45 22 * * *",
        run_created_at="2026-09-24T22:45:04Z",
        now=datetime.fromisoformat("2026-09-26T01:00:00+00:00"),
    )
    assert result["status"] == "delivered"
    assert result["slot"] == "morning"
    assert result["market_date"] == "2026-09-25"


def test_weekend_policy_requires_morning_but_skips_taiwan_intraday_anchors(monkeypatch, tmp_path):
    morning_path = tmp_path / "morning.json"
    _write_ledger(morning_path, "morning", "2026-09-26")
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: {
        "markets": {"taiwan_cash": _cash(False), "taiwan_futures": _futures(False)}
    })
    morning = audit.audit_slot(
        ledger_path=morning_path, schedule="45 22 * * *",
        run_created_at="2026-09-25T22:45:00Z",
        now=datetime.fromisoformat("2026-09-25T22:45:01Z"),
    )
    assert morning["status"] == "delivered"
    assert morning["obligation"] == "report_required"



def test_taiwan_holiday_preopen_is_required_and_postclose_is_expected_skip(monkeypatch, tmp_path):
    snapshot = {"markets": {
        "taiwan_cash": _cash(False),
        "taiwan_futures": _futures(False),
    }}
    pre_path = tmp_path / "pre.json"
    _write_ledger(pre_path, "pre_open", "2026-09-28")
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: snapshot)
    pre = audit.audit_slot(
        ledger_path=pre_path, schedule="30 1 * * 1-5",
        run_created_at="2026-09-28T01:30:00Z",
        now=datetime.fromisoformat("2026-09-28T01:30:01Z"),
    )
    assert pre["status"] == "delivered"
    assert pre["obligation"] == "holiday_notice_required"
    post = audit.audit_slot(
        ledger_path=tmp_path / "unused.json", schedule="5 7 * * 1-5",
        run_created_at="2026-09-28T07:05:00Z",
        now=datetime.fromisoformat("2026-09-28T07:05:01Z"),
    )
    assert post["status"] == "expected_skip"
    assert post["reason"] == "closed_market_publish_only"


def test_unverified_calendar_blocks_and_does_not_treat_missing_claim_as_success(monkeypatch, tmp_path):
    unverifiable_cash = {
        "is_trading_day": True,
        "calendar_status": "unknown",
        "calendar": "XTAI",
        "calendar_provider": "pandas_market_calendars",
    }
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: {
        "markets": {"taiwan_cash": unverifiable_cash, "taiwan_futures": _futures(False)}
    })
    blocked = audit.audit_slot(
        ledger_path=tmp_path / "unused.json", schedule="30 1 * * 1-5",
        run_created_at="2026-09-28T01:30:00Z",
        now=datetime.fromisoformat("2026-09-28T01:30:01Z"),
    )
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "market_calendar_unverified"

    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: {
        "markets": {"taiwan_cash": _cash(True), "taiwan_futures": _futures(True)}
    })
    missing = audit.audit_slot(
        ledger_path=tmp_path / "missing.json", schedule="30 1 * * 1-5",
        run_created_at="2026-09-28T01:30:00Z",
        now=datetime.fromisoformat("2026-09-28T01:30:01Z"),
    )
    assert missing["status"] == "blocked"
    assert missing["reason"].startswith("scheduled_receipt_ledger_unavailable_")


def test_partial_recipient_receipt_fails_and_wrong_dst_candidate_is_not_applicable(tmp_path):
    path = tmp_path / "event-ledger.json"
    _write_ledger(path, "us_premarket", "2026-09-25", delivered=["hash-a"])
    result = audit.audit_slot(
        ledger_path=path, schedule="45 13 * * 1-5",
        run_created_at="2026-09-25T13:45:00Z",
        now=datetime.fromisoformat("2026-09-25T13:45:01Z"),
    )
    assert result["status"] == "blocked" or result["status"] == "incomplete_receipt"

    wrong_dst = audit.audit_slot(
        ledger_path=tmp_path / "unused.json", schedule="45 14 * * 1-5",
        run_created_at="2026-09-25T14:45:00Z",
        now=datetime.fromisoformat("2026-09-25T14:45:01Z"),
    )
    assert wrong_dst["status"] == "not_applicable"


def test_nyse_closed_is_expected_skip_and_invalid_run_time_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: {
        "markets": {"us": {
            "is_trading_day": False,
            "calendar_status": "confirmed_closed",
            "calendar": "NYSE",
        }}
    })
    closed = audit.audit_slot(
        ledger_path=tmp_path / "unused.json", schedule="45 14 * * 1-5",
        run_created_at="2026-12-25T14:45:00Z",
        now=datetime.fromisoformat("2026-12-25T14:45:01Z"),
    )
    assert closed["status"] == "expected_skip"
    invalid = audit.audit_slot(
        ledger_path=tmp_path / "unused.json", schedule="45 13 * * 1-5",
        run_created_at="not-a-date",
        now=datetime.now(UTC),
    )
    assert invalid["status"] == "blocked"
    assert invalid["reason"] == "workflow_run_created_at_invalid"
