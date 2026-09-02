from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src import official_event_monitor as monitor
from src.official_event_monitor import build_official_event_brief, event_key, select_official_event
from src.release_gate import ReleaseGateResult
from src.telegram_client import TextDeliveryReceipt, alert_mini_app_url


def test_black_swan_needs_related_market_confirmation_before_delivery():
    candidate = {
        "importance": "high-risk",
        "url": "https://earthquake.usgs.gov/example",
        "title": "USGS event",
    }
    snapshot = {
        "official_events": {"items": [candidate]},
        "events": {"items": [{**candidate, "impact_confirmation": {"confirmed": False}}]},
    }
    assert select_official_event(snapshot, now=datetime(2026, 7, 27, 20, 0, tzinfo=ZoneInfo("Asia/Taipei"))) is None

    snapshot["events"]["items"][0]["impact_confirmation"] = {"confirmed": True}
    selected = select_official_event(snapshot, now=datetime(2026, 7, 27, 20, 0, tzinfo=ZoneInfo("Asia/Taipei")))
    assert selected["url"] == candidate["url"]


def test_monitor_prioritizes_current_official_event_source():
    snapshot = {
        "events": {"items": [{"title": "third party headline"}]},
        "official_events": {"items": [{"title": "FOMC statement", "url": "https://www.federalreserve.gov/x"}]},
    }
    assert select_official_event(snapshot)["title"] == "FOMC statement"


def test_first_run_baseline_suppresses_official_headline_but_keeps_price_signal():
    snapshot = {
        "official_events": {"items": [{"title": "FOMC statement", "url": "https://www.federalreserve.gov/x"}]},
        "events": {"items": [{"kind": "market_signal", "brief_title": "price alert", "instrument": {"ticker": "NASDAQ"}}]},
    }
    event = select_official_event(snapshot, baseline_official=True)
    assert event["kind"] == "market_signal"


def test_monitor_event_key_is_stable_and_changes_for_a_new_release():
    first = {"title": "CPI", "url": "https://www.bls.gov/a", "released_at": "2026-07-25T08:30:00-04:00"}
    second = {**first, "released_at": "2026-08-25T08:30:00-04:00"}
    assert event_key(first) == event_key(first)
    assert event_key(first) != event_key(second)
    assert event_key(None) == "none"


def test_changed_event_before_delivery_is_safe_noop(monkeypatch, tmp_path):
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(monitor, "prepare_snapshot", lambda: ({}, {"title": "new event"}))
    monkeypatch.setattr(monitor, "event_key", lambda event: "new-key" if event else "none")

    assert monitor.send_current_event("old-key") is False

    result = output.read_text(encoding="utf-8")
    assert "sent=false" in result
    assert "reason=event_changed_before_delivery" in result


def test_official_event_key_applies_two_hour_topic_cooldown_but_allows_escalation():
    first = {
        "title": "first source title", "source_key": "bls-cpi", "topic_key": "bls-cpi",
        "released_at": "2026-07-25T08:30:00+00:00",
    }
    revised = {**first, "title": "revised source title", "released_at": "2026-07-25T09:10:00+00:00"}
    escalated = {**revised, "escalation": True}
    assert event_key(first) == event_key(revised)
    # Escalation is a state transition of the same canonical event, not a
    # second event identity; the ledger handles the upgrade notification.
    assert event_key(first) == event_key(escalated)


def test_monitor_brief_is_neutral_and_watch_sized():
    brief = build_official_event_brief({"short_label": "Fed／貨幣政策", "title": "Federal Reserve issues FOMC statement with a long title"})
    assert brief.startswith("🟡 Fed｜")
    assert all(level not in brief for level in ("R0", "R1", "R2", "R3", "R4"))
    assert len(brief) <= 30


