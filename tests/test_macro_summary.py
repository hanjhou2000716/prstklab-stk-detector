from src.macro_summary import build_macro_summary

def test_macro_summary_keeps_no_event_conclusion_and_risk_context():
    summary = build_macro_summary({"is_major": False}, {"taiwan": {"label": "台股", "summary": "波動率觀察"}, "us": {"label": "美股", "sentiment": {"label": "恐慌"}}})
    assert summary["items"][0]["text"] == "今日無重大市場事件，持續觀察。"
    assert "美股情緒：恐慌" in [item["text"] for item in summary["items"]]


def test_macro_summary_discloses_program_as_a_source_link_not_a_transcript():
    summary = build_macro_summary(
        {"is_major": False},
        {"taiwan": {"label": "台股", "summary": "波動率觀察"}, "us": {"label": "美股", "summary": "波動率觀察"}},
        {"title": "最新節目標題", "url": "https://www.youtube.com/watch?v=abc", "source": "游庭皓的財經皓角｜YouTube"},
    )

    program = summary["items"][-1]
    assert program["label"] == "節目更新"
    assert program["url"] == "https://www.youtube.com/watch?v=abc"
    assert "完整內容" in summary["notice"]
