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
        "台股總經", "台積電／半導體", "科技產業", "利率／匯率／黃金能源", "加密市場", "風險提醒",
    ]
    assert "台指" in briefing["observations"][0]["event"]
    assert "美國10年債殖利率" in briefing["observations"][3]["event"]


def test_midday_briefing_explains_cross_market_move_and_technical_location():
    context = {"window_days": 20, "long_window_days": 60, "low": 100, "high": 120, "long_low": 90, "long_high": 130, "position_pct": 90, "zone": "接近20日壓力區", "status": "ok"}
    snapshot = {
        "indices": [
            {"ticker": "TAIEX", "price": 118, "change_percent": 1.2, "technical_context": context},
            {"ticker": "TPEx", "price": 115, "change_percent": 0.8, "technical_context": context},
            {"ticker": "NASDAQ", "price": 100, "change_percent": 1.0, "technical_context": context},
            {"ticker": "SOX", "price": 200, "change_percent": 1.5, "technical_context": context},
        ],
        "quotes": [{"ticker": "2330", "price": 1100, "change_percent": 2.0, "technical_context": context}],
        "events": {"items": [{
            "brief_title": "半導體需求更新",
            "summary": "公開財報顯示資本支出展望上修。",
            "why_important": "可能改變 AI 供應鏈需求預期，但仍需後續公司指引確認。",
            "market_context": "費半、Nasdaq 與台積電同步上行，形成跨市場確認。",
            "stock_observation": "觀察下一交易時段是否維持同向，以及成交量是否放大。",
        }]},
    }

    briefing = build_briefing_snapshot(snapshot, "midday")
    semiconductor = briefing["observations"][1]
    assert "台積電 1,100.00" in semiconductor["event"]
    assert "同步上行" in semiconductor["market_impact"]
    assert "20日區間" in semiconductor["watch"]
    assert "60日" in semiconductor["watch"]
