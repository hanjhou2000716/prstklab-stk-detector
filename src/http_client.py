"""Shared HTTPS client configuration for public data providers."""

from __future__ import annotations

import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context


class _PublicSourceTLSAdapter(HTTPAdapter):
    """Keep CA/hostname checks while tolerating missing optional X.509 SKI."""

    def __init__(self) -> None:
        context = create_urllib3_context()
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if strict_flag:
            context.verify_flags &= ~strict_flag
        self._ssl_context = context
        super().__init__()

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: object) -> None:
        pool_kwargs["ssl_context"] = self._ssl_context
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: object):
        proxy_kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def configure_public_source_tls(session: requests.Session | None = None) -> requests.Session:
    """Return a session with verified, cross-runner-compatible public HTTPS."""
    client = session or requests.Session()
    # Test doubles and provider adapters may implement only ``get``/``post``;
    # leave those untouched instead of imposing a requests-only mount API.
    if not hasattr(client, "mount"):
        return client
    if not getattr(client, "_prstk_public_tls", False):
        client.mount("https://", _PublicSourceTLSAdapter())
        client._prstk_public_tls = True  # type: ignore[attr-defined]
    return client
