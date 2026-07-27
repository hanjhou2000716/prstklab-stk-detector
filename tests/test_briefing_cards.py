from src.briefing_cards import build_briefing_snapshot


def test_midday_briefing_includes_japan_korea_and_public_observation_cards():
    snapshot = {
        "indices": [
            {"ticker": "TAIEX", "name": "臺灣加權指數", "price": 43800},
            {"ticker": "NIKKEI", "name": "日經225", "price": 40000},
            {"ticker": "KOSPI", "name": "韓國綜合", "price": 3000},
        ],
        "quotes": [{"ticker": "2330", "name": "台積電", "price": 1200}],
        "macro_quotes": [{"ticker": "DXY", "change_percent": 0.2}],
        "events": {"items": [{
            "brief_title": "台指價格訊號觸發｜急跌｜警戒",
            "summary": "臺灣加權指數 43,800",
            "trigger": "日內變動 -1.5%，達 -1.0% 警戒門檻。",
            "market_context": "同步觀察費半與 Nasdaq。",
        }]},
    }

    briefing = build_briefing_snapshot(snapshot, "midday")

    assert briefing["title"] == "台股午報儀表板"
    assert {item["ticker"] for item in briefing["markets"]} == {"TAIEX", "2330", "NIKKEI", "KOSPI"}
    assert [item["title"] for item in briefing["observations"]] == [
        "台股總經", "台積電／半導體", "科技產業", "利率匯率", "風險提醒",
    ]
    assert "台指" in briefing["observations"][0]["event"]
    assert "美國10年債殖利率" in briefing["observations"][3]["event"]
