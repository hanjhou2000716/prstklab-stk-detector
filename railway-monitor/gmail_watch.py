"""Gmail Watch configuration, renewal and privacy-safe health decisions.

The Gmail ``users.watch`` lease expires (normally after about a week).  This
module keeps renewal deterministic and injectable so the Railway process can
renew it at startup without putting OAuth or Gmail response data in logs.
"""

from __future__ import annotations

import json
import hashlib
import os
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
WATCH_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/watch"


@dataclass(frozen=True)
class GmailWatchConfig:
    topic_name: str
    label_ids: tuple[str, ...]
    oauth_state: str
    audience: str
    service_account: str
    require_jwt_verification: bool = False
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    refresh_token: str = ""
    renewal_margin_hours: int = 6
    retry_cooldown_minutes: int = 60
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GmailWatchConfig:
        source = os.environ if env is None else env
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
            renewal_margin_hours=_positive_int(source.get("GMAIL_WATCH_RENEWAL_MARGIN_HOURS", "6"), 6),
            retry_cooldown_minutes=_positive_int(source.get("GMAIL_WATCH_RETRY_COOLDOWN_MINUTES", "60"), 60),
            timeout_seconds=_positive_float(source.get("GMAIL_WATCH_TIMEOUT_SECONDS", "15"), 15.0),
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


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _default_transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=dict(headers), method="POST")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed Google HTTPS endpoints
        return int(response.status), response.read(128 * 1024)


def _safe_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GmailWatchError("invalid_json_response") from error
    if not isinstance(value, dict):
        raise GmailWatchError("invalid_json_response")
    return value


class GmailWatchError(RuntimeError):
    """Bounded, non-sensitive watch failure."""


class GmailWatchManager:
    """Create or renew a Gmail watch lease without failing the worker startup."""

    def __init__(
        self,
        config: GmailWatchConfig,
        store: Any,
        *,
        transport: Callable[[str, bytes, Mapping[str, str], float], tuple[int, bytes]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.transport = transport or _default_transport
        self.now = now or (lambda: datetime.now(UTC))

    def _post(self, url: str, body: bytes, headers: Mapping[str, str]) -> dict[str, Any]:
        try:
            status, raw = self.transport(
                url,
                body,
                dict(headers),
                self.config.timeout_seconds,
            )
        except HTTPError as error:
            raise GmailWatchError(f"http_{int(error.code)}") from None
        except (URLError, TimeoutError, OSError) as error:
            raise GmailWatchError(type(error).__name__.lower()) from None
        if status < 200 or status >= 300:
            raise GmailWatchError(f"http_{status}")
        return _safe_json(raw)

    def _post_json(self, url: str, payload: dict[str, Any], headers: Mapping[str, str]) -> dict[str, Any]:
        return self._post(
            url,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            {"Content-Type": "application/json", **dict(headers)},
        )

    def _access_token(self) -> str:
        result = self._post(
            TOKEN_ENDPOINT,
            urlencode({
                "client_id": self.config.oauth_client_id,
                "client_secret": self.config.oauth_client_secret,
                "refresh_token": self.config.refresh_token,
                "grant_type": "refresh_token",
            }).encode("ascii"),
            {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        token = str(result.get("access_token") or "").strip()
        if not token:
            raise GmailWatchError("oauth_access_token_missing")
        return token

    def ensure_watch(self) -> dict[str, Any]:
        cursor = self.store.cursor()
        if self.config.missing:
            return {"status": "configuration_missing", "renewed": False, "missing": list(self.config.missing)}
        if self.config.oauth_missing:
            return {"status": "configuration_missing", "renewed": False, "missing": list(self.config.oauth_missing)}
        expiration = cursor.get("watch_expiration")
        if not renewal_due(
            str(expiration) if expiration else None,
            now=self.now(),
            margin_hours=self.config.renewal_margin_hours,
        ):
            return {"status": "healthy", "renewed": False, "watch_expiration": expiration}
        try:
            token = self._access_token()
            request = self.config.watch_request()
            response = self._post_json(
                WATCH_ENDPOINT,
                {key: value for key, value in request.items() if key not in {"status"}},
                {"Authorization": f"Bearer {token}"},
            )
            expiration_ms = int(str(response.get("expiration") or "0"))
            history_id = str(response.get("historyId") or "").strip()
            if expiration_ms <= 0 or not history_id:
                raise GmailWatchError("watch_response_missing_fields")
            expires_at = datetime.fromtimestamp(expiration_ms / 1000, UTC).isoformat()
            renewed_at = self.now().astimezone(UTC).isoformat()
            values: dict[str, Any] = {
                "watch_expiration": expires_at,
                "watch_last_renewed_at": renewed_at,
                "watch_error": None,
                "watch_error_at": None,
            }
            if history_id:
                values["last_history_id"] = history_id
            self.store.save_cursor(**values)
            return {"status": "healthy", "renewed": True, "watch_expiration": expires_at}
        except GmailWatchError as error:
            self.store.save_cursor(watch_error=str(error), watch_error_at=self.now().astimezone(UTC).isoformat())
            return {"status": "failed", "renewed": False, "error": str(error)}
        except (TypeError, ValueError, OverflowError) as error:
            self.store.save_cursor(
                watch_error=type(error).__name__,
                watch_error_at=self.now().astimezone(UTC).isoformat(),
            )
            return {"status": "failed", "renewed": False, "error": type(error).__name__}


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
            except (TypeError, ValueError, OverflowError):
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
        # Counts and timestamps only; Gmail history/message IDs stay private.
        "queue_pending_count": store_count("queue_pending_count") or count("queue_pending_count", "pending_count"),
        "dead_letter_count": store_count("dead_letter_count") or count("dead_letter_count", "dlq_count"),
        "last_ingress_at": timestamp("last_notification_at"),
        "last_sync_at": timestamp("last_sync_at"),
        "history_cursor_present": bool(str(cursor.get("last_history_id") or "").strip()),
        "history_cursor_hash": (
            hashlib.sha256(str(cursor["last_history_id"]).encode("utf-8")).hexdigest()[:16]
            if str(cursor.get("last_history_id") or "").strip() else None
        ),
    }
    result: dict[str, Any] = {
        "status": state,
        "missing": list(config.missing),
        "watch_active": watch_active,
        "watch_expiration": expiration,
        "observability": observability,
    }
    for key in ("watch_last_renewed_at", "watch_error", "watch_error_at"):
        value = cursor.get(key)
        if value:
            result[key] = str(value) if key != "watch_error" else str(value)[:80]
    if cursor.get("watch_error") and state == "stale":
        result["status"] = "failed"
        result["observability"]["state"] = "failed"
    return result


__all__ = ["GmailWatchConfig", "GmailWatchError", "GmailWatchManager", "health", "renewal_due"]
