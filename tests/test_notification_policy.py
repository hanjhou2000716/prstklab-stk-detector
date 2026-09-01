from datetime import UTC, datetime, timedelta

from src.event_ledger import EventLedger, is_secondary_commentary, notification_theme_key, taiwan_investor_priority
from src.official_event_monitor import select_official_event


def _fed(title: str, *, source: str = "yahoo", official: bool = False) -> dict:
    return {
        "source_key": source,
        "source_tier": "official" if official else "discovery",
        "topic_key": "fed-rate-outlook",
        "title": title,
        "notification_status": "eligible",
        "risk_level": "R2",
        "official_confirmed": official,
    }


def test_public_formatter_theme_converges_across_providers_and_urls():
    assert notification_theme_key(_fed("JPMorgan sees a cautious Fed")) == "fed-rate-outlook"
    assert notification_theme_key(_fed("Analyst expects higher rates", source="anue")) == "fed-rate-outlook"


def test_same_theme_is_suppressed_for_two_hours_but_official_update_realerts(tmp_path):
    ledger = EventLedger(tmp_path / "events.json")
    start = datetime(2026, 9, 1, 1, tzinfo=UTC)
    first = _fed("Fed outlook turns cautious")
    assert ledger.theme_decision(first, now=start)["reason"] == "new_theme"
    ledger.mark_theme_notified(first, now=start)
    repeat = _fed("Another analyst repeats the cautious outlook")
    suppressed = ledger.theme_decision(repeat, now=start + timedelta(minutes=20))
    assert suppressed["allowed"] is False
    assert suppressed["reason"] == "same_theme_within_2h"
    assert suppressed["notification_theme_key"] == "fed-rate-outlook"
    official = _fed("FOMC decision published", source="fomc", official=True)
    update = ledger.theme_decision(official, now=start + timedelta(minutes=30))
    assert update["allowed"] is True
    # The explicit policy projection distinguishes an official decision from
    # the preceding rate-outlook theme, so it is a new eligible material lane.
    assert update["reason"] == "new_theme"


def test_price_theme_suppresses_small_extension_and_allows_escalation(tmp_path):
    ledger = EventLedger(tmp_path / "events.json")
    start = datetime(2026, 9, 1, 1, tzinfo=UTC)
    first = {"kind": "market_signal", "instrument": {"ticker": "NVDA", "change_percent": 1.6}, "risk_level": "R2"}
    ledger.theme_decision(first, now=start)
    ledger.mark_theme_notified(first, now=start)
    small = {"kind": "market_signal", "instrument": {"ticker": "NVDA", "change_percent": 1.8}, "risk_level": "R2"}
    assert ledger.theme_decision(small, now=start + timedelta(minutes=10))["reason"] == "same_theme_within_2h"
    escalation = {"kind": "market_signal", "instrument": {"ticker": "NVDA", "change_percent": 4.0}, "risk_level": "R2"}
    assert ledger.theme_decision(escalation, now=start + timedelta(minutes=20))["allowed"] is True


def test_secondary_commentary_is_digest_only_without_material_confirmation():
    assert is_secondary_commentary(_fed("Fed preview from an analyst")) is True
    assert is_secondary_commentary({**_fed("Fed decision"), "official_confirmed": True, "source_tier": "official"}) is False


def test_taiwan_session_priority_prefers_taiwan_and_global_r4_bypasses():
    now = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)  # 10:00 Asia/Taipei
    taiwan = {"kind": "market_signal", "instrument": {"ticker": "2330"}, "risk_level": "R2"}
    commentary = _fed("Fed preview")
    emergency = {"risk_level": "R4", "official_confirmed": True, "market_sync_confirmed": True, "systemic_emergency": True}
    assert taiwan_investor_priority(taiwan, now=now) == 1
    assert taiwan_investor_priority(commentary, now=now) == 3
    assert taiwan_investor_priority(emergency, now=now) == 0


def test_selector_routes_secondary_commentary_to_digest_and_keeps_taiwan_event():
    now = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)
    taiwan = {"kind": "market_signal", "instrument": {"ticker": "2330", "change_percent": -1.8}, "risk_level": "R2"}
    snapshot = {"official_events": {"items": []}, "events": {"items": [
        {**_fed("Fed preview"), "public_observation": True},
        taiwan,
    ]}}
    selected = select_official_event(snapshot, now=now)
    assert selected["instrument"]["ticker"] == "2330"
    assert snapshot["events"]["items"][0]["notification_status"] == "digest_only"
