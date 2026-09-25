import json
from datetime import datetime

from src.scheduled_slot_audit import audit_slot


def _write_ledger(path, *, status="delivered", delivered=None):
    anchor = "us:2026-09-25:us_premarket"
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


def test_audit_requires_exact_durable_receipt_for_each_recipient(tmp_path):
    ledger = tmp_path / "event-ledger.json"
    _write_ledger(ledger)
    result = audit_slot(
        ledger_path=ledger, schedule="45 13 * * 1-5",
        now=datetime.fromisoformat("2026-09-25T13:45:00+00:00"),
    )
    assert result["status"] == "delivered"
    assert result["recipient_count"] == 2
    assert result["read_only"] is True

    _write_ledger(ledger, delivered=["hash-a"])
    result = audit_slot(
        ledger_path=ledger, schedule="45 13 * * 1-5",
        now=datetime.fromisoformat("2026-09-25T13:45:00+00:00"),
    )
    assert result["status"] == "incomplete_receipt"
    assert result["delivered_count"] == 1


def test_delayed_audit_after_utc_midnight_checks_the_original_ny_slot(tmp_path):
    ledger = tmp_path / "event-ledger.json"
    _write_ledger(ledger)
    result = audit_slot(
        ledger_path=ledger, schedule="45 13 * * 1-5",
        now=datetime.fromisoformat("2026-09-26T01:00:00+00:00"),
    )
    assert result["status"] == "delivered"
    assert result["market_date"] == "2026-09-25"


def test_wrong_dst_cron_candidate_is_a_quiet_read_only_skip(tmp_path):
    result = audit_slot(
        ledger_path=tmp_path / "not-read.json", schedule="45 14 * * 1-5",
        now=datetime.fromisoformat("2026-09-25T14:45:00+00:00"),
    )
    assert result == {
        "status": "not_applicable", "reason": "wrong_dst_schedule_candidate", "read_only": True,
    }


def test_standard_time_candidate_is_selected_from_new_york_clock(tmp_path):
    result = audit_slot(
        ledger_path=tmp_path / "not-read.json", schedule="45 14 * * 1-5",
        now=datetime.fromisoformat("2026-12-28T14:45:00+00:00"),
    )
    assert result["status"] == "blocked"
    assert result["reason"].startswith("scheduled_receipt_ledger_unavailable_")


def test_nyse_holiday_is_expected_skip_not_a_missing_receipt(tmp_path):
    result = audit_slot(
        ledger_path=tmp_path / "not-read.json", schedule="45 14 * * 1-5",
        now=datetime.fromisoformat("2026-12-25T14:45:00+00:00"),
    )
    assert result["status"] == "expected_skip"
    assert result["reason"] == "nyse_closed_no_us_premarket_report"


def test_missing_or_corrupt_receipt_is_an_actionable_failure(tmp_path):
    missing = audit_slot(
        ledger_path=tmp_path / "missing.json", schedule="45 13 * * 1-5",
        now=datetime.fromisoformat("2026-09-25T13:45:00+00:00"),
    )
    assert missing["status"] == "blocked"
    corrupt_path = tmp_path / "broken.json"
    corrupt_path.write_text("not json", encoding="utf-8")
    corrupt = audit_slot(
        ledger_path=corrupt_path, schedule="45 13 * * 1-5",
        now=datetime.fromisoformat("2026-09-25T13:45:00+00:00"),
    )
    assert corrupt["status"] == "blocked"
    assert corrupt["reason"] == "scheduled_receipt_ledger_invalid"
