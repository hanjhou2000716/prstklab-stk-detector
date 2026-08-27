from __future__ import annotations

import json

import pytest

from prstk_app.db.repository import InMemoryRepository, RepositoryError, SupabaseRepository


def test_in_memory_job_lifecycle_is_idempotent() -> None:
    repo = InMemoryRepository()
    job = repo.create_job(market="tw", requested_by="telegram:1")
    assert job["status"] == "queued"
    assert repo.mark_job_running(job["id"])["status"] == "running"
    assert repo.mark_job_completed(job["id"])["status"] == "completed"
    assert repo.mark_job_failed(job["id"], "late failure")["status"] == "completed"


def test_in_memory_rejects_unknown_market() -> None:
    with pytest.raises(ValueError, match="market"):
        InMemoryRepository().create_job(market="jp")


class _Response:
    status_code = 201
    content = b"[{\"id\": \"job-1\"}]"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return json.loads(self.content)


def test_supabase_repository_uses_backend_auth_and_rest_contract() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> _Response:
        calls.append({"method": method, "url": url, **kwargs})
        return _Response()

    repo = SupabaseRepository(
        url="https://example.supabase.co",
        service_role_key="server-only-key",
        requester=requester,
    )
    result = repo.create_job(market="us")
    assert result["id"] == "job-1"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://example.supabase.co/rest/v1/report_jobs"
    headers = calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer server-only-key"


def test_supabase_repository_rejects_insecure_or_missing_configuration() -> None:
    with pytest.raises(RepositoryError, match="configured"):
        SupabaseRepository(url="", service_role_key="")
    with pytest.raises(RepositoryError, match="HTTPS"):
        SupabaseRepository(url="http://example.test", service_role_key="key")
