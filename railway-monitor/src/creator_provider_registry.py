# GENERATED FILE: do not edit manually.
# Run scripts/sync_railway_canonical_parser.py to refresh it.
# Canonical source: src/creator_provider_registry.py
# Canonical source SHA256: 4616bcaac4fc5c8a0f399727999db51ecc257b981b2aea4b4b8e0d6a307184e1

"""Canonical, fail-closed registry for optional Creator providers.

Provider identity is configuration, not a collection of duplicated literals in
routers, parsers, health checks, or release code.  The registry contains only
public provider metadata; no mailbox, token, recipient, or private URL belongs
here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_ALLOWED_SOURCE_TYPES = {"editorial"}
_ALLOWED_NOTIFICATION_POLICIES = {"optional_reviewed_only"}
_ALLOWED_MEDIA_POLICIES = {"summary_image_if_reviewed"}


@dataclass(frozen=True)
class CreatorProvider:
    creator_id: str
    display_name: str
    source_type: str
    email_identity_rules: dict[str, tuple[str, ...]]
    gmail_label: str
    parser: str
    consensus_eligible: bool
    notification_policy: str
    media_policy: str
    display_order: int
    morning_required: bool = False
    enabled: bool = True

    @property
    def markers(self) -> tuple[str, ...]:
        return self.email_identity_rules.get("markers", ())

    @property
    def domains(self) -> tuple[str, ...]:
        return self.email_identity_rules.get("domains", ())


def _default_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "creator_providers.json"


def _schema_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    for candidate in (
        root / "schemas" / "creator-providers.schema.json",
        root / "config" / "creator-providers.schema.json",
    ):
        if candidate.is_file():
            return candidate
    return root / "schemas" / "creator-providers.schema.json"


def _validate_document(payload: Any, candidate: Path) -> None:
    """Apply the formal registry contract before semantic normalization."""
    try:
        schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("creator provider registry schema unavailable") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        path = ".".join(str(part) for part in errors[0].path) or "root"
        raise ValueError(f"creator provider registry schema invalid at {path}: {errors[0].message}")


def _as_text(value: Any, field: str, provider: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"creator provider {provider!r} missing {field}")
    return text


def _as_terms(value: Any, field: str, provider: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"creator provider {provider!r} {field} must be a list")
    terms = tuple(dict.fromkeys(str(item).strip().casefold() for item in value if str(item).strip()))
    if field == "markers" and not terms:
        raise ValueError(f"creator provider {provider!r} requires email markers")
    return terms


def load_creator_registry(path: str | Path | None = None) -> tuple[CreatorProvider, ...]:
    """Load and validate the canonical registry; malformed config fails closed."""
    candidate = Path(path).expanduser() if path is not None else _default_path()
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"creator provider registry unavailable: {candidate}") from exc
    _validate_document(payload, candidate)
    entries = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("creator provider registry requires a non-empty providers list")
    providers: list[CreatorProvider] = []
    seen: set[str] = set()
    orders: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("creator provider entry must be an object")
        creator_id = _as_text(entry.get("creator_id"), "creator_id", "unknown").casefold()
        if creator_id in seen:
            raise ValueError(f"duplicate creator provider: {creator_id}")
        seen.add(creator_id)
        source_type = _as_text(entry.get("source_type"), "source_type", creator_id).casefold()
        if source_type not in _ALLOWED_SOURCE_TYPES:
            raise ValueError(f"unsupported creator source type: {creator_id}")
        rules = entry.get("email_identity_rules")
        if not isinstance(rules, dict):
            raise ValueError(f"creator provider {creator_id!r} requires email_identity_rules")
        order = entry.get("display_order")
        if not isinstance(order, int) or order <= 0 or order in orders:
            raise ValueError(f"invalid or duplicate display_order: {creator_id}")
        orders.add(order)
        notification_policy = _as_text(entry.get("notification_policy"), "notification_policy", creator_id)
        media_policy = _as_text(entry.get("media_policy"), "media_policy", creator_id)
        if notification_policy not in _ALLOWED_NOTIFICATION_POLICIES:
            raise ValueError(f"unsupported notification policy: {creator_id}")
        if media_policy not in _ALLOWED_MEDIA_POLICIES:
            raise ValueError(f"unsupported media policy: {creator_id}")
        providers.append(CreatorProvider(
            creator_id=creator_id,
            display_name=_as_text(entry.get("display_name"), "display_name", creator_id),
            source_type=source_type,
            email_identity_rules={
                "markers": _as_terms(rules.get("markers"), "markers", creator_id),
                "domains": _as_terms(rules.get("domains", []), "domains", creator_id),
            },
            gmail_label=_as_text(entry.get("gmail_label"), "gmail_label", creator_id),
            parser=_as_text(entry.get("parser"), "parser", creator_id),
            consensus_eligible=bool(entry.get("consensus_eligible")),
            notification_policy=notification_policy,
            media_policy=media_policy,
            display_order=order,
            morning_required=bool(entry.get("morning_required", False)),
            enabled=bool(entry.get("enabled", True)),
        ))
    return tuple(sorted(providers, key=lambda item: item.display_order))


def creator_providers(*, enabled_only: bool = False) -> tuple[CreatorProvider, ...]:
    providers = load_creator_registry()
    return tuple(item for item in providers if item.enabled) if enabled_only else providers


def creator_ids(*, enabled_only: bool = False) -> tuple[str, ...]:
    return tuple(item.creator_id for item in creator_providers(enabled_only=enabled_only))


def get_creator_provider(creator_id: str) -> CreatorProvider | None:
    normalized = str(creator_id or "").strip().casefold()
    return next((item for item in creator_providers() if item.creator_id == normalized), None)


def is_known_creator(creator_id: str, *, enabled_only: bool = False) -> bool:
    normalized = str(creator_id or "").strip().casefold()
    return normalized in creator_ids(enabled_only=enabled_only)


def editorial_creator_ids(*, enabled_only: bool = False) -> tuple[str, ...]:
    return tuple(item.creator_id for item in creator_providers(enabled_only=enabled_only) if item.source_type == "editorial")


CREATOR_PROVIDERS = creator_ids()

__all__ = [
    "CREATOR_PROVIDERS", "CreatorProvider", "creator_ids", "creator_providers",
    "editorial_creator_ids", "get_creator_provider", "is_known_creator",
    "load_creator_registry",
]
