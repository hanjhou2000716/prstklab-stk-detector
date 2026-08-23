from scripts.verify_intelligence_contracts import run_audit


def test_offline_intelligence_contract_audit_passes() -> None:
    result = run_audit()
    assert result["status"] == "pass"
    assert all(result["checks"].values())
    assert result["external_acceptance_required"] == ["Gmail", "Railway", "Pages", "Telegram"]
