import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest

from src import scheduled_slot_audit as audit

EXPECTED_RECIPIENT_HASHES = {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}


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
                "recipient_hashes": sorted(EXPECTED_RECIPIENT_HASHES),
                "delivered_recipient_hashes": delivered if delivered is not None else sorted(EXPECTED_RECIPIENT_HASHES),
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


def test_terminal_log_parser_reads_v1_v2_and_deduplicates_archive_entries():
    terminal_v2 = {
        "schema_version": "notification-terminal-v2",
        "workflow": "scheduled",
        "run_id": "123",
        "run_attempt": 2,
        "workflow_sha": "a" * 40,
        "slot": "morning",
        "scheduled_for_at": "2026-09-25T06:00:00+08:00",
        "status": "failed",
        "reason": "writer_queue_failed",
    }
    terminal_v1 = {**terminal_v2, "schema_version": "notification-terminal-v1", "run_id": "124"}
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("job/terminal.txt", "prefix " + json.dumps(terminal_v2))
        output.writestr("job/duplicate.txt", "prefix " + json.dumps(terminal_v2))
        output.writestr("terminal.json", json.dumps(terminal_v1))

    rows = audit._terminal_records_from_logs(archive.getvalue())

    assert {row["schema_version"] for row in rows} == {
        "notification-terminal-v1", "notification-terminal-v2",
    }
    assert len(rows) == 2


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
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
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
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
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
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
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
    _write_ledger(path, "us_premarket", "2026-09-25", delivered=["aaaaaaaaaaaa"])
    result = audit.audit_slot(
        ledger_path=path, schedule="45 13 * * 1-5",
        run_created_at="2026-09-25T13:45:00Z",
        now=datetime.fromisoformat("2026-09-25T13:45:01Z"),
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
    )
    assert result["status"] == "incomplete_receipt"
    assert result["reason"] == "scheduled_anchor_recipients_not_fully_delivered"

    wrong_dst = audit.audit_slot(
        ledger_path=tmp_path / "unused.json", schedule="45 14 * * 1-5",
        run_created_at="2026-09-25T14:45:00Z",
        now=datetime.fromisoformat("2026-09-25T14:45:01Z"),
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
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
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
    )
    assert closed["status"] == "expected_skip"
    invalid = audit.audit_slot(
        ledger_path=tmp_path / "unused.json", schedule="45 13 * * 1-5",
        run_created_at="not-a-date",
        now=datetime.now(UTC),
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
    )
    assert invalid["status"] == "blocked"
    assert invalid["reason"] == "workflow_run_created_at_invalid"


