from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.append(str(Path(__file__).parents[1] / "railway-monitor"))

from supabase_email_store import SupabaseEmailStore  # noqa: E402


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def test_cursor_round_trip_uses_singleton_and_hides_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if method == "GET":
            return _Response(200, current)
        current[:] = [dict(kwargs["json"])]
        return _Response(201, current)

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "service-role-secret")
    assert store.cursor()["last_history_id"] is None
    saved = store.save_cursor(last_history_id="123", pending_history_id="124")
    assert saved["last_history_id"] == "123"
    assert saved["pending_history_id"] == "124"
    assert calls[0]["url"].endswith("gmail_watch_state?id=eq.primary&select=*&limit=1")
    # The key is necessarily sent in the Authorization header; the adapter's
    # public return values and error classes never include it.
    assert "service-role-secret" not in repr(saved)


def test_pending_cursor_clear_uses_atomic_match(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return _Response(200, [{"id": "primary"}])

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.clear_pending_history_if_matches("history/new") is True
    assert calls[0]["method"] == "PATCH"
    assert "id=eq.primary" in calls[0]["url"]
    assert "pending_history_id=eq.history%2Fnew" in calls[0]["url"]
    assert calls[0]["kwargs"]["json"] == {"pending_history_id": None}


def test_public_projection_rejects_private_mail_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("supabase_email_store.requests.request", lambda *_args, **_kwargs: _Response(201, [{"ok": True}]))
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    with pytest.raises(ValueError, match="private"):
        store.save_public_observation({
            "observation_id": "obs-1",
            "source": "creator",
            "public_safe": True,
            "body": "must never persist",
        })


def test_claim_observation_treats_exact_content_conflict_as_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "supabase_email_store.requests.request",
        lambda *_args, **_kwargs: _Response(409, {"code": "23505"}),
    )
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.claim_observation({
        "gmail_message_id": "gmail-2",
        "observation_id": "obs-2",
        "content_hash": "content-1",
        "parse_status": "parsed",
        "parser_version": "test",
    }) is False


def test_public_projection_keeps_creator_fields_but_strips_transport_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        if method == "GET":
            return _Response(200, [])
        captured.append(kwargs.get("json") or {})
        return _Response(201, [{"observation_id": "jenny:abc"}])

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.save_public_observation({
        "observation_id": "jenny:abc",
        "content_origin": "jenny",
        "episode_key": "jenny:abc",
        "episode_title": "今日市場觀察",
        "public_safe": True,
    }) is True
    payload = captured[0]["payload_json"]
    assert payload["episode_title"] == "今日市場觀察"
    with pytest.raises(ValueError, match="private"):
        store.save_public_observation({
            "observation_id": "jenny:def",
            "content_origin": "jenny",
            "episode_key": "jenny:def",
            "source_message_id": "gmail-private-id",
            "public_safe": True,
        })
    assert "gmail_message_id" not in payload


def test_public_projection_replay_patches_only_richer_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    requests_seen: list[tuple[str, str, dict[str, Any]]] = []
    previous = {
        "observation_id": "fj:abc",
        "content_origin": "financialjuice",
        "public_safe": True,
        "original_headline": "舊標題",
    }

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        requests_seen.append((method, url, kwargs.get("json") or {}))
        if method == "GET":
            return _Response(200, [{"payload_json": previous}])
        return _Response(204, None)

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.save_public_observation({
        "observation_id": "fj:abc",
        "content_origin": "financialjuice",
        "public_safe": True,
        "original_headline": "新標題",
        "chinese_translation": "繁體中文翻譯",
    }) is True
    assert requests_seen[0][0] == "GET"
    assert requests_seen[1][0] == "PATCH"
    assert requests_seen[1][2]["payload_json"]["original_headline"] == "新標題"


def test_public_projection_does_not_replace_rich_semantics_with_sparse_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    previous = {
        "observation_id": "fj:rich",
        "content_origin": "financialjuice",
        "public_safe": True,
        "original_headline": "完整標題",
        "chinese_translation": "完整翻譯",
    }

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append(method)
        if method == "GET":
            return _Response(200, [{"payload_json": previous}])
        return _Response(204, None)

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.save_public_observation({
        "observation_id": "fj:rich",
        "content_origin": "financialjuice",
        "public_safe": True,
        "original_headline": "稀疏",
    }) is False
    assert calls == ["GET"]


def test_public_fact_exists_reads_sanitized_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    def request(method: str, url: str, **kwargs: Any) -> _Response:
        assert method == "GET"
        assert url.endswith("gmail_public_observations?select=payload_json&limit=500")
        return _Response(200, [{"payload_json": {"canonical_fact_key": "fj:fact-1"}}])

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.public_fact_exists("fj:fact-1") is True
    assert store.public_fact_exists("fj:fact-2") is False


