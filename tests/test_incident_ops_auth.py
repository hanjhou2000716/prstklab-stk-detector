from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from scripts import incident_ops_auth as auth


@pytest.mark.parametrize("value", [
    "http://prstk.account.workers.dev",
    "https://workers.dev",
    "https://prstk.account.workers.dev.evil.example",
    "https://user@prstk.account.workers.dev",
    "https://prstk.account.workers.dev:443",
    "https://prstk.account.workers.dev/path",
    "https://prstk.account.workers.dev?redirect=https://evil.example",
    "https://prstk.account.workers.dev#fragment",
])
def test_worker_base_rejects_noncanonical_or_untrusted_urls(value: str) -> None:
    with pytest.raises(auth.IncidentOpsAuthError, match="incident_ops_url_invalid"):
        auth.validate_worker_base(value)


def test_worker_base_accepts_workers_dev_without_custom_domain() -> None:
    assert auth.validate_worker_base("https://prstk.account.workers.dev") == "https://prstk.account.workers.dev"


def test_worker_request_rejects_unapproved_endpoint_before_network() -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("network must not be used")

    old = auth._open
    auth._open = fail_if_called
    try:
        with pytest.raises(auth.IncidentOpsAuthError, match="incident_ops_endpoint_not_allowed"):
            auth.request_worker_json(
                "https://prstk.account.workers.dev/ops/outbox/state",
                method="GET", token="test-token",
            )
    finally:
        auth._open = old


def test_worker_request_sends_no_redirect_and_only_to_allowed_workers_dev(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps({"ok": True, "mode": "shadow"}).encode()

    def fake_open(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(auth, "_open", fake_open)
    result = auth.request_worker_json(
        "https://prstk.account.workers.dev/ops/health", method="GET", token="test-token",
    )
    assert result["mode"] == "shadow"
    assert captured["request"].full_url == "https://prstk.account.workers.dev/ops/health"
    assert captured["request"].get_header("Authorization") == "Bearer test-token"
    assert isinstance(auth._NoRedirect(), auth.HTTPRedirectHandler)


def test_oidc_request_rejects_untrusted_host(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_open", lambda *args, **kwargs: pytest.fail("unexpected network request"))
    with pytest.raises(auth.IncidentOpsAuthError, match="github_oidc_request_environment_invalid"):
        auth.fetch_oidc_token({
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://pipelines.actions.githubusercontent.com.evil.test/token",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
        }, audience="https://prstk-incident-ops")


def test_oidc_environment_diagnostic_classifies_missing_and_untrusted_inputs_without_values():
    environment = {
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://evil.example/sensitive-path?secret=do-not-log",
    }
    diagnostics = auth.oidc_environment_diagnostics(environment, audience="https://prstk-incident-ops")
    assert diagnostics == ["request_token_missing", "request_url_host_untrusted"]
    with pytest.raises(auth.IncidentOpsAuthError) as error:
        auth.fetch_oidc_token(environment, audience="https://prstk-incident-ops")
    assert "request_url_host_untrusted" in str(error.value)
    assert "sensitive-path" not in str(error.value)
    assert "do-not-log" not in str(error.value)


def test_oidc_token_request_uses_audience_and_converts_redirect_to_failure(monkeypatch) -> None:
    captured = {}

    def fake_open(request, *, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        raise HTTPError(request.full_url, 302, "redirect", {}, None)

    monkeypatch.setattr(auth, "_open", fake_open)
    with pytest.raises(auth.IncidentOpsAuthError, match="github_oidc_http_302"):
        auth.fetch_oidc_token({
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://pipelines.actions.githubusercontent.com/path?foo=bar",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
        }, audience="https://prstk-incident-ops")
    assert "audience=https%3A%2F%2Fprstk-incident-ops" in captured["url"]
    assert captured["auth"] == "Bearer request-token"
