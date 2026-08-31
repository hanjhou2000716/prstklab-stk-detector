from __future__ import annotations

import ssl

import requests

from src.http_client import configure_public_source_tls


def test_public_source_tls_keeps_certificate_verification() -> None:
    session = configure_public_source_tls()
    assert isinstance(session, requests.Session)
    adapter = session.get_adapter("https://example.com")
    context = adapter._ssl_context  # type: ignore[attr-defined]
    assert context.verify_mode is ssl.CERT_REQUIRED
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    assert not strict_flag or not (context.verify_flags & strict_flag)


def test_public_source_tls_configuration_is_idempotent() -> None:
    session = requests.Session()
    assert configure_public_source_tls(session) is session
    adapter = session.get_adapter("https://example.com")
    assert configure_public_source_tls(session) is session
    assert session.get_adapter("https://example.com") is adapter
