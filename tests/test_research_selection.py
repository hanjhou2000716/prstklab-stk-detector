import json
import sys
from datetime import UTC, datetime

from src import research_selection
from src.research_attempts import STRATEGIES, rule_version
from src.research_selection import _write_env, resolve_strategy_selection
from src.run_research_report import selected_strategy_keys


def _report(markets, trading_date, *, incomplete=()):
    incomplete = set(incomplete)
    return {
        "sources": [
            {
                "market": market,
                "strategy": strategy,
                "scan_trading_date": trading_date,
                "scan_state": "building" if (market, strategy) in incomplete else "complete",
                "candidate_state": "building" if (market, strategy) in incomplete else "complete",
                "rule_version": rule_version(market, strategy),
                "strategy_version_state": "current",
                "historical_fallback": False,
            }
            for market in markets for strategy in STRATEGIES
        ]
    }


def test_resume_incomplete_scans_all_strategies_when_prior_report_is_for_older_slot():
    result = resolve_strategy_selection(
        target_market="us", requested_strategy="all", action="resume_incomplete",
        slot_key="us:2026-10-26:close-research",
        previous_report=_report(("us",), "2026-10-23"),
    )

    assert result["selection_status"] == "scan_selected"
    assert result["selected_strategies"] == list(STRATEGIES)
    assert result["required_market_strategy_pairs"] == [f"us:{name}" for name in STRATEGIES]
    assert result["selected_market_strategy_pairs"] == [f"us:{name}" for name in STRATEGIES]


def test_resume_incomplete_returns_valid_noop_only_when_due_date_is_complete():
    result = resolve_strategy_selection(
        target_market="us", requested_strategy="all", action="resume_incomplete",
        slot_key="us:2026-10-26:close-research",
        previous_report=_report(("us",), "2026-10-26"),
    )

    assert result["selection_status"] == "current_noop"
    assert result["selected_strategies"] == []
    assert result["reason"] == "research_slot_already_current"
    assert len(result["already_current_pairs"]) == len(STRATEGIES)


def test_resume_incomplete_selects_only_the_incomplete_strategy_for_the_due_date():
    result = resolve_strategy_selection(
        target_market="taiwan", requested_strategy="all", action="resume_incomplete",
        slot_key="taiwan:2026-10-27:close-research",
        previous_report=_report(("taiwan",), "2026-10-27", incomplete={("taiwan", "value")}),
    )

    assert result["selection_status"] == "scan_selected"
    assert result["selected_strategies"] == ["value"]
    assert result["required_market_strategy_pairs"] == ["taiwan:value"]


def test_both_market_slot_scans_a_strategy_when_either_market_is_stale():
    report = _report(("taiwan", "us"), "2026-10-27")
    for row in report["sources"]:
        if row["market"] == "us" and row["strategy"] == "momentum":
            row["scan_trading_date"] = "2026-10-26"
    result = resolve_strategy_selection(
        target_market="both", requested_strategy="all", action="resume_incomplete",
        slot_key="taiwan:2026-10-27:close-research,us:2026-10-27:close-research",
        previous_report=report,
    )

    assert result["selected_strategies"] == ["momentum"]
    assert result["required_market_strategy_pairs"] == ["us:momentum"]
    assert result["selected_market_strategy_pairs"] == ["us:momentum"]


def test_both_market_resume_selects_only_the_stale_pair_for_a_requested_strategy():
    report = _report(("taiwan", "us"), "2026-10-27")
    report["sources"] = [row for row in report["sources"] if row["strategy"] == "value"]
    report["sources"][-1]["scan_trading_date"] = "2026-10-26"
    result = resolve_strategy_selection(
        target_market="both", requested_strategy="value", action="resume_incomplete",
        slot_key="taiwan:2026-10-27:close-research,us:2026-10-27:close-research",
        previous_report=report,
    )

    assert result["selected_strategies"] == ["value"]
    assert result["required_market_strategy_pairs"] == ["us:value"]


def test_pair_selection_exports_only_due_market_strategy_flags(tmp_path, monkeypatch):
    env = tmp_path / "github-env.txt"
    monkeypatch.setenv("GITHUB_ENV", str(env))
    _write_env({
        "selected_strategies": ["momentum"],
        "selected_market_strategy_pairs": ["us:momentum"],
        "selection_status": "scan_selected",
        "reason": "",
    }, due=True)

    values = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines())
    assert values["RUN_US_MOMENTUM"] == "true"
    assert values["RUN_TAIWAN_MOMENTUM"] == "false"
    assert values["SCANNED_PAIRS"] == "us:momentum"


def test_retry_cooldown_for_one_market_does_not_starve_other_market(tmp_path, monkeypatch):
    slot = "taiwan:2026-10-27:close-research,us:2026-10-27:close-research"
    report = _report(("taiwan", "us"), "2026-10-27", incomplete={("taiwan", "value")})
    for row in report["sources"]:
        if row["market"] == "us" and row["strategy"] == "value":
            row["scan_trading_date"] = "2026-10-26"
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps(report), encoding="utf-8")
    attempts = tmp_path / "attempts.json"
    slot_identity = f"taiwan:2026-10-27:close-research:value:{rule_version('taiwan', 'value')}"
    attempts.write_text(json.dumps({
        "schema_version": 1,
        "slots": {
            slot_identity: {
                "attempts": 1,
                "last_attempt_at": datetime.now(UTC).isoformat(),
            }
        },
    }), encoding="utf-8")
    env = tmp_path / "github-env.txt"
    output = tmp_path / "github-output.txt"
    summary = tmp_path / "github-summary.txt"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCAN_MODE", "production")
    monkeypatch.setenv("RESEARCH_DUE", "true")
    monkeypatch.setenv("GITHUB_ENV", str(env))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(sys, "argv", [
        "research_selection", "--target-market", "both", "--target-strategy", "all",
        "--action", "resume_incomplete", "--slot-key", slot,
        "--previous-report", str(previous), "--attempts", str(attempts),
    ])

    assert research_selection.main() == 0
    result = json.loads((tmp_path / "research-artifacts" / "research-selection.json").read_text(encoding="utf-8"))
    assert result["selection_status"] == "scan_selected_with_suppressed_pairs"
    assert result["selected_market_strategy_pairs"] == ["us:value"]
    assert result["suppressed_market_strategy_pairs"] == {"taiwan:value": "retry_cooldown"}
    env_values = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines())
    assert env_values["RUN_US_VALUE"] == "true"
    assert env_values["RUN_TAIWAN_VALUE"] == "false"


def test_selected_market_strategy_pairs_preserve_only_the_pair_actually_scanned():
    assert selected_strategy_keys(
        "both", "all", "momentum", "us:momentum",
    ) == {("us", "momentum")}


def test_selected_market_strategy_pairs_reject_out_of_scope_identity():
    import pytest

    with pytest.raises(ValueError, match="selected research market/strategy pair is invalid"):
        selected_strategy_keys("us", "all", "momentum", "taiwan:momentum")
