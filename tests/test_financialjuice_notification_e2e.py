from src.financialjuice_notification import financialjuice_caption
from src.financialjuice_notification_e2e import run_financialjuice_notification_e2e


def test_financialjuice_notification_e2e_is_offline_and_replay_safe() -> None:
    result = run_financialjuice_notification_e2e()
    assert result["ok"] is True
    assert result["network_used"] is False
    assert result["secrets_used"] is False
    assert result["production_side_effects"] is False
    assert result["checks"]["vendor_score_does_not_change_risk"] is True
    assert result["checks"]["partial_delivery_isolated"] is True
    assert result["checks"]["retry_only_failed_recipient"] is True
    assert result["checks"]["replay_suppressed"] is True


def test_financialjuice_caption_includes_one_internal_risk_grade() -> None:
    caption = financialjuice_caption({
        "title": "Oil supply disruption",
        "vendor_importance": 8,
        "prstk_risk": {"prstk_risk_level": "R2"},
    })
    assert "FJ 8/10" in caption
    assert caption.count("R2") == 1
