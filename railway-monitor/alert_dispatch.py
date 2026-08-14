"""Transport-neutral orchestration for a signed Railway alert dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

BuildPayload = Callable[[Any, str], dict[str, Any]]
SignPayload = Callable[[dict[str, Any], Any, str], dict[str, Any]]
TraceId = Callable[[Any], str]
Dispatch = Callable[..., Awaitable[None]]


async def dispatch_alert(
    alert: Any,
    *,
    token: str,
    repository: str,
    shared_secret: str,
    trace_id: TraceId,
    build_payload: BuildPayload,
    sign_payload: SignPayload,
    dispatch: Dispatch,
) -> None:
    """Build once, sign once, and send one stable alert payload."""
    current_trace_id = trace_id(alert)
    payload = sign_payload(
        build_payload(alert, current_trace_id),
        alert,
        shared_secret,
    )
    await dispatch(
        payload,
        token=token,
        repository=repository,
        trace_id=current_trace_id,
    )
