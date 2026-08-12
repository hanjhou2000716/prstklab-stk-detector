import json
from pathlib import Path

from jsonschema import validate

from src.backtest_release import build_backtest_release
from src.strategy_registry import validate_strategy_release


def _report(*, status="complete", gaps=None):
    return {
        "status": status,
        "survivorship_audit": {"status": "pass", "snapshot_dates": ["2020-12-31"]},
        "methodology": {"fixed_windows": []},
        "strategies": {"momentum": {"data_gaps": list(gaps or []), "windows": {}}},
    }


def test_backtest_release_is_deterministic_and_registry_bound():
    config = {"data_version": "pit-v1", "strategy_versions": {"momentum": "m1"}, "strategy_parameters": {"momentum": {"top_n": 5}}}
    first = build_backtest_release(_report(), market="us", config=config, code_commit="abc")
    second = build_backtest_release(_report(), market="us", config=config, code_commit="abc")
    assert first == second
    assert first["publication_state"] == "ready"
    assert first["strategy_registry"][0]["strategy_version"] == "m1"
    assert len(first["strategy_registry"][0]["parameter_hash"]) == 16
    assert first["strategy_registry"][0]["backtest_release"] == first["backtest_release"]
    assert validate_strategy_release(first["strategy_registry"][0]) == []


def test_backtest_release_blocks_gaps_and_matches_schema():
    contract = build_backtest_release(_report(gaps=[{"reason": "missing fundamentals"}]), market="taiwan", config={})
    assert contract["publish_eligible"] is False
    assert contract["blocking_reasons"]
    schema = json.loads(Path("schemas/backtest-release.schema.json").read_text(encoding="utf-8"))
    validate(contract, schema)


def test_backtest_release_preserves_net_performance_and_audit_provenance():
    report = _report()
    report["strategies"]["momentum"]["summary"] = {
        "test": {
            "trade_count": 12,
            "cumulative_net_return_percent": 8.5,
            "sharpe": 0.71,
            "max_drawdown_percent": -4.2,
            "private_internal_field": "must not escape",
        }
    }
    contract = build_backtest_release(report, market="us", config={})
    assert contract["performance_summary"]["momentum"]["test"]["sharpe"] == 0.71
    assert "private_internal_field" not in contract["performance_summary"]["momentum"]["test"]
    assert contract["survivorship_audit"]["status"] == "pass"
    schema = json.loads(Path("schemas/backtest-release.schema.json").read_text(encoding="utf-8"))
    validate(contract, schema)