def test_claim_cannot_define_a_smaller_recipient_set_than_configuration(tmp_path):
    path = tmp_path / "event-ledger.json"
    _write_ledger(path, "us_premarket", "2026-09-25", delivered=["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    claim = next(iter(payload["delivery_claims"].values()))
    claim["recipient_hashes"] = ["aaaaaaaaaaaa"]
    claim["delivered_recipient_hashes"] = ["aaaaaaaaaaaa"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = audit._receipt_result(
        payload,
        anchor="us:2026-09-25:us_premarket",
        slot_date="2026-09-25",
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
    )

    assert result["status"] == "incomplete_receipt"
    assert result["reason"] == "scheduled_anchor_recipient_set_mismatch"
    assert "aaaaaaaaaaaa" not in json.dumps(result)


def test_external_audit_payload_must_match_original_fixed_slot_anchor(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: {
        "markets": {"taiwan_cash": _cash(True), "taiwan_futures": _futures(True)}
    })
    ledger_path = tmp_path / "empty-ledger.json"
    ledger_path.write_text(json.dumps({"delivery_claims": {}}), encoding="utf-8")
    requested_at = "2026-09-28T01:30:03Z"
    kwargs = {
        "ledger_path": ledger_path,
        "schedule": "",
        "now": datetime.fromisoformat("2026-09-28T01:30:05Z"),
        "external_slot": "pre_open",
        "external_slot_date": "2026-09-28",
        "external_scheduled_for_at": "2026-09-28T08:45:00+08:00",
        "external_requested_at": requested_at,
        "expected_recipient_hashes": EXPECTED_RECIPIENT_HASHES,
        "trigger_source": "repository_dispatch",
    }
    invalid = audit.audit_slot(**{**kwargs, "external_scheduled_for_at": "2026-09-28T09:00:00+08:00"})
    assert invalid["status"] == "blocked"
    assert invalid["reason"] == "external_audit_slot_identity_invalid"

    valid = audit.audit_slot(**kwargs)
    assert valid["status"] == "missing_receipt"
    assert valid["reason"] == "scheduled_anchor_claim_missing"
    assert valid["anchor"] == "taiwan:2026-09-28:pre_open"
    assert valid["trigger_source"] == "repository_dispatch"


def test_external_audit_clock_skew_allows_up_to_120_seconds_and_bounds_wait():
    from datetime import timedelta

    due = datetime.fromisoformat("2026-09-28T01:30:00+00:00")
    common = {
        "slot": "pre_open",
        "slot_date": "2026-09-28",
        "scheduled_for_at": "2026-09-28T08:45:00+08:00",
        "dispatch_unix": str(int((due - timedelta(seconds=69)).timestamp())),
    }
    allowed = audit.external_audit_timing(
        **common,
        requested_at=(due - timedelta(seconds=69)).isoformat(),
        now=due - timedelta(seconds=20),
    )
    assert allowed["status"] == "ready"
    assert allowed["clock_skew_seconds"] == -69
    assert allowed["wait_seconds"] == 20

    boundary = audit.external_audit_timing(
        **{**common, "dispatch_unix": str(int((due - timedelta(seconds=120)).timestamp()))},
        requested_at=(due - timedelta(seconds=120)).isoformat(),
        now=due - timedelta(seconds=120),
    )
    assert boundary["status"] == "ready"
    assert boundary["wait_seconds"] == 120

    too_early = audit.external_audit_timing(
        **{**common, "dispatch_unix": str(int((due - timedelta(seconds=121)).timestamp()))},
        requested_at=(due - timedelta(seconds=121)).isoformat(),
        now=due,
    )
    assert too_early["status"] == "blocked"
    assert too_early["reason"] == "external_audit_requested_too_early"


def test_external_audit_clock_skew_boundaries_include_on_time_and_exact_limit():
    due = datetime.fromisoformat("2026-09-28T01:30:00+00:00")
    for seconds_early, expected_status in ((0, "ready"), (69, "ready"), (120, "ready"), (121, "blocked")):
        requested = due - timedelta(seconds=seconds_early)
        result = audit.external_audit_timing(
            slot="pre_open",
            slot_date="2026-09-28",
            scheduled_for_at="2026-09-28T08:45:00+08:00",
            dispatch_unix=str(int(requested.timestamp())),
            requested_at=requested.isoformat(),
            now=due,
        )
        assert result["status"] == expected_status
        assert result["clock_skew_seconds"] == -seconds_early


def test_external_audit_within_clock_tolerance_does_not_read_ledger_before_due(tmp_path):
    due = datetime.fromisoformat("2026-09-28T01:30:00+00:00")
    result = audit.audit_slot(
        ledger_path=tmp_path / "ledger-must-not-be-read.json",
        schedule="",
        now=due - timedelta(seconds=15),
        external_slot="pre_open",
        external_slot_date="2026-09-28",
        external_scheduled_for_at="2026-09-28T08:45:00+08:00",
        external_dispatch_unix=str(int((due - timedelta(seconds=69)).timestamp())),
        external_requested_at=(due - timedelta(seconds=69)).isoformat(),
        expected_recipient_hashes=EXPECTED_RECIPIENT_HASHES,
    )
    assert result["status"] == "not_due"
    assert result["wait_seconds"] == 15
    assert not (tmp_path / "ledger-must-not-be-read.json").exists()


def test_external_audit_requires_received_at_and_rejects_future_clock(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: {
        "markets": {"taiwan_cash": _cash(True), "taiwan_futures": _futures(True)}
    })
    ledger_path = tmp_path / "empty-ledger.json"
    ledger_path.write_text(json.dumps({"delivery_claims": {}}), encoding="utf-8")
    base = {
        "ledger_path": ledger_path,
        "schedule": "",
        "now": datetime.fromisoformat("2026-09-28T01:30:05Z"),
        "external_slot": "pre_open",
        "external_slot_date": "2026-09-28",
        "external_scheduled_for_at": "2026-09-28T08:45:00+08:00",
    }
    missing = audit.audit_slot(**base)
    assert missing["reason"] == "external_audit_requested_at_missing"
    future = audit.audit_slot(**{**base, "external_requested_at": "2026-09-28T02:00:00Z"})
    assert future["reason"] == "external_audit_requested_at_in_future"


def test_external_dispatch_unix_derives_fixed_slot_anchor_without_runner_date():
    sent_at = datetime.fromisoformat("2026-09-28T09:30:00+08:00")
    selected = audit._external_slot_anchor(
        slot="pre_open",
        slot_date="",
        scheduled_for_at="",
        dispatch_unix=str(int(sent_at.timestamp())),
    )
    assert selected is not None
    assert selected[0] == "pre_open"
    assert selected[1].isoformat() == "2026-09-28T08:45:00+08:00"


def test_external_time_gate_uses_only_standard_library_anchor_before_calendar_install(monkeypatch):
    import src.scheduled_slot_audit as audit_module

    def calendar_must_not_run(*_args, **_kwargs):
        raise AssertionError("exchange calendar is only checked by the full audit after dependencies install")

    monkeypatch.setattr(audit_module, "fixed_scheduled_for", calendar_must_not_run)
    anchor = datetime.fromisoformat("2026-10-07T09:00:00-04:00")
    due = anchor + timedelta(minutes=45)
    result = audit_module.external_audit_timing(
        slot="us_premarket",
        slot_date="2026-10-07",
        scheduled_for_at=anchor.isoformat(),
        dispatch_unix=str(int((due - timedelta(seconds=53)).timestamp())),
        requested_at=(due - timedelta(seconds=53)).isoformat(),
        now=due - timedelta(seconds=20),
    )
    assert result["status"] == "ready"
    assert result["clock_skew_seconds"] == -53
    assert result["wait_seconds"] == 20


def test_missing_claim_is_diagnosed_from_exact_read_only_workflow_terminal(monkeypatch):
    anchor = "2026-09-28T08:45:00+08:00"
    terminal = {
        "schema_version": "notification-terminal-v1",
        "workflow": "scheduled",
        "run_id": "12345",
        "workflow_sha": "a" * 40,
        "slot": "pre_open",
        "scheduled_for_at": anchor,
        "expected": True,
        "status": "failed",
        "reason": "required_report_not_delivered:suppressed:scheduled_public_summary_invalid",
        "no_resend": False,
        "durable_receipt_verified": False,
        "sender_status": "suppressed",
        "receipt_status": "not_attempted",
        "stages": {"prepare": "success", "deployment": "true", "public_gate": "true", "receipt": "skipped", "ledger": "skipped"},
    }
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("job/terminal.txt", "2026-09-28T01:30:00Z " + json.dumps(terminal))
    log_bytes = archive_bytes.getvalue()

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit=-1):
            return self.body

    requested_urls = []

    def opener(request, timeout):
        assert timeout == 15
        requested_urls.append(request.full_url)
        if "/actions/workflows/" in request.full_url and "/runs?" in request.full_url:
            if "page=2" in request.full_url:
                return Response(json.dumps({"total_count": 2, "workflow_runs": [{
                    "id": 12346,
                    "path": ".github/workflows/other.yml",
                    "event": "schedule",
                    "created_at": "2026-09-28T01:00:00Z",
                    "head_sha": "b" * 40,
                    "status": "completed",
                    "conclusion": "success",
                }]}).encode())
            return Response(json.dumps({"total_count": 2, "workflow_runs": [{
                "id": 12345,
                "path": ".github/workflows/scheduled-brief.yml",
                "event": "schedule",
                "created_at": "2026-09-28T01:00:00Z",
                "head_sha": "a" * 40,
                "html_url": "https://github.com/acme/prstk/actions/runs/12345",
                "status": "completed",
                "conclusion": "failure",
            }]}).encode())
        if "/actions/runs/12345/jobs?" in request.full_url:
            return Response(json.dumps({"total_count": 1, "jobs": [{
                "id": 456,
                "name": "refresh-notify-deploy",
                "status": "completed",
                "conclusion": "failure",
                "runner_id": 88,
                "started_at": "2026-09-28T01:00:01Z",
                "steps": [
                    {"name": "Wait for production writer queue", "status": "completed", "conclusion": "failure", "started_at": "2026-09-28T01:01:00Z"},
                ],
            }]}).encode())
        return Response(log_bytes)

    diagnosis = audit._diagnose_scheduled_run(
        repository="acme/prstk",
        token="test-token",
        slot="pre_open",
        anchor_local=datetime.fromisoformat(anchor),
        now=datetime.fromisoformat("2026-09-28T01:31:00Z"),
        opener=opener,
    )
    assert diagnosis["status"] == "matched"
    assert diagnosis["terminal_reason"].endswith("scheduled_public_summary_invalid")
    assert diagnosis["run_id"] == 12345
    assert diagnosis["stages"]["public_gate"] == "true"
    assert diagnosis["execution_diagnostic"]["classification"] == "workflow_step_failed"
    assert diagnosis["annotation_evidence_status"] == "not_required"
    assert len(requested_urls) == 5
    assert all("test-token" not in url for url in requested_urls)


def test_terminal_artifact_is_bound_to_run_attempt_and_preferred_to_logs():
    anchor = "2026-09-28T08:45:00+08:00"
    terminal = {
        "schema_version": "notification-terminal-v2",
        "workflow": "scheduled",
        "run_id": "12345",
        "run_attempt": 2,
        "workflow_sha": "a" * 40,
        "slot": "pre_open",
        "scheduled_for_at": anchor,
        "expected": True,
        "status": "failed",
        "reason": "writer_queue_timeout",
        "stages": {"writer_queue": "failed", "prepare": "not_run"},
    }
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("terminal.json", json.dumps(terminal))
    terminal_zip = archive_bytes.getvalue()

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit=-1):
            return self.body

    requested_urls = []

    def opener(request, timeout):
        requested_urls.append(request.full_url)
        if "/actions/workflows/" in request.full_url and "/runs?" in request.full_url:
            return Response(json.dumps({"total_count": 1, "workflow_runs": [{
                "id": 12345,
                "run_attempt": 2,
                "path": ".github/workflows/scheduled-brief.yml",
                "event": "schedule",
                "created_at": "2026-09-28T01:00:00Z",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "failure",
            }]}).encode())
        if "/actions/runs/12345/artifacts?" in request.full_url:
            return Response(json.dumps({"total_count": 1, "artifacts": [{
                "id": 789,
                "name": "scheduled-terminal-12345-attempt-2",
                "expired": False,
                "workflow_run": {"id": 12345},
            }]}).encode())
        if "/actions/artifacts/789/zip" in request.full_url:
            return Response(terminal_zip)
        if "/actions/runs/12345/jobs?" in request.full_url:
            return Response(json.dumps({"total_count": 1, "jobs": [{
                "id": 456,
                "name": "refresh-notify-deploy",
                "status": "completed",
                "conclusion": "failure",
                "runner_id": 88,
                "started_at": "2026-09-28T01:00:01Z",
                "steps": [{
                    "name": "Wait for production writer queue",
                    "status": "completed",
                    "conclusion": "failure",
                    "started_at": "2026-09-28T01:01:00Z",
                }],
            }]}).encode())
        raise AssertionError(f"unexpected API request: {request.full_url}")

    diagnosis = audit._diagnose_scheduled_run(
        repository="acme/prstk",
        token="read-only-token",
        slot="pre_open",
        anchor_local=datetime.fromisoformat(anchor),
        now=datetime.fromisoformat("2026-09-28T01:31:00Z"),
        opener=opener,
    )

    assert diagnosis["status"] == "matched"
    assert diagnosis["terminal_reason"] == "writer_queue_timeout"
    assert diagnosis["run_id"] == 12345
    assert not any("/actions/runs/12345/logs" in url for url in requested_urls)


def test_artifact_cross_host_redirect_drops_github_credentials_and_rejects_other_hosts():
    from urllib.error import URLError
    from urllib.request import Request

    from src.scheduled_slot_audit import _ArtifactRedirectHandler

    request = Request(
        "https://api.github.com/repos/acme/prstk/actions/artifacts/789/zip",
        headers={"Authorization": "Bearer secret", "Cookie": "session=secret"},
    )
    handler = _ArtifactRedirectHandler()
    redirected = handler.redirect_request(
        request, object(), 302, "Found", {},
        "https://productionresultssa12.blob.core.windows.net/actions/abc?sig=private",
    )
    assert redirected is not None
    assert not redirected.has_header("Authorization")
    assert not redirected.has_header("Cookie")

    with pytest.raises(URLError):
        handler.redirect_request(
            request, object(), 302, "Found", {}, "https://attacker.example/collect",
        )


def test_recipient_manifest_rejects_invalid_values_without_falling_back(monkeypatch):
    monkeypatch.setenv(
        "SCHEDULED_RECIPIENT_SET_MANIFEST",
        '{"schema_version":"scheduled-recipient-set-v1","version":"bad","effective_at":"2026-09-28T00:00:00Z","recipient_hashes":["0123456789ab","not-a-hash"]}',
    )
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "must-not-fall-back")
    assert audit._expected_recipient_hashes_from_env() == set()


