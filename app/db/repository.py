"""Small, idempotent repository for the Supabase report-job contract.

Heavy market computation never belongs here.  The repository is deliberately
transport-injected so the same state transitions can be tested offline and
used by a Cloudflare Worker without spreading raw Supabase requests through
the application.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import requests


class RepositoryError(RuntimeError):
    """A safe, user-facing persistence failure (never contains credentials)."""


Request = Callable[..., requests.Response]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("message") if isinstance(payload, Mapping) else None
    except (ValueError, requests.RequestException):
        message = None
    return str(message or f"Supabase returned HTTP {response.status_code}")[:240]


class SupabaseRepository:
    """REST repository using only the service-role secret on the backend.

    ``requester`` is injectable for tests.  No key, URL query, or raw response
    body is ever included in raised errors.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        service_role_key: str | None = None,
        requester: Request = requests.request,
        timeout: float = 10.0,
    ) -> None:
        self.url = str(url or os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        self.key = str(service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        self.requester = requester
        self.timeout = timeout
        if not self.url or not self.key:
            raise RepositoryError("Supabase repository is not configured")
        if not self.url.startswith("https://"):
            raise RepositoryError("SUPABASE_URL must use HTTPS")

    def _request(self, method: str, table: str, *, params: Mapping[str, str] | None = None, payload: Any = None, prefer: str | None = None) -> list[dict[str, Any]]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = self.requester(
                method,
                f"{self.url}/rest/v1/{table}",
                headers=headers,
                params=dict(params or {}),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            if not response.content:
                return []
            decoded = response.json()
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                raise RepositoryError(_safe_error(exc.response)) from exc
            raise RepositoryError("Supabase request failed") from exc
        if isinstance(decoded, list):
            return [dict(item) for item in decoded if isinstance(item, Mapping)]
        if isinstance(decoded, Mapping):
            return [dict(decoded)]
        return []

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "report_jobs", params={"id": f"eq.{job_id}", "select": "*"})
        return rows[0] if rows else None

    def create_job(self, *, market: str, intro: str = "", outro: str = "", requested_by: str = "") -> dict[str, Any]:
        if market not in {"tw", "us"}:
            raise ValueError("market must be tw or us")
        job = {
            "id": str(uuid.uuid4()),
            "market": market,
            "intro": intro[:2000],
            "outro": outro[:2000],
            "status": "queued",
            "requested_by": requested_by[:128],
            "created_at": _utc_now(),
        }
        rows = self._request("POST", "report_jobs", payload=job, prefer="return=representation,resolution=ignore-duplicates")
        return rows[0] if rows else job

    def mark_job_running(self, job_id: str) -> dict[str, Any] | None:
        current = self.get_job(job_id)
        if current is None or current.get("status") in {"completed", "failed"}:
            return current
        rows = self._request(
            "PATCH", "report_jobs", params={"id": f"eq.{job_id}", "status": "eq.queued"},
            payload={"status": "running", "started_at": _utc_now(), "error": None},
            prefer="return=representation",
        )
        return rows[0] if rows else self.get_job(job_id)

    def mark_job_completed(self, job_id: str) -> dict[str, Any] | None:
        current = self.get_job(job_id)
        if current is None or current.get("status") == "completed":
            return current
        if current.get("status") == "failed":
            return current
        rows = self._request(
            "PATCH", "report_jobs", params={"id": f"eq.{job_id}", "status": "eq.running"},
            payload={"status": "completed", "completed_at": _utc_now(), "error": None},
            prefer="return=representation",
        )
        return rows[0] if rows else self.get_job(job_id)

    def mark_job_failed(self, job_id: str, error: str) -> dict[str, Any] | None:
        current = self.get_job(job_id)
        if current is None or current.get("status") == "completed":
            return current
        rows = self._request(
            "PATCH", "report_jobs", params={"id": f"eq.{job_id}", "status": "in.(queued,running)"},
            payload={"status": "failed", "completed_at": _utc_now(), "error": str(error)[:500]},
            prefer="return=representation",
        )
        return rows[0] if rows else self.get_job(job_id)

    def save_report(self, *, job_id: str, market: str, content: str) -> dict[str, Any]:
        payload = {"id": str(uuid.uuid4()), "job_id": job_id, "market": market, "content": content, "created_at": _utc_now()}
        rows = self._request("POST", "reports", payload=payload, prefer="return=representation")
        return rows[0] if rows else payload

    def get_report(self, job_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "reports", params={"job_id": f"eq.{job_id}", "select": "*", "order": "created_at.desc", "limit": "1"})
        return rows[0] if rows else None

    def update_system_status(self, *, component: str, status: str, error: str | None = None) -> dict[str, Any]:
        payload = {"component": component, "status": status, "last_error": error[:500] if error else None, "updated_at": _utc_now()}
        if status == "ok":
            payload["last_success_at"] = payload["updated_at"]
        rows = self._request("POST", "system_status", payload=payload, prefer="return=representation,resolution=merge-duplicates")
        return rows[0] if rows else payload


class InMemoryRepository:
    """Deterministic repository used by offline contract and worker tests."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.system_status: dict[str, dict[str, Any]] = {}

    def create_job(self, *, market: str, intro: str = "", outro: str = "", requested_by: str = "") -> dict[str, Any]:
        if market not in {"tw", "us"}:
            raise ValueError("market must be tw or us")
        job = {"id": str(uuid.uuid4()), "market": market, "intro": intro[:2000], "outro": outro[:2000], "status": "queued", "requested_by": requested_by[:128], "created_at": _utc_now()}
        self.jobs[job["id"]] = job
        return dict(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        return dict(job) if job else None

    def mark_job_running(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if job and job["status"] not in {"completed", "failed"}:
            job.update(status="running", started_at=_utc_now(), error=None)
        return self.get_job(job_id)

    def mark_job_completed(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if job and job["status"] == "running":
            job.update(status="completed", completed_at=_utc_now(), error=None)
        return self.get_job(job_id)

    def mark_job_failed(self, job_id: str, error: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if job and job["status"] in {"queued", "running"}:
            job.update(status="failed", completed_at=_utc_now(), error=str(error)[:500])
        return self.get_job(job_id)

    def save_report(self, *, job_id: str, market: str, content: str) -> dict[str, Any]:
        report = {"id": str(uuid.uuid4()), "job_id": job_id, "market": market, "content": content, "created_at": _utc_now()}
        self.reports[job_id] = report
        return dict(report)

    def get_report(self, job_id: str) -> dict[str, Any] | None:
        report = self.reports.get(job_id)
        return dict(report) if report else None

    def update_system_status(self, *, component: str, status: str, error: str | None = None) -> dict[str, Any]:
        row = {"component": component, "status": status, "last_error": error, "updated_at": _utc_now()}
        if status == "ok":
            row["last_success_at"] = row["updated_at"]
        self.system_status[component] = row
        return dict(row)
