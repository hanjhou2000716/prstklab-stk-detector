from src.external_intelligence_e2e import run_external_intelligence_dry_run


def test_external_intelligence_offline_dry_run_is_fail_closed():
    result = run_external_intelligence_dry_run()
    assert result["network_used"] is False
    assert result["secrets_used"] is False
    assert result["formal_delivery"] is False
    assert result["email_observation"]["parse_status"] in {"identified", "parsed", "normalized"}
    assert result["external_risk"]["level"] == "R2"
    assert result["external_risk"]["notification"]["status"] == "pending"
    assert result["creator_release"]["status"] == "ready"
