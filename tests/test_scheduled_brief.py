from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduled_brief import build_brief, resolve_slot


def test_resolves_morning_slot_in_taiwan_time():
    now = datetime(2026, 7, 23, 6, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert resolve_slot("auto", now) == "morning"


def test_brief_uses_slot_label_and_market_direction():
    snapshot = {"quotes": [{"ticker": "2330", "change_percent": 1.25}]}
    assert build_brief(snapshot, "intraday") == "盤中｜2330📈+1.2%"


def test_brief_handles_missing_data_neutrally():
    assert build_brief({"quotes": []}, "morning") == "晨報｜市場資料暫時無法取得"
