from src.official_events import _headline_links, _rss_links, _twse_items, _usgs_items, fetch_official_events


def test_headline_links_are_deduplicated_and_resolved():
    links = _headline_links(
        '<a href="/x">CPI release</a><a href="/x">CPI release again</a>',
        "https://www.bls.gov/bls/newsrels.htm",
    )
    assert links == [("CPI release", "https://www.bls.gov/x", None)]


def test_official_event_fetch_keeps_only_material_release_titles(monkeypatch):
    class Response:
        text = '<rss><channel><item><title>Consumer Price Index released</title><link>https://www.bls.gov/release</link><pubDate>Fri, 24 Jul 2026 08:30:00 -0400</pubDate></item></channel></rss>'

        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.official_events.requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    monkeypatch.setattr("src.official_events._twse_items", lambda: [])
    monkeypatch.setattr("src.official_events._sec_items", lambda: [])
    monkeypatch.setattr("src.official_events._usgs_items", lambda: [])
    snapshot = fetch_official_events()

    assert snapshot["items"]
    assert all(item["short_label"] in {"Fed／貨幣政策", "重大總經", "能源／通膨"} for item in snapshot["items"])
    assert not snapshot["errors"]


def test_rss_parser_keeps_official_timestamp_and_link():
    rows = _rss_links(
        "<rss><channel><item><title>CPI released</title><link>https://example.com/cpi</link><pubDate>Fri, 24 Jul 2026 08:30:00 -0400</pubDate></item></channel></rss>",
        "https://example.com/feed.xml",
    )
    assert rows[0][0] == "CPI released"
    assert rows[0][1] == "https://example.com/cpi"
    assert rows[0][2].endswith("+00:00")


def test_twse_news_uses_roc_date_and_material_terms(monkeypatch):
    class Response:
        def json(self):
            return [{"Title": "台積電重大訊息公告", "Url": "https://twse.example/item", "Date": "1150729"}]
    monkeypatch.setattr("src.official_events._request", lambda _: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    item = _twse_items()[0]
    assert item["short_label"] == "台股官方訊息"
    assert item["released_at"].startswith("2026-07-29")


def test_usgs_major_quake_becomes_a_first_party_candidate(monkeypatch):
    class Response:
        def json(self):
            return {"features": [{"properties": {"mag": 7.1, "time": 1_785_000_000_000, "place": "Japan", "url": "https://usgs.example/event"}}]}
    monkeypatch.setattr("src.official_events._request", lambda _: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    item = _usgs_items()[0]
    assert item["short_label"] == "黑天鵝／地緣"
    assert item["source_key"] == "usgs"
