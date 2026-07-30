from src.official_events import (
    MOPS_TERMS,
    TWSE_TERMS,
    _date_from_text,
    _headline_links,
    _mops_items,
    _rss_links,
    _twse_items,
    _twse_market_alert_items,
    _usgs_items,
    _is_recent_release,
    fetch_official_events,
)


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
    monkeypatch.setattr("src.official_events._twse_market_alert_items", lambda: [])
    monkeypatch.setattr("src.official_events._mops_items", lambda: [])
    monkeypatch.setattr("src.official_events._sec_items", lambda: [])
    monkeypatch.setattr("src.official_events._usgs_items", lambda: [])

    snapshot = fetch_official_events()

    assert snapshot["items"]
    assert all(item["relevance"] == "official" for item in snapshot["items"])
    assert not snapshot["errors"]


def test_rss_parser_keeps_official_timestamp_and_link():
    rows = _rss_links(
        "<rss><channel><item><title>CPI released</title><link>https://example.com/cpi</link><pubDate>Fri, 24 Jul 2026 08:30:00 -0400</pubDate></item></channel></rss>",
        "https://example.com/feed.xml",
    )
    assert rows[0][0] == "CPI released"
    assert rows[0][1] == "https://example.com/cpi"
    assert rows[0][2].endswith("+00:00")


def test_html_date_parser_accepts_roc_and_gregorian_release_dates():
    assert _date_from_text("\u767c\u5e03\u65e5\u671f\uff1a115\u5e747\u670829\u65e5") == "2026-07-28T16:00:00+00:00"
    assert _date_from_text("2026/07/29 16:00") == "2026-07-28T16:00:00+00:00"


def test_future_dated_release_is_not_considered_fresh():
    assert _is_recent_release("2099-01-01T00:00:00+00:00") is False


def test_mops_daily_api_keeps_material_ordinary_share_announcement(monkeypatch):
    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"result": {"data": [["115/07/29", "10:05:30", "2330", "TSMC", MOPS_TERMS[0]]]}}

    monkeypatch.setattr("src.official_events.requests.post", lambda *args, **kwargs: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    monkeypatch.setattr("src.official_events._taiwan_0050_codes", lambda: frozenset({"2330"}))

    items = _mops_items()

    assert items[0]["source_key"] == "mops"
    assert "2330" in items[0]["title"]
    assert items[0]["brief_summary"].startswith("0050｜2330")


def test_mops_non_0050_material_announcement_is_not_a_telegram_candidate(monkeypatch):
    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"result": {"data": [["115/07/29", "10:05:30", "8409", "Example", MOPS_TERMS[-1]]]}}

    monkeypatch.setattr("src.official_events.requests.post", lambda *args, **kwargs: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    monkeypatch.setattr("src.official_events._taiwan_0050_codes", lambda: frozenset({"2330"}))
    assert _mops_items() == []


def test_twse_market_alert_keeps_recent_systemic_share_disposition(monkeypatch):
    class Response:
        @staticmethod
        def json():
            return [{"Date": "1150729", "Code": "2330", "Name": "TSMC", "ReasonsOfDisposition": "example"}]

    monkeypatch.setattr("src.official_events._request", lambda _: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)

    items = _twse_market_alert_items()

    assert len(items) == 2
    assert all(item["source_key"] == "twse_market_alert" for item in items)


def test_twse_news_uses_roc_date_and_material_terms(monkeypatch):
    class Response:
        @staticmethod
        def json():
            return [{"Title": TWSE_TERMS[0], "Url": "https://twse.example/item", "Date": "1150729"}]

    monkeypatch.setattr("src.official_events._request", lambda _: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    item = _twse_items()[0]
    assert item["source_key"] == "twse"
    assert item["released_at"].startswith("2026-07-29")


def test_usgs_major_quake_becomes_a_first_party_candidate(monkeypatch):
    class Response:
        @staticmethod
        def json():
            return {"features": [{"properties": {"mag": 7.1, "time": 1_785_000_000_000, "place": "Japan", "url": "https://usgs.example/event"}}]}

    monkeypatch.setattr("src.official_events._request", lambda _: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    item = _usgs_items()[0]
    assert item["source_key"] == "usgs"
