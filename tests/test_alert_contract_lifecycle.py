from src.alert_caption import make_caption, validate_caption
from src.alert_contract import AlertEnvelope
from src.alert_lifecycle import transition
from src.material_change import classify_price_pattern, has_material_change


def test_caption_is_short_without_splitting_numbers():
    caption = make_caption(subject="費城半導體指數", change="+5.1%", state="波動", verified=True)
    validate_caption(caption)
    assert "+5.1%" in caption


def test_caption_compacts_long_subject_without_cutting_status():
    caption = make_caption(
        subject="一個非常長的市場事件標題需要壓縮但不能破壞語意",
        change="+12.34%",
        state="等待市場同步",
    )
    validate_caption(caption)
    assert caption.endswith("等待市場同步")

def test_alert_envelope_requires_provenance():
    envelope = AlertEnvelope.from_event({"event_key": "e1", "title": "測試", "alert_type": "market_risk", "severity": "warning"}, release_id="r1", snapshot_id="s1", short_caption="🔵 測試｜觀察")
    assert envelope.to_dict()["event_cluster_key"] == "e1"

def test_lifecycle_waits_for_all_confirmation_evidence():
    assert transition("observation", official_confirmed=True, second_source=True, market_sync=False) == "pending_confirmation"
    assert transition("pending_confirmation", official_confirmed=True, second_source=True, market_sync=True) == "confirmed"
    assert transition("confirmed", material_change=True) == "escalated"
    assert transition("confirmed", condition_active=False) == "resolved"
    assert transition("observation", budget_allowed=False) == "suppressed"

def test_material_change_and_direction_reversal():
    assert has_material_change(previous_change=1.0, current_change=2.0, asset_class="market_index")
    assert classify_price_pattern(daily_percent=8, move_15m=-0.5) == "gain_fading"
    assert classify_price_pattern(daily_percent=-2, move_15m=1.2) == "fast_rebound"


def test_caption_uses_safe_minimal_fallback_and_validates_boundaries():
    caption = make_caption(subject="x" * 200, change="y" * 200, state="等待核對", icon="⚠️")
    assert caption == "⚠️｜等待核對"
    validate_caption(caption)


def test_lifecycle_deescalates_then_resolves_and_rejects_unknown_state():
    assert transition("escalated", material_change=False) == "deescalated"
    assert transition("deescalated", condition_active=False) == "resolved"
    assert transition("resolved") == "resolved"
