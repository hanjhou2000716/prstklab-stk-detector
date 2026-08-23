"""Gmail Watch configuration and renewal decisions.

Network calls stay outside this module.  It produces a narrow, auditable
``users.watch`` request and reports ``configuration_missing`` until OAuth,
Pub/Sub audience and a dedicated label are configured.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class GmailWatchConfig:
    topic_name: str
    label_ids: tuple[str, ...]
    oauth_state: str
    audience: str
    service_account: str
    require_jwt_verification: bool = False
    # OAuth values stay in Railway's private environment. They are optional
    # for the authenticated push contract and required only by renewal.
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    refresh_token: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GmailWatchConfig:
        source = env or os.environ
        labels = tuple(value.strip() for value in source.get("GMAIL_WATCH_LABEL_IDS", "").split(",") if value.strip())
        return cls(
            topic_name=source.get("GMAIL_WATCH_TOPIC", "").strip(),
            label_ids=labels,
            oauth_state=source.get("GMAIL_OAUTH_STATE", "").strip(),
            audience=source.get("GMAIL_PUBSUB_AUDIENCE", "").strip(),
            service_account=source.get("GMAIL_PUBSUB_SERVICE_ACCOUNT", "").strip(),
            require_jwt_verification=source.get("GMAIL_PUBSUB_REQUIRE_JWT", "false").strip().casefold() == "true",
            oauth_client_id=source.get("GMAIL_OAUTH_CLIENT_ID", "").strip(),
            oauth_client_secret=source.get("GMAIL_OAUTH_CLIENT_SECRET", "").strip(),
            refresh_token=source.get("GMAIL_REFRESH_TOKEN", "").strip(),
        )

    @property
    def missing(self) -> tuple[str, ...]:
        values = {
            "GMAIL_WATCH_TOPIC": self.topic_name,
            "GMAIL_WATCH_LABEL_IDS": ",".join(self.label_ids),
            "GMAIL_OAUTH_STATE": self.oauth_state,
            "GMAIL_PUBSUB_AUDIENCE": self.audience,
            "GMAIL_PUBSUB_SERVICE_ACCOUNT": self.service_account,
        }
        return tuple(key for key, value in values.items() if not value)

    @property
    def status(self) -> str:
        return "configuration_missing" if self.missing else "configured"

    @property
    def oauth_missing(self) -> tuple[str, ...]:
        """Return names missing for automatic ``users.watch`` renewal."""
        values = {
            "GMAIL_OAUTH_CLIENT_ID": self.oauth_client_id,
            "GMAIL_OAUTH_CLIENT_SECRET": self.oauth_client_secret,
            "GMAIL_REFRESH_TOKEN": self.refresh_token,
        }
        return tuple(key for key, value in values.items() if not value)

    def watch_request(self) -> dict[str, Any]:
        if self.missing:
            return {"status": "configuration_missing", "missing": list(self.missing)}
        return {
            "status": "ready",
            "topicName": self.topic_name,
            "labelIds": list(self.label_ids),
            "labelFilterAction": "include",
        }


def renewal_due(expiration: str | None, *, now: datetime | None = None, margin_hours: int = 6) -> bool:
    if not expiration:
        return True
    try:
        parsed = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
    except ValueError:
        return True
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return parsed.astimezone(UTC) <= current + timedelta(hours=max(1, margin_hours))


def health(
    config: GmailWatchConfig,
    cursor: Mapping[str, Any],
    *,
    store_health: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a privacy-safe watch status and operational observability.

    Cursor identifiers (history/message IDs) are deliberately not copied into
    the public health payload.  Timestamps and bounded counters are sufficient
    for the Mini App/source-health view and keep Gmail content private.
    """
    state = "healthy"
    if config.missing:
        state = "configuration_missing"
        watch_active = False
    else:
        expiration = cursor.get("watch_expiration")
        watch_active = not renewal_due(str(expiration) if expiration else None)
        if not watch_active:
            state = "stale"

    def timestamp(*keys: str) -> str | None:
        for key in keys:
            value = cursor.get(key)
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
            return parsed.astimezone(UTC).isoformat()
        return None

    def count(*keys: str) -> int:
        for key in keys:
            if key not in cursor:
                continue
            try:
                value = int(cursor.get(key) or 0)
            except (TypeError, ValueError):
                continue
            return max(0, value)
        return 0

    expiration = cursor.get("watch_expiration")
    store = store_health if isinstance(store_health, Mapping) else {}
    def store_count(key: str, fallback: str | None = None) -> int:
        value = store.get(key)
        if value is None and fallback:
            value = store.get(fallback)
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError, OverflowError):
            return 0
        return max(0, parsed)

    observability = {
        "observations": count("observation_count", "observations"),
        "last_received_at": timestamp("last_notification_at", "received_at"),
        "last_parsed_at": timestamp("last_parsed_at", "last_parse_at", "last_sync_at"),
        "parser_error_count": count("parser_error_count", "dlq_count"),
        "last_delivery_at": timestamp("last_delivery_at", "last_receipt_at"),
        "state": state,
        # These are counts/timestamps only.  History/message IDs and OAuth
        # transport identifiers never cross this boundary.
        "queue_pending_count": store_count("queue_pending_count") or count("queue_pending_count", "pending_count"),
        "dead_letter_count": store_count("dead_letter_count", "dlq_count") or count("dead_letter_count", "dlq_count"),
        "last_ingress_at": timestamp("last_notification_at"),
        "last_sync_at": timestamp("last_sync_at"),
        "history_cursor_present": bool(str(cursor.get("last_history_id") or "").strip()),
        "history_cursor_hash": (
            hashlib.sha256(str(cursor["last_history_id"]).encode("utf-8")).hexdigest()[:16]
            if str(cursor.get("last_history_id") or "").strip() else None
        ),
    }
    return {
        "status": state,
        "missing": list(config.missing),
        "watch_active": watch_active,
        "watch_expiration": expiration,
        "observability": observability,
    }


__all__ = ["GmailWatchConfig", "health", "renewal_due"]
