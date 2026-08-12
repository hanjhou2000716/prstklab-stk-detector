"""Fail-closed validation for private creator media attachments.

Creator emails may contain screenshots or audio references.  The public
release only receives a content hash and an explicit availability state; raw
bytes, local paths and untrusted URLs never cross this boundary.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

MAX_MEDIA_BYTES = 8 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "audio/mpeg", "audio/mp4"}
MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
    "audio/mpeg": (b"ID3", b"\xff\xfb"),
    "audio/mp4": (b"\x00\x00\x00",),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_name(value: Any) -> bool:
    name = _text(value)
    if not name or name in {".", ".."}:
        return False
    if "\\" in name or "/" in name:
        return False
    return PurePosixPath(name).name == name and PureWindowsPath(name).name == name


def _mime(value: Any, name: str) -> str:
    candidate = _text(value).lower()
    if candidate in ALLOWED_MIME:
        return candidate
    guessed, _ = mimetypes.guess_type(name)
    return guessed.lower() if guessed else ""


def validate_creator_media(record: dict[str, Any]) -> dict[str, Any]:
    """Validate one private attachment without returning its bytes or path."""
    data = record.get("data", b"")
    if not isinstance(data, (bytes, bytearray)):
        data = b""
    name = _text(record.get("filename"))
    mime = _mime(record.get("mime_type"), name)
    errors: list[str] = []
    if not _safe_name(name):
        errors.append("unsafe_filename")
    if mime not in ALLOWED_MIME:
        errors.append("unsupported_mime")
    if len(data) == 0:
        errors.append("empty_payload")
    if len(data) > MAX_MEDIA_BYTES:
        errors.append("payload_too_large")
    signatures = MAGIC.get(mime, ())
    if signatures and not any(bytes(data).startswith(signature) for signature in signatures):
        errors.append("magic_mismatch")
    digest = hashlib.sha256(bytes(data)).hexdigest() if data else None
    return {
        "media_id": _text(record.get("media_id")) or (f"media-{digest[:16]}" if digest else ""),
        "filename": name if not errors else "",
        "mime_type": mime,
        "byte_size": len(data),
        "sha256": digest,
        "storage_scope": "private" if not errors else "rejected",
        "availability": "private_ready" if not errors else "unavailable",
        "validation_errors": errors,
        "public_safe": True,
    }


def creator_media_summary(record: dict[str, Any]) -> dict[str, Any]:
    """Return the only media fields allowed in a public creator insight."""
    errors = list(record.get("validation_errors") or [])
    return {
        "media_id": _text(record.get("media_id")),
        "mime_type": _text(record.get("mime_type")),
        "byte_size": int(record.get("byte_size") or 0),
        "sha256": _text(record.get("sha256")),
        "availability": _text(record.get("availability")) or "unavailable",
        "storage_scope": "private",
        "validation_errors": errors,
        "public_safe": True,
    }


__all__ = ["creator_media_summary", "validate_creator_media"]
