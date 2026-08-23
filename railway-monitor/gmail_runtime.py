"""Standalone Gmail ingress wiring for the Railway deployment pack.

The module owns configuration-to-ingress construction only.  Parsing,
authentication, persistence and routing stay in their existing components;
this keeps ``app.py`` from becoming a second Gmail pipeline.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

try:
    from health_contract import gmail_health_fields
except ModuleNotFoundError:  # pragma: no cover - direct file loading
    _spec = spec_from_file_location("railway_health_contract", Path(__file__).with_name("health_contract.py"))
    if _spec is None or _spec.loader is None:
        raise ImportError("cannot load railway-monitor/health_contract.py") from None
    _module = module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    gmail_health_fields = _module.gmail_health_fields


def configure_gmail_ingress(
    environ: Mapping[str, str] | None = None,
    *,
    config_factory: Callable[[Mapping[str, str] | None], Any] | None = None,
    store_factory: Callable[[str], Any] | None = None,
    ingress_factory: Callable[[Any, Any], Any] | None = None,
) -> tuple[Any | None, dict[str, Any]]:
    """Build a Gmail ingress and return a redacted health projection.

    Factories are injectable so this boundary can be contract-tested without
    Gmail credentials or a filesystem.  Production defaults import only the
    existing Railway-local modules.
    """
    env = environ or os.environ
    try:
        default_ingress = ingress_factory is None
        if config_factory is None or store_factory is None or ingress_factory is None:
            from email_store import EmailStore
            from gmail_watch import GmailWatchConfig

            from gmail_ingress import GmailIngressService

            config_factory = config_factory or GmailWatchConfig.from_env
            store_factory = store_factory or EmailStore
            ingress_factory = ingress_factory or GmailIngressService
        config = config_factory(env)
        path = env.get("GMAIL_STATE_PATH", "/data/gmail-ingress.sqlite3")
        if default_ingress:
            verifier = _google_oidc_verifier if getattr(config, "require_jwt_verification", False) else None
            ingress = ingress_factory(store_factory(path), config, token_verifier=verifier)
        else:
            ingress = ingress_factory(store_factory(path), config)
        # The lease is independent from Pub/Sub HTTP availability.  Attempt
        # renewal once at startup; the manager persists a bounded failure so
        # health probes can report it while the worker remains alive.
        ensure_watch = getattr(ingress, "ensure_watch", None)
        if callable(ensure_watch):
            ensure_watch()
        diagnostics = ingress.health()
        return ingress, {
            "status": "configuration_missing" if config.missing else "ready",
            **gmail_health_fields(diagnostics),
            # Keep the configuration contract authoritative even when the
            # ingress health payload predates the public ``missing`` field.
            "missing": list(config.missing),
            "error": None,
        }
    except Exception as error:  # pragma: no cover - defensive startup boundary
        return None, {
            "status": "failed",
            "watch_status": "not_checked",
            "observability": {},
            "error": type(error).__name__,
        }


def _google_oidc_verifier(token: str, audience: str) -> Mapping[str, Any]:
    """Verify a Pub/Sub OIDC token and return its signed claims."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, Request(), audience=audience)