def test_public_projection_prefers_cleaner_equal_width_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    requests_seen: list[tuple[str, str, dict[str, Any]]] = []
    previous = {
        "observation_id": "fj:clean",
        "content_origin": "financialjuice",
        "public_safe": True,
        "vendor_translation": "翻譯內容 💡 AI 評論: 舊評論",
        "vendor_analysis": "重要性評分: 8/10 📝 繁體中文翻譯:",
        "vendor_possible_impact": "影響內容 📄 原文內容: 舊原文",
        "vendor_original_headline": "舊原文",
    }

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        requests_seen.append((method, url, kwargs.get("json") or {}))
        if method == "GET":
            return _Response(200, [{"payload_json": previous}])
        return _Response(204, None)

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.save_public_observation({
        "observation_id": "fj:clean",
        "content_origin": "financialjuice",
        "public_safe": True,
        "vendor_original_headline": "Iran says no nuclear activity",
        "vendor_translation": "美伊衝突升級。",
        "vendor_analysis": "市場風險偏好受壓。",
        "vendor_possible_impact": "油價波動可能升高。",
    }) is True
    assert requests_seen[1][0] == "PATCH"
    patched = requests_seen[1][2]["payload_json"]
    assert patched["vendor_translation"] == "美伊衝突升級。"
    assert patched["vendor_analysis"] == "市場風險偏好受壓。"


def test_store_requires_https_and_credentials() -> None:
    with pytest.raises(ValueError, match="not_configured"):
        SupabaseEmailStore("", "")
    with pytest.raises(ValueError, match="https"):
        SupabaseEmailStore("http://example.supabase.co", "key")


def test_cursor_retries_transient_supabase_reads_with_bounded_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def request(method: str, url: str, **_kwargs: Any) -> _Response:
        assert method == "GET"
        calls.append(1)
        return _Response(504 if len(calls) < 3 else 200, [])

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    monkeypatch.setattr("supabase_email_store.random.uniform", lambda _low, _high: 0.0)
    store = SupabaseEmailStore("https://example.supabase.co", "key", sleep_fn=sleeps.append)
    assert store.cursor()["last_history_id"] is None
    assert len(calls) == 3
    assert sleeps == [1.0, 3.0]
    assert store.last_retry_count == 2


def test_cursor_retries_http_500_four_times_then_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def request(method: str, _url: str, **_kwargs: Any) -> _Response:
        assert method == "GET"
        calls.append(1)
        return _Response(500, {"private": "hidden"})

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    monkeypatch.setattr("supabase_email_store.random.uniform", lambda _low, _high: 0.0)
    store = SupabaseEmailStore("https://example.supabase.co", "key", sleep_fn=sleeps.append)
    with pytest.raises(RuntimeError, match="supabase_http_500"):
        store.cursor()
    assert len(calls) == 4
    assert sleeps == [1.0, 3.0, 7.0]
    assert store.last_retry_count == 3
    assert store.last_request_attempts == 4


def test_private_sync_health_uses_atomic_rpc_and_never_returns_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append((method, url))
        assert kwargs["json"]["p_error"] == "supabase_http_500"
        return _Response(200, [{"status": "retry_pending", "consecutive_failure_count": 1}])

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    state = store.record_sync_failure(
        error="supabase_http_500",
        failed_at="2026-09-14T13:30:50+00:00",
        run_id="123",
        run_sha="abc",
        next_retry_at="2026-09-14T13:35:50+00:00",
    )
    assert state["status"] == "retry_pending"
    assert calls[0] == ("POST", "https://example.supabase.co/rest/v1/rpc/record_gmail_sync_failure")
    assert "private" not in repr(state)


def test_cursor_does_not_retry_authentication_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def request(*_args: Any, **_kwargs: Any) -> _Response:
        calls.append(1)
        return _Response(401, {"private": "must not be surfaced"})

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key", sleep_fn=lambda _delay: None)
    with pytest.raises(RuntimeError, match="supabase_http_401"):
        store.cursor()
    assert len(calls) == 1


def test_priority_pending_uses_idempotent_table_fallback_when_rpc_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **_kwargs: Any) -> _Response:
        calls.append((method, url))
        if "/rpc/upsert_financialjuice_priority_pending" in url:
            return _Response(404, {"private": "not exposed"})
        if method == "GET":
            return _Response(200, [])
        return _Response(201, [{"event_ref": "ref-1", "summary_status": "pending"}])

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    result = store.upsert_priority_pending({
        "canonical_fact_key": "fj:fact-1",
        "material_fact_version": "v1",
        "source_published_at": "2026-09-20T01:00:00+00:00",
        "summary_contract_version": "public-summary-v3",
        "public_summary_status": "incomplete",
    })
    assert result["event_ref"] == "ref-1"
    assert calls[0][0] == "POST"
    assert calls[1][0] == "GET"
    assert calls[2][0] == "POST"
