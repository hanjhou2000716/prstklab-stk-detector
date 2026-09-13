from src.event_output import four_section_event, short_event_message


def test_event_output_uses_four_sections_and_compact_short_message():
    event = {"short_label": "台指價格訊號", "market_direction": "下跌", "market_move": "-2.4%", "risk_level": "警戒", "trigger": "台指日內下跌。", "why_important": "波動擴大。", "market_context": "可能連動費半。", "stock_observation": "觀察台股電子權值。"}
    assert list(four_section_event(event)) == ["event", "importance", "market_impact", "watch"]
    assert short_event_message(event).startswith("🟠 台指價格訊號，下跌")
    assert short_event_message(event).count("｜") == 0
    assert all(code not in short_event_message(event) for code in ("R0", "R1", "R2", "R3", "R4"))
    assert len(short_event_message(event)) <= 60


def test_event_output_uses_the_same_structured_fact_summary():
    event = {
        "notification_topic": "fed",
        "structured_fact": {
            "subject": "聯準會",
            "action": "表示",
            "object": "若通膨過熱，可能延後降息",
        },
        "summary": "三名消息人士表示",
    }
    message = short_event_message(event)
    assert message.startswith("🟡 Fed，聯準會表示")
    assert "延後降息" in message
    assert len(message) <= 60

