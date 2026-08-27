from __future__ import annotations

from jobs.process_report_job import process_report_job
from prstk_app.db.repository import InMemoryRepository, RepositoryError


def test_report_worker_completes_and_persists_report() -> None:
    repo = InMemoryRepository()
    job = repo.create_job(market="tw", intro="hello")
    result = process_report_job(job["id"], repository=repo, builder=lambda **kwargs: "report-body")
    assert result == {"job_id": job["id"], "status": "completed", "report": "report-body"}
    assert repo.get_job(job["id"])["status"] == "completed"
    assert repo.get_report(job["id"])["content"] == "report-body"
    assert repo.system_status["report_engine"]["status"] == "ok"


def test_report_worker_does_not_recompute_terminal_job() -> None:
    repo = InMemoryRepository()
    job = repo.create_job(market="us")
    repo.mark_job_running(job["id"])
    repo.save_report(job_id=job["id"], market="us", content="existing")
    repo.mark_job_completed(job["id"])
    result = process_report_job(job["id"], repository=repo, builder=lambda **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert result["status"] == "completed"


def test_report_worker_closes_failed_job() -> None:
    repo = InMemoryRepository()
    job = repo.create_job(market="us")
    result = process_report_job(job["id"], repository=repo, builder=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("upstream timeout")))
    assert result["status"] == "failed"
    assert "upstream timeout" in result["error"]
    assert repo.get_job(job["id"])["status"] == "failed"
    assert repo.system_status["report_engine"]["status"] == "error"


def test_report_worker_rejects_unknown_job() -> None:
    try:
        process_report_job("missing", repository=InMemoryRepository(), builder=lambda **kwargs: "unused")
    except RepositoryError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("unknown jobs must fail closed")
