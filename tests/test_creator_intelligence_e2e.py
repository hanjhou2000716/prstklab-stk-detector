from src.creator_intelligence_e2e import run_creator_intelligence_e2e


def test_creator_intelligence_e2e_is_offline_and_fail_closed():
    report = run_creator_intelligence_e2e()

    assert report["ok"] is True
    assert all(report["checks"].values())
    assert report["network_used"] is False
    assert report["secrets_used"] is False
    assert report["production_side_effects"] is False


def test_creator_intelligence_e2e_keeps_creator_and_market_evidence_separate():
    report = run_creator_intelligence_e2e()

    assert report["consensus"]["is_investment_signal"] is False
    assert report["correlation"]["evidence_alignment"] == "aligned"
    assert report["news"]["taiwan_excluded"] >= 1
    assert "fed" in report["news"]["us_providers"]