def test_recipient_manifest_never_falls_back_to_legacy_sender_or_split_variables(monkeypatch):
    monkeypatch.delenv("SCHEDULED_RECIPIENT_SET_MANIFEST", raising=False)
    monkeypatch.setenv("SCHEDULED_RECIPIENT_HASHES", "0123456789ab")
    monkeypatch.setenv("SCHEDULED_RECIPIENT_SET_VERSION", "legacy-version")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "must-not-be-used")
    assert audit._expected_recipient_hashes_from_env() == set()


def test_audit_workflow_receives_versioned_allowlist_without_sender_credentials():
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "scheduled-brief-slot-audit.yml"
    ).read_text(encoding="utf-8")
    assert "SCHEDULED_RECIPIENT_SET_MANIFEST: ${{ vars.SCHEDULED_RECIPIENT_SET_MANIFEST || '' }}" in workflow
    assert "SCHEDULED_RECIPIENT_SET_VERSION:" not in workflow
    assert "SCHEDULED_RECIPIENT_SET_EFFECTIVE_AT:" not in workflow
    assert "SCHEDULED_RECIPIENT_HASHES:" not in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY" not in workflow
    assert "--wait-until-due" in workflow
    timing_at = workflow.index("Validate external audit timestamp and wait until due")
    install_at = workflow.index("Install read-only audit dependencies")
    ledger_at = workflow.index("Checkout published receipt ledger after audit deadline")
    assert timing_at < install_at < ledger_at
    assert "python -m pip install -r requirements-production.txt" in workflow


