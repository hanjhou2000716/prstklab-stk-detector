from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "alert_dispatch.py"
SPEC = importlib.util.spec_from_file_location("railway_alert_dispatch_test", MODULE)
assert SPEC and SPEC.loader
dispatch_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dispatch_module)


def test_dispatch_alert_builds_signs_and_sends_once():
    calls = []

    def trace_id(alert):
        return f"trace-{alert['id']}"

    def build_payload(alert, trace):
        calls.append(("build", alert, trace))
        return {"client_payload": {"trace_id": trace}}

    def sign_payload(payload, alert, secret):
        calls.append(("sign", payload, alert, secret))
        return {**payload, "signed": True}

    async def dispatch(payload, *, token, repository, trace_id):
        calls.append(("dispatch", payload, token, repository, trace_id))

    asyncio.run(
        dispatch_module.dispatch_alert(
            {"id": "a-1"},
            token="token",
            repository="owner/repo",
            shared_secret="secret",
            trace_id=trace_id,
            build_payload=build_payload,
            sign_payload=sign_payload,
            dispatch=dispatch,
        )
    )

    assert calls == [
        ("build", {"id": "a-1"}, "trace-a-1"),
        ("sign", {"client_payload": {"trace_id": "trace-a-1"}}, {"id": "a-1"}, "secret"),
        ("dispatch", {"client_payload": {"trace_id": "trace-a-1"}, "signed": True}, "token", "owner/repo", "trace-a-1"),
    ]