def test_monitor_selects_threshold_price_signal_when_no_official_release_exists():
    snapshot = {
        "official_events": {"items": []},
        "events": {"items": [{
            "kind": "market_signal", "brief_title": "台指價格訊號觸發｜急跌｜高風險",
            "instrument": {"ticker": "TAIEX", "quote_date": "2026-07-27"}, "risk_level": "高風險",
        }]},
    }
    event = select_official_event(snapshot)
    assert event is not None
    assert build_official_event_brief(event).startswith("🔴 TAIEX｜")


def test_realtime_external_projection_adds_eligible_fj_to_shared_event_lane(monkeypatch, tmp_path):
    source = tmp_path / "observations.json"
    monkeypatch.setattr(monitor, "external_observations_path", lambda: source)
    source.write_text("[]", encoding="utf-8")
    row = {
        "observation_id": "fj-realtime-1",
        "item_id": "fj-item-1",
        "source": "financialjuice",
        "original_headline": "Oil supply risk",
        "event_type": "energy",
        "importance": 8,
        "source_url": "https://financialjuice.com/item/1",
        "published_at": "2026-08-21T01:00:00Z",
        "received_at": "2026-08-21T01:01:00Z",
        "parser_version": "financialjuice-v1",
        "public_safe": True,
    }
    monkeypatch.setattr(monitor, "load_external_observations", lambda _path: ([row], 0))
    monkeypatch.setattr(monitor, "_external_observations_configured", lambda: False)
    snapshot = {"events": {"items": []}, "source_health": {"sources": []}}
    result = monitor._attach_realtime_external_events(snapshot)
    assert result["financialjuice_priority_events"][0]["vendor_importance"] == 8
    assert result["financialjuice_priority_events"][0]["notification_status"] == "eligible"
    assert result["events"]["items"][0]["source_key"] == "financialjuice"
    assert result["financialjuice_release_contract"]["ok"] is True


def test_realtime_external_projection_keeps_below_threshold_visible_without_selection(monkeypatch, tmp_path):
    source = tmp_path / "observations.json"
    source.write_text("[]", encoding="utf-8")
    row = {
        "observation_id": "fj-realtime-7",
        "source": "financialjuice",
        "original_headline": "Routine market note",
        "importance": 7,
        "source_url": "https://financialjuice.com/item/7",
        "public_safe": True,
    }
    monkeypatch.setattr(monitor, "external_observations_path", lambda: source)
    monkeypatch.setattr(monitor, "load_external_observations", lambda _path: ([row], 0))
    monkeypatch.setattr(monitor, "_external_observations_configured", lambda: False)
    result = monitor._attach_realtime_external_events({"events": {"items": []}})
    assert result["financialjuice_priority_decisions"][0]["notification_status"] == "not_eligible"
    assert result["financialjuice_priority_events"] == []
    assert result["events"]["items"][0]["notification_status"] == "not_eligible"


def test_realtime_external_projection_removes_stale_blocked_fj_rows(monkeypatch, tmp_path):
    source = tmp_path / "observations.json"
    source.write_text("[]", encoding="utf-8")
    row = {
        "observation_id": "fj-realtime-clean-1",
        "source": "financialjuice",
        "original_headline": "Blocked source row",
        "importance": 10,
        "source_identity_verified": False,
        "source_url": "https://financialjuice.com/item/clean-1",
        "public_safe": True,
    }
    stale_fj = {
        "kind": "external_event",
        "source": "FinancialJuice",
        "source_key": "financialjuice",
        "observation_id": "stale-fj-row",
        "public_signal_eligible": False,
        "title": "PR run failed: FinancialJuice semantics",
    }
    retained = {"kind": "market_signal", "title": "Keep official signal"}
    monkeypatch.setattr(monitor, "load_external_observations", lambda _path: ([row], 0))
    monkeypatch.setattr(monitor, "_external_observations_configured", lambda: False)
    result = monitor._attach_realtime_external_events({"events": {"items": [stale_fj, retained]}})
    items = result["events"]["items"]
    assert items == [retained]
    assert result["financialjuice_priority_events"] == []


