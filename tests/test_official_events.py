from src.official_events import _headline_links, fetch_official_events


def test_headline_links_are_deduplicated_and_resolved():
    links = _headline_links(
        '<a href="/x">CPI release</a><a href="/x">CPI release again</a>',
        "https://www.bls.gov/bls/newsrels.htm",
    )
    assert links == [("CPI release", "https://www.bls.gov/x", None)]


def test_official_event_fetch_keeps_only_material_release_titles(monkeypatch):
    class Response:
        text = '<a href="/release">Consumer Price Index released</a><time datetime="2026-07-25T08:30:00-04:00"></time><a href="/other">Other item</a>'

        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.official_events.requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("src.official_events._is_recent_release", lambda released_at: released_at is not None)
    snapshot = fetch_official_events()

    assert snapshot["items"]
    assert all(item["short_label"] in {"Fed／貨幣政策", "重大總經"} for item in snapshot["items"])
    assert not snapshot["errors"]
