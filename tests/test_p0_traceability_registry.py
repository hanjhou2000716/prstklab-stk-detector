from pathlib import Path


REGISTRY = Path(__file__).resolve().parents[1] / "docs" / "p0-requirement-traceability.md"


def test_traceability_registry_covers_all_p0_requirements_once():
    text = REGISTRY.read_text(encoding="utf-8")
    for number in range(1, 30):
        marker = f"| P0-{number:02d} "
        assert text.count(marker) == 1, marker


def test_traceability_registry_has_explicit_evidence_and_status_columns():
    text = REGISTRY.read_text(encoding="utf-8")
    assert "| Requirement | Task / implementation | Verification and evidence | Regression / preservation | Status |" in text
    assert "NEEDS_REVERIFY" in text
    assert "PASS / LOCKED" in text
    assert "final `COMPLETE` claim" in text