def test_price_signal_key_changes_for_escalation_or_a_direction_reversal():
    warning = {"kind": "market_signal", "instrument": {"ticker": "SOX", "quote_date": "2026-07-27"}, "risk_level": "警戒", "signal_state": "急跌:警戒:down"}
    high = {**warning, "risk_level": "高風險", "signal_state": "急跌:高風險:down"}
    rebound = {**warning, "signal_state": "突然大漲:警戒:up"}
    assert event_key(warning) == event_key(warning)
    assert event_key(warning) != event_key(high)
    assert event_key(warning) != event_key(rebound)


def test_taiex_high_risk_signal_repeats_once_per_quote_hour_but_not_every_poll():
    base = {
        "kind": "market_signal",
        "risk_level": "高風險",
        "signal_state": "急跌:高風險:擴大:daily",
        "realert_interval_minutes": 60,
        "instrument": {"ticker": "TAIEX", "quote_date": "2026-07-28", "quote_time": "2026-07-28T10:05:00+08:00"},
    }
    same_hour = {**base, "instrument": {**base["instrument"], "quote_time": "2026-07-28T10:50:00+08:00"}}
    next_hour = {**base, "instrument": {**base["instrument"], "quote_time": "2026-07-28T11:00:00+08:00"}}
    assert event_key(base) == event_key(same_hour)
    assert event_key(base) != event_key(next_hour)


