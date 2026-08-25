from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "health_state.py"
SPEC = importlib.util.spec_from_file_location("railway_health_state_test", MODULE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_health_state_snapshot_is_detached_and_preserves_public_defaults() -> None:
    original = module.snapshot_health()
    assert original["status"] == "ok"
    assert original["creator"]["status"] == "not_checked"
    original["creator"]["status"] = "mutated"
    assert module.snapshot_health()["creator"]["status"] == "not_checked"


def test_health_state_updates_are_serialized() -> None:
    workers = [
        threading.Thread(target=module.update_health, kwargs={"component": "monitor", "last_cycle_completed_at": str(index)})
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    snapshot = module.snapshot_health()
    assert snapshot["monitor"]["last_cycle_completed_at"] in {"0", "1", "2", "3"}


def test_health_summary_distinguishes_no_event_configuration_and_failure() -> None:
    summary = module.summarize_health({
        "gdelt": {"status": "no_event"},
        "gmail": {"status": "configuration_missing"},
        "news": {"status": "failed"},
    })
    assert summary["overall_state"] == "partial"
    assert summary["no_event_count"] == 1
    assert summary["configuration_missing_count"] == 1
    assert summary["failure_count"] == 1
    assert summary["component_statuses"] == {
        "gdelt": "no_event", "gmail": "configuration_missing", "news": "failed",
    }


def test_health_summary_marks_all_empty_scan_as_healthy() -> None:
    summary = module.summarize_health({
        "gdelt": {"status": "no_new_content"},
        "financialjuice": {"status": "scan_complete"},
    })
    assert summary["overall_state"] == "healthy"
    assert summary["no_event_count"] == 1
    assert summary["failure_count"] == 0


def test_health_history_is_bounded_and_exposes_only_component_states() -> None:
    module.HEALTH_HISTORY.clear()
    module.update_health("gdelt", status="rate_limited", error="HTTP_429", token="must-not-leak")
    module.record_health_sample(recorded_at=module.datetime(2026, 8, 25, tzinfo=module.UTC))
    history = module.health_history_summary(now=module.datetime(2026, 8, 25, 1, tzinfo=module.UTC))
    assert history["sample_count"] == 1
    assert history["windows"]["24h"]["failure_count"] == 1
    assert history["samples"][0]["component_statuses"]["gdelt"] == "rate_limited"
    assert "token" not in str(history)


def test_health_history_caps_samples() -> None:
    module.HEALTH_HISTORY.clear()
    for index in range(module.MAX_HEALTH_HISTORY + 5):
        module.record_health_sample(recorded_at=module.datetime(2026, 8, 1 + index // 24, index % 24, tzinfo=module.UTC))
    assert len(module.HEALTH_HISTORY) == module.MAX_HEALTH_HISTORY
    assert module.health_history_summary()["sample_count"] == module.MAX_HEALTH_HISTORY
