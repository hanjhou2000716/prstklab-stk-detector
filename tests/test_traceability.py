import pytest

from src.traceability import load_traceability, validate_traceability


def test_repository_traceability_ledger_is_valid_and_explicit_about_external_gates():
    ledger = load_traceability()
    assert ledger["baseline"] == "123395ee"
    assert any(entry["status"] == "BLOCKED" for entry in ledger["entries"])
    assert any(entry["status"] == "NEEDS_REVERIFY" for entry in ledger["entries"])


def test_traceability_rejects_duplicate_requirements():
    payload = {"entries": [{
        "requirement": "REQ-1", "task": "x", "implementation": ["a"],
        "verification": ["b"], "evidence": "e", "regression": "r", "status": "PASS",
    }, {
        "requirement": "REQ-1", "task": "y", "implementation": ["c"],
        "verification": ["d"], "evidence": "e", "regression": "r", "status": "PASS",
    }]}
    with pytest.raises(ValueError, match="unique"):
        validate_traceability(payload)


def test_traceability_pass_requires_evidence():
    payload = {"entries": [{
        "requirement": "REQ-1", "task": "x", "implementation": ["a"],
        "verification": ["b"], "evidence": "", "regression": "r", "status": "PASS",
    }]}
    with pytest.raises(ValueError, match="objective evidence"):
        validate_traceability(payload)