def test_recipient_set_version_binds_hashes_and_effective_time():
    hashes = {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}
    original = audit.recipient_set_version(hashes, "2026-09-28T00:00:00Z")
    assert original != audit.recipient_set_version({"aaaaaaaaaaaa"}, "2026-09-28T00:00:00Z")
    assert original != audit.recipient_set_version(hashes, "2026-09-28T00:01:00Z")


def test_recipient_set_version_and_effective_time_are_required_for_production_audit(
    monkeypatch, tmp_path,
):
    snapshot = {"markets": {"taiwan_cash": _cash(True), "taiwan_futures": _futures(True)}}
    monkeypatch.setattr(audit, "_calendar_snapshot", lambda *_args: snapshot)
    diagnoses = []

    def diagnose(**kwargs):
        diagnoses.append(kwargs)
        return {"status": "matched", "execution_diagnostic": {"classification": "workflow_step_failed"}}

    monkeypatch.setattr(audit, "_diagnose_scheduled_run", diagnose)
    ledger_path = tmp_path / "empty-ledger.json"
    ledger_path.write_text(json.dumps({"delivery_claims": {}}), encoding="utf-8")
    base = {
        "ledger_path": ledger_path,
        "schedule": "",
        "now": datetime.fromisoformat("2026-09-28T01:31:00Z"),
        "external_slot": "pre_open",
        "external_slot_date": "2026-09-28",
        "external_scheduled_for_at": "2026-09-28T08:45:00+08:00",
        "external_requested_at": "2026-09-28T01:30:05Z",
        "expected_recipient_hashes": EXPECTED_RECIPIENT_HASHES,
        "require_recipient_set_metadata": True,
        "github_repository": "acme/prstk",
        "github_token": "read-only-token",
    }

    missing = audit.audit_slot(**base)
    assert missing["status"] == "blocked"
    assert missing["reason"] == "expected_recipient_set_version_unavailable"
    assert missing["run_diagnosis"]["execution_diagnostic"]["classification"] == "workflow_step_failed"
    assert diagnoses[-1]["slot"] == "pre_open"

    future_effective = audit.audit_slot(**{
        **base,
        "expected_recipient_set_version": "recipients-2026-09-28-v1",
        "expected_recipient_set_effective_at": "2026-09-28T02:00:00Z",
    })
    assert future_effective["status"] == "blocked"
    assert future_effective["reason"] == "expected_recipient_set_not_effective_for_slot"

    valid = audit.audit_slot(**{
        **base,
        "expected_recipient_set_version": audit.recipient_set_version(
            EXPECTED_RECIPIENT_HASHES, "2026-09-28T00:00:00Z",
        ),
        "expected_recipient_set_effective_at": "2026-09-28T00:00:00Z",
    })
    assert valid["status"] == "missing_receipt"
    assert valid["recipient_set_version"] == audit.recipient_set_version(
        EXPECTED_RECIPIENT_HASHES, "2026-09-28T00:00:00Z",
    )
    assert valid["recipient_set_effective_at"] == "2026-09-28T00:00:00Z"



def test_receipt_failure_is_unhealthy_result_not_audit_process_failure():
    missing = audit._finalize_audit_result({
        "status": "missing_receipt", "reason": "scheduled_anchor_claim_missing",
        "slot": "pre_open", "market_date": "2026-10-09",
    })
    assert missing["executionStatus"] == "COMPLETED"
    assert missing["dataStatus"] == "UNHEALTHY"
    assert missing["completionStatus"] == "INCOMPLETE"
    assert missing["incidentKey"] == "scheduled-receipt:pre_open:2026-10-09"
    assert audit._audit_exit_code(missing) == 0

    for status in ("expected_skip", "not_applicable", "not_due"):
        skipped = audit._finalize_audit_result({"status": status, "reason": "calendar_verified_closed"})
        assert skipped["executionStatus"] == "COMPLETED"
        assert skipped["dataStatus"] == "PASS"
        assert skipped["completionStatus"] == "EXPECTED_SKIP"
        assert skipped["reasonCodes"] == ["calendar_verified_closed"]
        assert audit._audit_exit_code(skipped) == 0

    blocked = audit._finalize_audit_result({"status": "blocked", "reason": "ledger_unavailable"})
    assert audit._audit_exit_code(blocked) == 1
