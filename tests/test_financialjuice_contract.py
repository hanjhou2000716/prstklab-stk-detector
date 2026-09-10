from src.financialjuice_contract import (
    financialjuice_canonical_fact_key,
    financialjuice_material_fact_version,
    financialjuice_notification_state,
    normalize_financialjuice,
)


def test_fj_fact_identity_excludes_commentary_translation_and_transport_fields() -> None:
    base = {
        "original_headline": "Fed keeps rates unchanged as inflation cools",
        "event_type": "fed",
        "chinese_translation": "聯準會維持利率不變，通膨降溫",
        "ai_commentary": "評論版本 A",
        "possible_impact": "科技股估值仍待觀察",
        "source_published_at": "2026-09-07T01:00:00Z",
        "transport_received_at": "2026-09-07T01:01:00Z",
    }
    revised = {
        **base,
        "chinese_translation": "聯準會維持政策利率，通膨略有放緩",
        "ai_commentary": "評論版本 B",
        "possible_impact": "美元與殖利率可能影響科技股",
        "transport_received_at": "2026-09-07T01:04:00Z",
    }
    assert financialjuice_canonical_fact_key(base) == financialjuice_canonical_fact_key(revised)
    assert financialjuice_material_fact_version(base) == financialjuice_material_fact_version(revised)


def test_fj_source_timestamp_is_not_backfilled_from_legacy_published_at() -> None:
    result = normalize_financialjuice({
        "original_headline": "Oil supply update",
        "published_at": "2026-09-07T01:00:00Z",
        "received_at": "2026-09-07T01:01:00Z",
    })
    assert result["published_at"].endswith("+00:00")
    assert result["source_published_at"] is None


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


def test_vendor_8_remains_ordinary_metadata_and_does_not_change_risk() -> None:
    result = normalize_financialjuice({
        "original_headline": "Policy update",
        "importance": 8,
        "event_type": "policy",
    })
    state = financialjuice_notification_state(result)
    assert state["vendor_priority_notification"] is False
    assert state["vendor_priority_exception"] is False
    assert state["delivery_authorized"] is False
    assert state["status"] == "pending_confirmation"
    assert state["delivery_policy"] == "none"
    assert state["risk_level"] == "R2"
    assert result["prstk_risk"]["notification_eligible"] is False


def test_vendor_7_is_not_priority_notification() -> None:
    result = normalize_financialjuice({
        "original_headline": "Routine update",
        "importance": 7,
        "event_type": "policy",
    })
    state = financialjuice_notification_state(result)
    assert state["vendor_priority_notification"] is False
    assert state["status"] == "pending_confirmation"
    assert state["vendor_priority_reason"] == "vendor_importance_below_9_or_missing"


def test_vendor_priority_accepts_string_and_decimal_importance_without_risk_upgrade() -> None:
    result = normalize_financialjuice({
        "original_headline": "Policy update",
        "importance": "8.9/10",
        "event_type": "policy",
    })
    state = financialjuice_notification_state(result)
    assert result["vendor_importance"] == 8
    assert state["vendor_priority_notification"] is False
    assert state["status"] == "pending_confirmation"
    assert result["prstk_risk"]["prstk_risk_level"] == "R2"
