from src.financialjuice_contract import financialjuice_notification_state, normalize_financialjuice


def test_vendor_10_does_not_become_r4_without_evidence() -> None:
    result = normalize_financialjuice({
        "original_headline": "Oil supply update",
        "importance": "10/10",
        "event_type": "energy",
    })
    assert result["vendor_importance"] == 10
    assert result["vendor_importance_is_not_risk"] is True
    assert result["prstk_risk"]["prstk_risk_level"] == "R2"
    assert result["pending_reasons"] == ["等待官方核對", "等待市場同步"]


def test_fj_reaches_r4_only_after_official_and_market_sync() -> None:
    result = normalize_financialjuice({
        "original_headline": "Confirmed supply disruption",
        "importance": 10,
        "event_type": "energy",
        "official_confirmed": True,
        "market_sync_confirmed": True,
    })
    assert result["prstk_risk"]["prstk_risk_level"] == "R4"
    assert financialjuice_notification_state(result)["status"] == "eligible"


def test_fj_contract_is_public_safe_and_time_normalized() -> None:
    result = normalize_financialjuice({
        "original_headline": "headline",
        "source_published_at": "2026-08-13T01:00:00Z",
        "fetched_at": "2026-08-13T01:01:00Z",
        "vendor_translation": "translation",
        "vendor_analysis": "analysis",
        "vendor_possible_impact": "impact",
        "body": "must not be copied",
    })
    assert result["published_at"].endswith("+00:00")
    assert result["fetched_at"].endswith("+00:00")
    assert "body" not in result
    assert result["public_safe"] is True


def test_fj_observation_id_is_stable() -> None:
    record = {"original_headline": "headline", "published_at": "2026-08-13T01:00:00Z"}
    assert normalize_financialjuice(record)["observation_id"] == normalize_financialjuice(dict(record))["observation_id"]
