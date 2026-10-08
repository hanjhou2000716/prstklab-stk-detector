import json
import subprocess
from datetime import datetime
from pathlib import Path

from src.market_source_watch import TAIPEI
from src.scheduled_preparation import coordinate_preparation, preparation_window


def test_post_close_window_keeps_revalidation_budget_after_1440_source_check():
    anchor = "2026-10-08T14:20:00+08:00"
    started = datetime.fromisoformat("2026-10-08T14:32:22+08:00").timestamp()
    window = preparation_window("post_close", anchor, started)
    assert datetime.fromtimestamp(window.first_attempt_deadline, TAIPEI).isoformat() == "2026-10-08T14:40:00+08:00"
    assert datetime.fromtimestamp(window.overall_deadline, TAIPEI).isoformat() == "2026-10-08T14:45:00+08:00"
    assert window.overall_deadline > window.first_attempt_deadline


def _run_same_slot_preparation(tmp_path: Path, *, source_updated: bool):
    anchor = "2026-10-08T14:20:00+08:00"
    local = datetime.fromisoformat("2026-10-08T14:32:22+08:00").timestamp()
    snapshot_path = tmp_path / "market.json"
    old_rows = [
        {"ticker": "TAIEX", "quote_date": "2026-10-07", "price": 49806.37, "change": 114.2, "change_percent": 0.23},
        {"ticker": "TXF", "quote_date": "2026-10-07", "price": 49979, "change": -103, "change_percent": -0.21},
    ]
    snapshot_path.write_text(json.dumps({"indices": old_rows}), encoding="utf-8")
    current_rows = [
        {"ticker": "TAIEX", "quote_date": "2026-10-08", "price": 49313.44, "change": -492.93, "change_percent": -0.99},
        {"ticker": "TXF", "quote_date": "2026-10-08", "price": 49349, "change": -619, "change_percent": -1.24},
    ]
    source_result_path: Path | None = None
    prepare_count = 0
    commands: list[list[str]] = []
    source_waits: list[float | None] = []

    class SourceProcess:
        def wait(self, timeout=None):
            nonlocal local
            source_waits.append(timeout)
            local = datetime.fromisoformat("2026-10-08T14:40:00+08:00").timestamp()
            return 0

        def poll(self):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def popen(command, *, env, stdout, stderr):
        nonlocal source_result_path
        source_result_path = Path(command[command.index("--result-file") + 1])
        final_rows = current_rows if source_updated else old_rows
        source_result_path.write_text(json.dumps({
            "status": "source_watch_cutoff_reached",
            "cash_target_date": "2026-10-08", "futures_target_date": "2026-10-08",
            "last_probe": {
                "cash_quote": {**final_rows[0], "source_attempts": [{"source": "twse_mi_index_json", "outcome": "verified", "observed_date": "2026-10-08"}]},
                "futures_quote": {**final_rows[1], "source_attempts": [{"source": "taifex_daily_table", "outcome": "verified", "observed_date": "2026-10-08"}]},
            },
        }), encoding="utf-8")
        return SourceProcess()

    def run(command, *, timeout, env, check, text):
        nonlocal prepare_count
        commands.append(list(command))
        if command[0] == "git" and command[1] == "rev-parse":
            return subprocess.CompletedProcess(command, 0, stdout="a" * 40 + "\n")
        if "src.scheduled_delivery" in command:
            prepare_count += 1
            output = Path(env["GITHUB_OUTPUT"])
            output.write_text(
                f"prepared=true\nsnapshot_id=snapshot-{prepare_count}\nnotification_expected=true\n",
                encoding="utf-8",
            )
            if prepare_count == 2:
                override_file = Path(command[command.index("--official-close-overrides") + 1])
                overrides = json.loads(override_file.read_text(encoding="utf-8"))
                assert overrides["cash_quote"]["price"] == 49313.44
                assert overrides["futures_quote"]["price"] == 49349
                snapshot_path.write_text(json.dumps({"indices": current_rows}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="")
        return subprocess.CompletedProcess(command, 0, stdout="")

    outputs = tmp_path / "outputs.txt"
    summary = tmp_path / "summary.md"
    result, status = coordinate_preparation(
        slot="post_close", scheduled_for=anchor, slot_context="{}",
        notification_requested="true", snapshot_path=str(snapshot_path),
        data_release_branch="data-release", initial_source_status="source_watch_cutoff_reached",
        environ={"GITHUB_OUTPUT": str(outputs), "GITHUB_STEP_SUMMARY": str(summary)},
        clock=lambda: local, run=run, popen=popen,
    )
    return result, status, outputs.read_text(encoding="utf-8"), prepare_count, commands, source_waits


def test_preparation_uses_overall_deadline_after_final_source_check_when_candidate_is_unchanged(tmp_path):
    result, status, outputs, count, _, source_waits = _run_same_slot_preparation(tmp_path, source_updated=False)
    assert status == 0
    assert count == 1
    assert result["status"] == "ready"
    assert "data_release_sha=" in outputs
    assert "prepared=true" in outputs
    assert source_waits == [8 * 60 + 23]
    assert result["source_check_deadline"] == "2026-10-08T06:40:00+00:00"
    assert result["delivery_deadline"] == "2026-10-08T06:50:00+00:00"
    assert result["candidate_identity"]["snapshot_id"] == "snapshot-1"
    assert result["first_failure_reason"] == ""
    assert result["stage_history"]


def test_source_update_rebuild_uses_the_same_verified_close_observations(tmp_path):
    result, status, _outputs, count, commands, _source_waits = _run_same_slot_preparation(tmp_path, source_updated=True)
    assert status == 0
    assert count == 2
    assert result["rebuild_reason"] == "verified_source_update"
    assert any("--official-close-overrides" in command for command in commands)
