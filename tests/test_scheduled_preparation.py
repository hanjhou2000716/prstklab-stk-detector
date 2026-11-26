import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from src.market_source_watch import TAIPEI
from src.scheduled_preparation import _resolved_commit, _run_command, coordinate_preparation, preparation_window


def test_post_close_window_keeps_revalidation_budget_after_1440_source_check():
    anchor = "2026-10-08T14:20:00+08:00"
    started = datetime.fromisoformat("2026-10-08T14:32:22+08:00").timestamp()
    window = preparation_window("post_close", anchor, started)
    assert datetime.fromtimestamp(window.first_attempt_deadline, TAIPEI).isoformat() == "2026-10-08T14:40:00+08:00"
    assert datetime.fromtimestamp(window.overall_deadline, TAIPEI).isoformat() == "2026-10-08T14:45:00+08:00"
    assert window.overall_deadline > window.first_attempt_deadline


@pytest.mark.parametrize(
    ("scenario", "expected_reason", "expected_rebuild"),
    [
        ("equivalent", "prepared_release_current", "none"),
        ("updated", "prepared_release_current", "verified_source_update"),
        ("timeout", "prepare_timeout_budget_exhausted", "verified_source_update"),
        ("late_success", "prepare_timeout_budget_exhausted", "verified_source_update"),
        ("unapplied", "prepared_source_superseded_after_rebuild", "verified_source_update"),
        ("restore_failed", "data_release_restore_failed", "verified_source_update"),
        ("base_update", "prepared_release_current", "release_base_update"),
        ("base_changed_twice", "prepared_base_changed_twice_during_prepare", "release_base_update"),
        ("txf_sibling_stale", "prepared_close_regressed_after_rebuild", "verified_source_update"),
        ("txf_sibling_missing", "prepared_close_regressed_after_rebuild", "verified_source_update"),
        ("txf_sibling_price", "prepared_source_superseded_after_rebuild", "verified_source_update"),
        ("txf_sibling_contract", "prepared_source_superseded_after_rebuild", "verified_source_update"),
        ("txf_sibling_session", "prepared_close_regressed_after_rebuild", "verified_source_update"),
        ("cash_sibling_stale", "prepared_close_regressed_after_rebuild", "verified_source_update"),
        ("cash_sibling_price", "prepared_source_superseded_after_rebuild", "verified_source_update"),
        ("base_sibling_stale", "prepared_close_regressed_after_rebuild", "release_base_update"),
        ("watch_conflict", "official_close_source_conflict", "none"),
        ("historical_watch_conflict", "prepared_release_current", "none"),
    ],
)
def test_post_close_replays_incident_budget_and_never_releases_old_candidate(
    tmp_path, scenario, expected_reason, expected_rebuild,
):
    anchor = "2026-11-26T14:20:00+08:00"
    local = datetime.fromisoformat("2026-11-26T14:32:21.043104+08:00").timestamp()
    today = "2026-11-26"
    checked_at = f"{today}T14:38:30+08:00"
    prior = {"ticker": "TAIEX", "quote_date": "2026-11-25", "price": 38195.43}
    observed = {
        "ticker": "TAIEX", "quote_date": today, "quote_time": f"{today}T13:30:00+08:00",
        "price": 39151.81, "change": 956.38, "change_percent": 2.50, "source_tier": "official",
        "instrument_id": "twse:taiex", "quote_basis": "TWSE_TAIEX_DAILY_CLOSE",
        "source_url": "https://www.twse.com.tw/exchangeReport/MI_INDEX",
        "source_attempts": [{"source": "twse_mi_index_json", "outcome": "verified",
                             "target_date": today, "observed_date": today, "checked_at": checked_at}],
    }
    yesterday = "2026-11-25"
    futures = {
        "ticker": "TXF", "quote_date": today, "quote_time": f"{today}T13:45:00+08:00",
        "price": 39200, "change": 1138, "change_percent": 2.99, "freshness": "recent_close",
        "contract_month": "202612", "session": "regular", "source_tier": "official",
        "instrument_id": "market:txf:taifex:202612:regular",
        "quote_basis": "TAIFEX_TXF_DAY|contract=202612|session=regular",
        "source_url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut",
        "source_attempts": [
            {"source": source, "outcome": outcome, "target_date": today, "observed_date": today}
            for source, outcome in (
                ("taifex_openapi", "verified"), ("taifex_daily_table", "verified"),
                ("taifex_selection", "selected:taifex_openapi"),
            )
        ],
    }
    old_futures = {**futures, "quote_date": yesterday, "quote_time": f"{yesterday}T13:45:00+08:00"}
    snapshot_path = tmp_path / "market.json"
    source_updated = expected_rebuild == "verified_source_update"
    futures_updated = scenario.startswith("cash_sibling_")
    base_updated = expected_rebuild == "release_base_update"
    prepare_timeouts = []
    restored_bases = []
    remote_sha = "a" * 40
    fetch_count = 0

    class SourceProcess:
        def wait(self, timeout=None):
            nonlocal local
            local = datetime.fromisoformat("2026-11-26T14:40:00.125563+08:00").timestamp()
            return 0

        def poll(self):
            return 0

    def popen(command, **_kwargs):
        result = Path(command[command.index("--result-file") + 1])
        probe = {"cash_quote": observed, "futures_quote": futures, "checked_at": checked_at}
        if scenario in {"watch_conflict", "historical_watch_conflict"}:
            probe["futures_quote"] = None
            probe["futures_attempts"] = [{
                "source": "taifex_official_comparison", "outcome": "same_day_official_conflict",
                "observed_date": today if scenario == "watch_conflict" else yesterday,
                "target_date": today, "checked_at": checked_at,
            }]
        if scenario == "base_sibling_stale":
            probe["futures_quote"] = None
        result.write_text(json.dumps({
            "status": "source_watch_cutoff_reached", "last_probe": probe,
        }), encoding="utf-8")
        return SourceProcess()

    def run(command, *, timeout, env, **kwargs):
        nonlocal local, remote_sha, fetch_count
        assert kwargs["capture_output"] is True
        if "src.data_release" in command:
            restored_bases.append(remote_sha)
            local += 16.148 if len(restored_bases) == 1 else 5.111
            ok = scenario != "restore_failed" or len(restored_bases) == 1
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"restored": ok}))
        if command[:2] == ["git", "rev-parse"]:
            local += 0.153 if len(restored_bases) == 1 else 0.165
            return subprocess.CompletedProcess(command, 0, stdout=remote_sha + "\n")
        if command[:2] == ["git", "fetch"]:
            fetch_count += 1
            if base_updated and fetch_count == 1:
                remote_sha = "b" * 40
            if scenario == "base_changed_twice" and fetch_count == 2:
                remote_sha = "c" * 40
            return subprocess.CompletedProcess(command, 0)
        assert "src.scheduled_delivery" in command
        prepare_timeouts.append(timeout)
        attempt = len(prepare_timeouts)
        if attempt == 1:
            local += 438.836
        else:
            assert timeout == 294
            if source_updated:
                overrides = Path(command[command.index("--official-close-overrides") + 1])
                expected = {"futures_quote": futures} if futures_updated else {"cash_quote": observed}
                assert json.loads(overrides.read_text(encoding="utf-8")) == expected
            else:
                assert "--official-close-overrides" not in command
            if scenario == "timeout":
                local += timeout
                raise subprocess.TimeoutExpired(command, timeout)
            local += 295 if scenario == "late_success" else 291
        cash_row = observed
        futures_row = futures
        if source_updated and not futures_updated and (attempt == 1 or scenario == "unapplied"):
            cash_row = prior
        if futures_updated and attempt == 1:
            futures_row = old_futures
        if attempt == 2:
            if scenario in {"txf_sibling_stale", "base_sibling_stale"}:
                futures_row = old_futures
            if scenario == "txf_sibling_price":
                futures_row = {**futures, "price": 38062}
            if scenario == "txf_sibling_contract":
                futures_row = {
                    **futures, "contract_month": "202701",
                    "instrument_id": "market:txf:taifex:202701:regular",
                    "quote_basis": "TAIFEX_TXF_DAY|contract=202701|session=regular",
                }
            if scenario == "txf_sibling_session":
                futures_row = {
                    **futures, "session": "night",
                    "instrument_id": "market:txf:taifex:202612:night",
                    "quote_basis": "TAIFEX_TXF_NIGHT|contract=202612|session=night",
                }
            if scenario == "cash_sibling_stale":
                cash_row = prior
            if scenario == "cash_sibling_price":
                cash_row = {**observed, "price": prior["price"]}
        rows = [cash_row]
        if attempt == 1 or scenario != "txf_sibling_missing":
            rows.append(futures_row)
        snapshot_path.write_text(json.dumps({"indices": rows}), encoding="utf-8")
        Path(env["GITHUB_OUTPUT"]).write_text(
            f"prepared=true\nsnapshot_id=snapshot-{attempt}\nnotification_expected=true\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    outputs = tmp_path / "outputs.txt"
    artifact = tmp_path / "preparation.json"
    result, status = coordinate_preparation(
        slot="post_close", scheduled_for=anchor, slot_context="{}",
        notification_requested="true", snapshot_path=str(snapshot_path),
        data_release_branch="data-release", initial_source_status="source_watch_cutoff_reached",
        environ={"GITHUB_OUTPUT": str(outputs), "PREPARATION_RESULT_PATH": str(artifact)},
        clock=lambda: local, run=run, popen=popen,
    )
    assert json.loads(artifact.read_text(encoding="utf-8")) == result
    assert result["reason"] == expected_reason
    assert result["rebuild_reason"] == expected_rebuild
    assert result["first_candidate_identity"] == {"snapshot_id": "snapshot-1", "data_release_sha": "a" * 40}
    expected_base = "" if scenario == "watch_conflict" else ("b" if base_updated else "a") * 40
    assert result["first_revalidated_base_sha"] == expected_base
    assert result["source_probe_checked_at"] == checked_at
    assert result["source_check_changed_candidate"] is source_updated
    stages = [row for row in result["stage_history"] if row["stage"] == "prepare"]
    assert stages[0]["duration_seconds"] == 438.836
    assert stages[0]["starting_budget_seconds"] == 442
    if futures_updated:
        assert set(result["source_updates"]["TXF"]["changed_fields"]) == {"quote_date"}
    elif source_updated:
        assert result["source_updates"]["TAIEX"]["changed_fields"]["price"] == {
            "before": 38195.43, "after": 39151.81,
        }
    if scenario == "unapplied":
        assert result["unapplied_source_updates"]["TAIEX"]["changed_fields"]["quote_date"]["after"] == today
    if scenario == "watch_conflict":
        assert len(prepare_timeouts) == 1 and fetch_count == 0
        assert result["source_conflicts"][0]["observed_date"] == today
        assert result["source_conflicts"][0]["outcome"] == "same_day_official_conflict"
    elif scenario == "historical_watch_conflict":
        assert result["source_conflicts"] == []
        assert len(prepare_timeouts) == 1
    if expected_reason == "prepared_close_regressed_after_rebuild":
        ticker = "TAIEX" if futures_updated else "TXF"
        expected_date = None if scenario in {"txf_sibling_missing", "txf_sibling_session"} else yesterday
        assert ticker in result["first_current_close_tickers"]
        assert result["regressed_close_dates"] == {ticker: expected_date}
        if scenario == "base_sibling_stale":
            assert result["unapplied_source_updates"] == {}
        else:
            field = "session" if scenario == "txf_sibling_session" else "quote_date"
            assert field in result["unapplied_source_updates"][ticker]["changed_fields"]
    if scenario in {"txf_sibling_price", "txf_sibling_contract", "cash_sibling_price"}:
        ticker = "TAIEX" if futures_updated else "TXF"
        field = "contract_month" if scenario == "txf_sibling_contract" else "price"
        assert result["regressed_close_dates"] == {}
        assert set(result["unapplied_source_updates"][ticker]["changed_fields"]) == {field}
    output = outputs.read_text(encoding="utf-8")
    if expected_reason == "prepared_release_current":
        assert status == 0
        assert "prepared=true" in output
        assert f"snapshot_id=snapshot-{len(prepare_timeouts)}" in output
    else:
        assert status == 1
        assert "prepared=false" in output and "base_current=false" in output
        if scenario != "watch_conflict":
            assert "snapshot_id=snapshot-1" not in output
    if scenario in {"timeout", "late_success"}:
        assert stages[1]["starting_budget_seconds"] == 294
        assert stages[1]["remaining_budget_seconds"] == 0
    if base_updated:
        assert restored_bases == ["a" * 40, "b" * 40]


def test_real_git_rev_parse_captures_and_validates_commit_output(tmp_path):
    subprocess.run(
        ["git", "init", str(tmp_path)], check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "fixture@example.invalid"], check=True)
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("root commit", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "fixture.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"], check=True,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )

    result = _run_command(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        timeout_seconds=5, env=dict(os.environ), run=subprocess.run,
    )
    assert result.returncode == 0
    assert re.fullmatch(r"[0-9a-f]{40}", _resolved_commit(result))

    missing = _run_command(
        ["git", "-C", str(tmp_path), "rev-parse", "missing-ref"],
        timeout_seconds=5, env=dict(os.environ), run=subprocess.run,
    )
    assert missing.returncode != 0
    assert _resolved_commit(missing) == ""


