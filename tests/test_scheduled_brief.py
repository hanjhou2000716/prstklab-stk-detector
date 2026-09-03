from datetime import datetime
from zoneinfo import ZoneInfo

from src.alert_budget import decide_alert_budget
from src.scheduled_brief import briefing_correlation, build_brief, resolve_slot


def test_taiwan_price_brief_includes_the_current_percent_move():
    snapshot = {
        "indices": [{"ticker": "TAIEX", "change_percent": -2.1}],
        "events": {"items": [{
            "kind": "market_signal",
            "pattern": "急跌",
            "instrument": {"ticker": "TAIEX", "change_percent": -2.1},
        }]},
    }
    assert build_brief(snapshot, "intraday") == "盤中｜台指 -2.1%｜急跌"


def test_resolves_morning_slot_in_taiwan_time():
    now = datetime(2026, 7, 23, 6, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("auto", now) == "morning"


def test_us_premarket_uses_2100_taiwan_during_new_york_dst():
    summer_2100 = datetime(2026, 7, 23, 21, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    summer_2200 = datetime(2026, 7, 23, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("auto", summer_2100) == "us_premarket"
    assert resolve_slot("auto", summer_2200) is None


def test_us_premarket_stays_at_2100_taiwan_during_new_york_standard_time():
    winter_2100 = datetime(2026, 1, 22, 21, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    winter_2200 = datetime(2026, 1, 22, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("auto", winter_2100) == "us_premarket"
    assert resolve_slot("auto", winter_2200) is None


def test_external_dispatch_accepts_2100_us_premarket_all_year():
    summer = datetime(2026, 7, 27, 21, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    winter = datetime(2026, 1, 22, 21, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("us_premarket", summer, strict_window=True) == "us_premarket"
    assert resolve_slot("us_premarket", winter, strict_window=True) == "us_premarket"


def test_external_dispatch_rejects_an_early_declared_pre_open_slot():
    early = datetime(2026, 7, 27, 8, 5, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("pre_open", early, strict_window=True) is None


def test_external_dispatch_accepts_the_declared_0845_pre_open_slot():
    scheduled = datetime(2026, 7, 27, 8, 45, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("pre_open", scheduled, strict_window=True) == "pre_open"


def test_brief_uses_slot_label_and_market_direction():
    snapshot = {"quotes": [{"ticker": "2330", "change_percent": 1.25}]}
    assert build_brief(snapshot, "intraday") == "盤中｜2330📈+1.2%"


def test_taiwan_session_uses_taiex_and_does_not_promote_brent_price_signal():
    snapshot = {
        "indices": [{"ticker": "TAIEX", "change_percent": -0.8}],
        "quotes": [{"ticker": "2330", "change_percent": -1.2}],
        "events": {"items": [{
            "kind": "market_signal",
            "brief_title": "BRENT價格訊號觸發｜急跌｜高風險",
            "instrument": {"ticker": "BRENT"},
        }]},
    }

    assert build_brief(snapshot, "midday") == "午報｜TAIEX🟰-0.8%"


def test_taiwan_session_keeps_verified_international_major_event_when_taiwan_has_no_signal():
    snapshot = {
        "indices": [{"ticker": "TAIEX", "change_percent": 0.2}],
        "events": {"items": [{
            "kind": "major_event",
            "brief_title": "Fed／貨幣政策｜重要事件｜觀察",
        }]},
    }

    assert build_brief(snapshot, "intraday") == "盤中｜Fed／貨幣政策｜重要事件｜觀察"


def test_brief_handles_missing_data_neutrally():
    assert build_brief({"quotes": []}, "morning") == "晨報｜市場資料暫時無法取得"


def test_brief_preserves_market_move_when_event_label_is_too_long():
    snapshot = {
        "quotes": [{"ticker": "NVDA", "change_percent": -3.25}],
        "events": {"items": [{"short_label": "重大政策與半導體供應鏈長篇事件標籤"}]},
    }

    brief = build_brief(snapshot, "morning")

    assert len(brief) <= 40
    assert brief.endswith("NVDA📉-3.2%")


def test_scheduled_brief_correlation_uses_published_observation_id():
    correlation = briefing_correlation(
        {"snapshot_id": "snap123456789012"},
        "midday",
        {"instrument": {"observation_id": "obs123"}},
    )
    assert correlation == {
        "trace_id": "brief-snap123456789012-midday",
        "snapshot_id": "snap123456789012",
        "observation_id": "obs123",
    }


def test_scheduled_delivery_uses_shared_budget_for_repeated_event():
    now = datetime(2026, 8, 5, 2, 0, tzinfo=ZoneInfo("UTC"))
    result = decide_alert_budget(
        {"event_key": "brief-event", "importance": "warning"},
        [{"event_key": "brief-event", "importance": "warning", "sent_at": now.isoformat()}],
        now=now,
    )
    assert result["allowed"] is False
    assert result["reason"] == "cooldown"