def test_taiwan_market_window_prefers_taiex_and_suppresses_unrelated_price_signals():
    snapshot = {
        "official_events": {"items": []},
        "events": {"items": [
            {"kind": "market_signal", "brief_title": "WTI價格訊號觸發", "instrument": {"ticker": "WTI"}},
            {"kind": "market_signal", "brief_title": "台指價格訊號觸發", "instrument": {"ticker": "TAIEX"}},
        ]},
    }
    now = datetime(2026, 7, 28, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert select_official_event(snapshot, now)["instrument"]["ticker"] == "TAIEX"
    only_wti = {**snapshot, "events": {"items": [snapshot["events"]["items"][0]]}}
    assert select_official_event(only_wti, now) is None


def test_official_monitor_suppresses_budgeted_event_before_renderer(monkeypatch, tmp_path):
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    event = {
        "event_key": "iran-1",
        "event_cluster_key": "iran-1",
        "title": "Iran statement",
        "risk_level": "警戒",
        "source_url": "https://example.test/iran",
    }
    monkeypatch.setattr(monitor, "prepare_snapshot", lambda: ({"snapshot_id": "snap-1"}, event))
    monkeypatch.setattr(monitor, "event_key", lambda _event: "iran-1")
    monkeypatch.setattr(monitor, "verify_release_for_delivery", lambda **_kwargs: ReleaseGateResult(True, release_id="release-1", snapshot_id="snap-1"))
    monkeypatch.setattr(monitor, "_observe_event", lambda *_args, **_kwargs: {"should_remind": True})

    class FakeLedger:
        def __init__(self):
            self.records = {}
            self.decisions = []

        def delivery_history(self):
            return [{"event_key": "iran-1", "importance": "警戒", "sent_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()}]

        def record_decision(self, event, decision):
            self.decisions.append((event, decision))
            return decision

        def save(self):
            return None

    monkeypatch.setattr(monitor, "EventLedger", FakeLedger)
    monkeypatch.setattr(monitor, "send_text_briefs_audited", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("delivery must not run")))

    assert monitor.send_current_event() is False
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=alert_budget:cooldown" in text


def test_financialjuice_event_uses_immediate_text_lane_and_records_receipt(monkeypatch, tmp_path):
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    event = {
        "source_key": "financialjuice",
        "source": "FinancialJuice",
        "event_cluster_key": "fj-cluster-1",
        "observation_id": "fj-observation-1",
        "vendor_importance": 9,
        "vendor_priority_notification": True,
        "notification_status": "eligible",
        "notification_reason": "vendor_priority_importance_ge_8",
        "prstk_risk": {"prstk_risk_level": "R2"},
        "title": "Oil supply risk",
    }
    snapshot = {"snapshot_id": "snap-1", "events": {"items": [event]}}
    monkeypatch.setattr(monitor, "prepare_snapshot", lambda: (snapshot, event))
    monkeypatch.setattr(monitor, "event_key", lambda _event: "fj-key")
    monkeypatch.setattr(monitor, "verify_release_for_delivery", lambda **_kwargs: ReleaseGateResult(True, release_id="release-1", snapshot_id="snap-1"))
    monkeypatch.setattr(monitor, "_observe_event", lambda *_args, **_kwargs: {"should_remind": True})
    monkeypatch.setattr(monitor, "get_settings", lambda: type("Settings", (), {
        "telegram_ready": True, "telegram_bot_token": "token", "telegram_chat_ids": ("test",),
        "dashboard_url": "https://example.test/app",
    })())
    recorded = {}

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, payload, **_kwargs):
            recorded.update(payload)

        def save(self):
            return None

    monkeypatch.setattr(monitor, "EventLedger", FakeLedger)
    monkeypatch.setattr(monitor, "decide_alert_budget", lambda *_args: {"allowed": True, "reason": "material_change", "event_key": "fj-key"})
    monkeypatch.setattr(monitor, "deliver_financialjuice_event", lambda *_args, **_kwargs: {
        "status": "delivered", "notification_key": "financialjuice:key", "receipts": [{
            "recipient_hash": "hash", "delivery_status": "delivered", "message_id": 7,
        }],
    })
    assert monitor.send_current_event() is True
    text = output.read_text(encoding="utf-8")
    assert "sent=true" in text
    assert "delivery_mode=text" in text
    assert "delivered_count=1" in text
    assert "risk=R2" in text
    assert recorded["delivery_status"] == "delivered"


def test_official_text_lane_passes_alert_deep_link(monkeypatch, tmp_path):
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    event = {
        "source_key": "official",
        "source": "issuer",
        "event_cluster_key": "official-cluster-1",
        "observation_id": "official-observation-1",
        "notification_status": "eligible",
        "prstk_risk": {"prstk_risk_level": "R2"},
        "title": "Official update",
    }
    snapshot = {"snapshot_id": "snap-1", "events": {"items": [event]}}
    monkeypatch.setattr(monitor, "prepare_snapshot", lambda: (snapshot, event))
    monkeypatch.setattr(monitor, "event_key", lambda _event: "official-key")
    monkeypatch.setattr(monitor, "verify_release_for_delivery", lambda **_kwargs: ReleaseGateResult(True, release_id="release-1", snapshot_id="snap-1"))
    monkeypatch.setattr(monitor, "_observe_event", lambda *_args, **_kwargs: {"should_remind": True})
    monkeypatch.setattr(monitor, "build_official_event_brief", lambda _event: "官方事件")
    monkeypatch.setattr(monitor, "get_settings", lambda: type("Settings", (), {
        "telegram_ready": True, "telegram_bot_token": "token", "telegram_chat_ids": ("test",),
        "dashboard_url": "https://example.test/app",
    })())
    monkeypatch.setattr(monitor, "decide_alert_budget", lambda *_args: {"allowed": True, "reason": "budget_available", "event_key": "official-key"})

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, payload, **_kwargs):
            return payload

        def save(self):
            return None

    monkeypatch.setattr(monitor, "EventLedger", FakeLedger)
    captured = {}

    def sender(**kwargs):
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=1, observation_id=kwargs.get("observation_id", ""),
        ),)

    monkeypatch.setattr(monitor, "send_text_briefs_audited", sender)
    assert monitor.send_current_event() is True
    assert captured["target_url"] == alert_mini_app_url(
        "https://example.test/app",
        alert_id="official-cluster-1",
        release_id="release-1",
        snapshot_id="snap-1",
        observation_id="official-observation-1",
    )
