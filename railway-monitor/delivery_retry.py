"""Durable delivery-outbox retry orchestration for the Railway monitor.

The retry loop is intentionally transport-neutral.  ``app.py`` supplies the
existing repository-dispatch callback and health projection, while this module
owns bounded batch selection, failure marking and success accounting.  This
keeps persistence and transport seams testable without changing the public
``SeenStore`` API.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

Dispatch = Callable[..., Awaitable[None]]
HealthUpdate = Callable[..., Any]


def _batch_size() -> int:
    """Return the configured retry batch while preserving a safe bound."""
    return max(1, min(100, int(os.environ.get("OUTBOX_RETRY_BATCH", "20"))))


async def retry_due_outbox(
    store: Any,
    *,
    token: str,
    repository: str,
    shared_secret: str,
    dispatch: Dispatch,
    update_health: HealthUpdate,
) -> int:
    """Replay durable dispatches that survived a transient failure.

    ``shared_secret`` remains part of the boundary for compatibility with the
    caller's release/dispatch contract.  The outbox already stores a signed
    payload, so retries must reuse it byte-for-byte rather than re-signing.
    """
    del shared_secret
    retried = 0
    for item in store.due_outbox(_batch_size()):
        trace_id = item["trace_id"]
        try:
            await dispatch(
                item["dispatch_payload"],
                token=token,
                repository=repository,
                trace_id=trace_id,
            )
        except Exception as error:
            store.mark_outbox(trace_id, "failed", type(error).__name__)
            logging.exception("outbox retry failed trace_id=%s; backoff scheduled", trace_id)
            continue
        store.mark_outbox(trace_id, "sent")
        retried += 1
        logging.info("outbox retry delivered trace_id=%s", trace_id)
    if retried:
        update_health("delivery", **store.delivery_diagnostics())
    return retried
