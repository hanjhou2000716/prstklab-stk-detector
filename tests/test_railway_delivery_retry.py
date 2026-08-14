from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "delivery_retry.py"
SPEC = importlib.util.spec_from_file_location("railway_delivery_retry_test", MODULE)
assert SPEC and SPEC.loader
delivery_retry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery_retry)


class FakeStore:
    def __init__(self, items):
        self.items = list(items)
        self.marked = []
        self.health_calls = 0

    def due_outbox(self, limit):
        assert limit == 20
        return self.items

    def mark_outbox(self, trace_id, status, error=None):
        self.marked.append((trace_id, status, error))

    def delivery_diagnostics(self):
        self.health_calls += 1
        return {"status": "sent", "last_trace_id": "trace-1"}


def test_retry_reuses_persisted_payload_and_updates_health(monkeypatch):
    store = FakeStore([{"trace_id": "trace-1", "dispatch_payload": {"signed": True}}])
    calls = []
    health = []

    async def dispatch(payload, *, token, repository, trace_id):
        calls.append((payload, token, repository, trace_id))

    result = asyncio.run(
        delivery_retry.retry_due_outbox(
            store,
            token="token",
            repository="owner/repo",
            shared_secret="secret",
            dispatch=dispatch,
            update_health=lambda category, **fields: health.append((category, fields)),
        )
    )

    assert result == 1
    assert calls == [({"signed": True}, "token", "owner/repo", "trace-1")]
    assert store.marked == [("trace-1", "sent", None)]
    assert health == [("delivery", {"status": "sent", "last_trace_id": "trace-1"})]


def test_retry_marks_failure_and_continues(monkeypatch):
    store = FakeStore([
        {"trace_id": "trace-fail", "dispatch_payload": {"id": 1}},
        {"trace_id": "trace-ok", "dispatch_payload": {"id": 2}},
    ])
    calls = []

    async def dispatch(payload, *, token, repository, trace_id):
        calls.append(trace_id)
        if trace_id == "trace-fail":
            raise TimeoutError("temporary")

    result = asyncio.run(
        delivery_retry.retry_due_outbox(
            store,
            token="token",
            repository="owner/repo",
            shared_secret="secret",
            dispatch=dispatch,
            update_health=lambda *_args, **_kwargs: None,
        )
    )

    assert result == 1
    assert calls == ["trace-fail", "trace-ok"]
    assert store.marked == [
        ("trace-fail", "failed", "TimeoutError"),
        ("trace-ok", "sent", None),
    ]
