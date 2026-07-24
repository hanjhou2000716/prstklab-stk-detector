from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduled_brief import build_brief, resolve_slot


def test_resolves_morning_slot_in_taiwan_time():
    now = datetime(2026, 7, 23, 6, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("auto", now) == "morning"


def test_us_premarket_uses_2100_taiwan_during_new_york_dst():
    summer_2100 = datetime(2026, 7, 23, 21, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    summer_2200 = datetime(2026, 7, 23, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("auto", summer_2100) == "us_premarket"
    assert resolve_slot("auto", summer_2200) is None


def test_us_premarket_uses_2200_taiwan_during_new_york_standard_time():
    winter_2100 = datetime(2026, 1, 22, 21, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    winter_2200 = datetime(2026, 1, 22, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("auto", winter_2100) is None
    assert resolve_slot("auto", winter_2200) == "us_premarket"


def test_brief_uses_slot_label_and_market_direction():
    snapshot = {"quotes": [{"ticker": "2330", "change_percent": 1.25}]}
    assert build_brief(snapshot, "intraday") == "盤中｜2330📈+1.2%"


def test_brief_handles_missing_data_neutrally():
    assert build_brief({"quotes": []}, "morning") == "晨報｜市場資料暫時無法取得"


def test_brief_preserves_market_move_when_event_label_is_too_long():
    snapshot = {
        "quotes": [{"ticker": "NVDA", "change_percent": -3.25}],
        "events": {"items": [{"short_label": "重大政策與半導體供應鏈長篇事件標籤"}]},
    }

    brief = build_brief(snapshot, "morning")

    assert len(brief) <= 30
    assert brief.endswith("NVDA📉-3.2%")
