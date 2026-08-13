from __future__ import annotations

from urllib.parse import urlsplit

from src.news_feed_adapters import feed_catalog, fetch_official_market_news


class Response:
    def __init__(self, *, text: str = "", payload=None, status: int = 200):
        self.text = text
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self._payload


def test_catalog_keeps_disabled_nasdaq_endpoint_explicit():
    nasdaq = next(item for item in feed_catalog() if item["provider_id"] == "nasdaq")
    assert nasdaq["enabled"] is False
    assert "documented" in nasdaq["disabled_reason"]


def test_rss_adapter_normalizes_fed_atom_and_isolates_other_provider_failure():
    xml = """
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry><title>FOMC policy statement</title><link href='https://www.federalreserve.gov/newsevents/pressreleases/a.htm'/><updated>2026-08-14T01:00:00Z</updated></entry>
    </feed>
    """

    def requester(url, **_kwargs):
        if (urlsplit(url).hostname or "").lower().endswith("sec.gov"):
            raise TimeoutError("sec timeout")
        return Response(text=xml)

    result = fetch_official_market_news("us", requester=requester)
    assert [story["provider"] for story in result["stories"]] == ["fed"]
    assert result["stories"][0]["source_tier"] == "official"
    assert any(item["provider"] == "sec" and item["status"] == "failed" for item in result["source_health"])
    assert any(item["provider"] == "sec" for item in result["errors"])


def test_json_adapter_normalizes_twse_rows_and_disabled_sources_do_not_call():
    calls = []

    def requester(url, **_kwargs):
        calls.append(url)
        return Response(payload=[{"title": "TWSE market notice", "url": "https://www.twse.com.tw/news/1", "published_at": "2026-08-14T08:00:00Z"}])

    result = fetch_official_market_news("taiwan", requester=requester)
    assert result["stories"][0]["provider"] == "twse"
    assert result["stories"][0]["published_at"].endswith("+00:00")
    assert len(calls) == 2  # TWSE and MOPS; no US provider is requested.


def test_http_429_is_recorded_without_retrying_or_aborting():
    calls = []

    def requester(url, **_kwargs):
        calls.append(url)
        return Response(status=429)

    result = fetch_official_market_news("us", requester=requester)
    assert result["stories"] == []
    assert len(calls) == 2  # SEC and Fed each attempted once.
    assert all(item["status"] == "rate_limited" for item in result["source_health"] if item["provider"] in {"sec", "fed"})
