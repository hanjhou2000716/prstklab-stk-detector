"""Typed, secret-safe configuration contract for the Creator gateway."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CreatorRuntimeConfig:
    gmail_oauth_client_id: str = ""
    gmail_oauth_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_watch_label_ids: tuple[str, ...] = ()
    google_cloud_project: str = ""
    pubsub_audience: str = ""
    pubsub_expected_service_account: str = ""
    creator_media_root: str = ""
    creator_dispatch_shared_secret: str = ""

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> CreatorRuntimeConfig:
        values = source or os.environ
        labels = tuple(
            part.strip() for part in values.get("GMAIL_WATCH_LABEL_IDS", "").replace("\n", ",").split(",")
            if part.strip()
        )
        return cls(
            gmail_oauth_client_id=values.get("GMAIL_OAUTH_CLIENT_ID", "").strip(),
            gmail_oauth_client_secret=values.get("GMAIL_OAUTH_CLIENT_SECRET", "").strip(),
            gmail_refresh_token=values.get("GMAIL_REFRESH_TOKEN", "").strip(),
            gmail_watch_label_ids=labels,
            google_cloud_project=values.get("GOOGLE_CLOUD_PROJECT", "").strip(),
            pubsub_audience=values.get("PUBSUB_AUDIENCE", "").strip(),
            pubsub_expected_service_account=values.get("PUBSUB_EXPECTED_SERVICE_ACCOUNT", "").strip(),
            creator_media_root=values.get("CREATOR_MEDIA_ROOT", "").strip(),
            creator_dispatch_shared_secret=values.get("CREATOR_DISPATCH_SHARED_SECRET", "").strip(),
        )

    def missing(self, *, require_oauth: bool = False, require_dispatch: bool = False) -> list[str]:
        required = {
            "GMAIL_WATCH_LABEL_IDS": bool(self.gmail_watch_label_ids),
            "GOOGLE_CLOUD_PROJECT": bool(self.google_cloud_project),
            "PUBSUB_AUDIENCE": bool(self.pubsub_audience),
            "PUBSUB_EXPECTED_SERVICE_ACCOUNT": bool(self.pubsub_expected_service_account),
            "CREATOR_MEDIA_ROOT": bool(self.creator_media_root),
        }
        if require_oauth:
            required.update({
                "GMAIL_OAUTH_CLIENT_ID": bool(self.gmail_oauth_client_id),
                "GMAIL_OAUTH_CLIENT_SECRET": bool(self.gmail_oauth_client_secret),
                "GMAIL_REFRESH_TOKEN": bool(self.gmail_refresh_token),
            })
        if require_dispatch:
            required["CREATOR_DISPATCH_SHARED_SECRET"] = bool(self.creator_dispatch_shared_secret)
        return sorted(name for name, present in required.items() if not present)

    def health(self, *, require_oauth: bool = False, require_dispatch: bool = False) -> dict[str, object]:
        missing = self.missing(require_oauth=require_oauth, require_dispatch=require_dispatch)
        return {
            "status": "healthy" if not missing else "configuration_missing",
            "missing": missing,
            "watch_label_count": len(self.gmail_watch_label_ids),
            "secret_values_exposed": False,
        }


__all__ = ["CreatorRuntimeConfig"]