def test_restore_stdout_and_tracking_ref_bind_the_restored_bytes(tmp_path):
    remote, local = tmp_path / "upstream", tmp_path / "runner"

    def git(repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    for repo, branch in ((remote, "data-release"), (local, "main")):
        repo.mkdir()
        git(repo, "init", "--initial-branch", branch)
        git(repo, "config", "user.name", "Fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        (repo / "site/data").mkdir(parents=True)
        (repo / "site/data/market.json").write_text('{"version": 1}', encoding="utf-8")
        git(repo, "add", "site/data/market.json")
        git(repo, "commit", "-m", "Initial market data")
    first = git(remote, "rev-parse", "HEAD")
    git(local, "remote", "add", "origin", str(remote))
    (local / "site/data/market.json").write_text('{"version": 0}', encoding="utf-8")

    def restore(branch):
        return subprocess.run(
            [sys.executable, "-B", "-m", "src.data_release", "--restore", "--branch", branch,
             "--include", "site/data"],
            cwd=local,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            check=True, capture_output=True, text=True,
        )

    result = json.loads(restore("data-release").stdout)
    assert result["restored"] is True
    assert "site/data/market.json" in result["files"]
    assert git(local, "rev-parse", "refs/remotes/origin/data-release") == first
    assert json.loads((local / "site/data/market.json").read_text(encoding="utf-8")) == {"version": 1}
    assert json.loads(restore("missing-release").stdout)["restored"] is False

    (remote / "site/data/market.json").write_text('{"version": 2}', encoding="utf-8")
    git(remote, "commit", "-am", "New upstream data")
    git(local, "fetch", "--no-tags", "origin", "refs/heads/data-release:refs/remotes/origin/data-release")
    assert git(local, "rev-parse", "refs/remotes/origin/data-release") != first
    assert json.loads((local / "site/data/market.json").read_text(encoding="utf-8")) == {"version": 1}


@pytest.mark.parametrize("slot", ["morning", "pre_open"])
def test_non_post_close_keeps_existing_restore_and_fetch_paths(tmp_path, slot):
    anchor = "2026-11-26T08:40:00+08:00"
    clock = datetime.fromisoformat(anchor).timestamp()
    commands = []

    def run(command, *, env, **_kwargs):
        commands.append(command)
        if "src.scheduled_delivery" in command:
            assert "--official-close-overrides" not in command
            Path(env["GITHUB_OUTPUT"]).write_text("prepared=true\nsnapshot_id=snapshot-1\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="a" * 40 if "rev-parse" in command else "")

    def popen(*_args, **_kwargs):
        pytest.fail("only post-close starts an official-close watcher")

    result, status = coordinate_preparation(
        slot=slot, scheduled_for=anchor, slot_context="{}", notification_requested="true",
        snapshot_path=str(tmp_path / "market.json"), data_release_branch="data-release",
        initial_source_status="unknown", environ={}, clock=lambda: clock, run=run, popen=popen,
    )
    assert status == 0 and result["attempts"] == 1
    assert [command[:2] for command in commands].count(["git", "fetch"]) == 2


@pytest.mark.parametrize("slot", ["morning", "pre_open"])
@pytest.mark.parametrize("timed_out_stage", ["restore", "base_lookup", "prepare", "base_revalidation"])
def test_non_post_close_preserves_previous_timeout_output(tmp_path, capsys, slot, timed_out_stage):
    anchor = "2026-11-26T08:40:00+08:00"
    now = datetime.fromisoformat(anchor).timestamp()
    outputs = tmp_path / "outputs.txt"
    artifact = tmp_path / "preparation.json"
    base = "a" * 40
    fetch_count = 0

    def run(command, *, timeout, env, **_kwargs):
        nonlocal fetch_count
        if "src.data_release" in command:
            stage = "restore"
        elif "src.scheduled_delivery" in command:
            stage = "prepare"
        elif command[:2] == ["git", "fetch"]:
            fetch_count += 1
            stage = "base_lookup" if fetch_count == 1 else "base_revalidation"
        else:
            assert command[:2] == ["git", "rev-parse"]
            return subprocess.CompletedProcess(command, 0, stdout=base)
        if stage == timed_out_stage:
            raise subprocess.TimeoutExpired(command, timeout)
        if stage == "prepare":
            Path(env["GITHUB_OUTPUT"]).write_text(
                "prepared=true\nsnapshot_id=snapshot-1\nnotification_expected=false\n", encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0)

    result, status = coordinate_preparation(
        slot=slot, scheduled_for=anchor, slot_context="{}", notification_requested="true",
        snapshot_path=str(tmp_path / "market.json"), data_release_branch="data-release",
        initial_source_status="unknown",
        environ={"GITHUB_OUTPUT": str(outputs), "PREPARATION_RESULT_PATH": str(artifact)},
        clock=lambda: now, run=run,
    )
    prepare_timeout = timed_out_stage == "prepare"
    reason = "prepare_timeout_budget_exhausted" if prepare_timeout else f"{timed_out_stage}_timeout"
    expected_output = {}
    if timed_out_stage == "base_revalidation":
        expected_output.update({"snapshot_id": "snapshot-1", "notification_expected": "false"})
    expected_output.update({
        "prepared": "false", "reason": reason, "prepare_failure_reason": reason,
        "preparation_stage": timed_out_stage, "preparation_attempts": "1",
        "data_release_base_sha": base if timed_out_stage in {"prepare", "base_revalidation"} else "unknown",
        "data_release_current_sha": "unknown", "base_current": "false",
    })
    if prepare_timeout:
        expected_output["notification_expected"] = "true"
    assert status == 1
    assert dict(line.split("=", 1) for line in outputs.read_text(encoding="utf-8").splitlines()) == expected_output
    suffix = "" if prepare_timeout else " (TimeoutExpired)"
    assert capsys.readouterr().out == f"::error::scheduled_prepare_failed:{reason}{suffix}\n"
    assert json.loads(artifact.read_text(encoding="utf-8")) == result
    expected_fields = {
        "schema_version", "status", "reason", "stage", "started_at", "finished_at", "source_check_deadline",
        "delivery_deadline", "remaining_budget_seconds", "rebuild_count", "first_failure_reason",
        "candidate_identity", "stage_history",
    }
    if prepare_timeout:
        expected_fields |= {"attempts", "base_sha", "current_sha", "source_check_status", "remaining_seconds"}
    assert set(result) == expected_fields
    assert all(set(row) == {"stage", "started_at", "finished_at", "duration_seconds"} for row in result["stage_history"])
