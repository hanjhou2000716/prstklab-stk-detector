from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_acceptance_runbook_keeps_external_evidence_fail_closed():
    document = (ROOT / "docs" / "zero-cost-production-acceptance.md").read_text(encoding="utf-8")
    assert "not_checked` is not a pass" in document
    assert "needs_reverify" in document
    assert "one explicitly designated test chat" in document
    assert "restore the previous Pages release" in document


def test_acceptance_runbook_requires_lineage_and_receipts():
    document = (ROOT / "docs" / "zero-cost-production-acceptance.md").read_text(encoding="utf-8")
    for term in ("release", "snapshot", "alert", "trace", "delivery_receipts"):
        assert term in document
    assert "raw email" in document
