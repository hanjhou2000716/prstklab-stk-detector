from src.event_output import four_section_event, short_event_message


def test_event_output_uses_four_sections_and_compact_short_message():
    event = {"short_label": "台指價格訊號", "market_direction": "下跌", "market_move": "-2.4%", "risk_level": "警戒", "trigger": "台指日內下跌。", "why_important": "波動擴大。", "market_context": "可能連動費半。", "stock_observation": "觀察台股電子權值。"}
    assert list(four_section_event(event)) == ["event", "importance", "market_impact", "watch"]
    assert short_event_message(event).startswith("快訊｜台指價格訊號｜下跌｜-2.4%｜警戒")
    assert len(short_event_message(event)) <= 30

