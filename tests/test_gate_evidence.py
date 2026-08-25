from __future__ import annotations

import copy

from src.gate_evidence import load_registry, validate_registry


def test_gate_evidence_registry_covers_p0_and_reports_external_debt_without_false_pass():
    result = validate_registry(load_registry())
    assert result["status"] == "needs_reverify"
    assert result["error_count"] == 0
    assert result["requirement_count"] == 29
    assert result["locked_count"] == 29
    assert result["open_completion_debt_count"] > 0


def test_strict_gate_rejects_open_debt():
    result = validate_registry(load_registry(), strict=True)
    assert result["status"] == "fail"
    assert any("zero OPEN" in error for error in result["errors"])


def test_locked_requirement_without_evidence_fails_closed():
    document = copy.deepcopy(load_registry())
    document["requirements"][0]["evidence"] = []
    result = validate_registry(document)
    assert result["status"] == "fail"
    assert any("P0-01" in error and "evidence" in error for error in result["errors"])
