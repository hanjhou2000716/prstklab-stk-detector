from __future__ import annotations

from urllib.parse import urlsplit

from src.news_feed_adapters import feed_catalog, fetch_official_market_news
from src.news_intelligence import provider_registry


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


def test_catalog_uses_the_canonical_provider_registry_without_identity_drift():
    registry = {item["provider_id"]: item for item in provider_registry()}
    catalog = {item["provider_id"]: item for item in feed_catalog()}
    assert set(catalog) == {"twse", "mops", "sec", "fed", "nasdaq"}
    for provider_id, item in catalog.items():
        canonical = registry[provider_id]
        assert item["url"] == canonical.get("feed_url", "")
        assert item["source_tier"] == canonical["authority_tier"]
        assert item["enabled"] == canonical["enabled"]
        assert item["markets"] == canonical["markets"]


def test_discovery_providers_never_enter_official_feed_catalog():
    provider_ids = {item["provider_id"] for item in feed_catalog()}
    assert "google_news" not in provider_ids
    assert "anue" not in provider_ids


def test_rss_adapter_normalizes_fed_atom_and_isolates_other_provider_failure():
    xml = """
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry><title>FOMC policy statement</title><link href='https://www.federalreserve.gov/newsevents/pressreleases/a.htm'/><updated>2026-08-14T01:00:00Z</updated></entry>
    </feed>
    """

    def requester(url, **_kwargs):
        host = (urlsplit(url).hostname or "").lower()
        if host == "www.sec.gov":
            raise TimeoutError("sec timeout")
        return Response(text=xml)

    result = fetch_official_market_news("us", requester=requester)
    assert [story["provider"] for story in result["stories"]] == ["fed"]
    assert result["stories"][0]["source_tier"] == "official"
    assert any(item["provider"] == "sec" and item["status"] == "failed" for item in result["source_health"])
    assert any(item["provider"] == "sec" for item in result["errors"])
    failed = next(item for item in result["source_health"] if item["provider"] == "sec")
    assert failed["parser_error_count"] == 1
    assert failed["last_parsed_at"] is None
    assert failed["latency_ms"] >= 0


def test_json_adapter_normalizes_twse_rows_and_disabled_sources_do_not_call():
    calls = []

    def requester(url, **_kwargs):
        calls.append(url)
        return Response(payload=[{"title": "TWSE market notice", "url": "https://www.twse.com.tw/news/1", "published_at": "2026-08-14T08:00:00Z"}])

    result = fetch_official_market_news("taiwan", requester=requester)
    assert result["stories"][0]["provider"] == "twse"
    assert result["stories"][0]["published_at"].endswith("+00:00")
    assert len(calls) == 2  # TWSE and MOPS; no US provider is requested.
    assert all("checked_at" in item for item in result["source_health"])


def test_http_429_is_recorded_without_retrying_or_aborting():
    calls = []

    def requester(url, **_kwargs):
        calls.append(url)
        return Response(status=429)

    result = fetch_official_market_news("us", requester=requester)
    assert result["stories"] == []
    assert len(calls) == 2  # SEC and Fed each attempted once.
    assert all(item["status"] == "rate_limited" for item in result["source_health"] if item["provider"] in {"sec", "fed"})


def test_custom_multimarket_source_is_fetched_for_the_requested_market():
    result = fetch_official_market_news(
        "us",
        requester=lambda *_args, **_kwargs: Response(text="""
            <rss><channel><item>
              <title>US market breadth</title>
              <link>https://www.cnyes.com/news/1</link>
              <pubDate>Tue, 18 Aug 2026 12:00:00 GMT</pubDate>
            </item></channel></rss>
        """),
        catalog=[{
            "provider_id": "anue", "market": "taiwan", "markets": ["taiwan", "us"],
            "kind": "rss", "url": "https://www.cnyes.com/rss", "enabled": True,
            "source_tier": "market", "timeout_seconds": 8,
        }],
    )
    assert result["market"] == "us"
    assert result["stories"][0]["market"] == "us"
