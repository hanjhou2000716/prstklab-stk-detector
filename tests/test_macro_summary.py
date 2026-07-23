from src.macro_summary import build_macro_summary

def test_macro_summary_keeps_no_event_conclusion_and_risk_context():
    summary = build_macro_summary({"is_major": False}, {"taiwan": {"label": "台股", "summary": "波動率觀察"}, "us": {"label": "美股", "sentiment": {"label": "恐慌"}}})
    assert summary["items"][0]["text"] == "今日無重大市場事件，持續觀察。"
    assert "美股情緒：恐慌" in [item["text"] for item in summary["items"]]
