"""Bounded, no-redirect transport for the private workers.dev incident API."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class IncidentOpsAuthError(RuntimeError):
    """Raised when an OIDC or Worker request cannot be safely verified."""


_ALLOWED_PATHS = {
    ("GET", "/ops/health"),
    ("GET", "/ops/mail/pending-receipts"),
    ("POST", "/ops/incidents/evidence"),
    ("POST", "/ops/incidents/import"),
    ("POST", "/ops/mail/verify"),
    ("POST", "/ops/mail/receipt"),
}
_OIDC_HOSTS = {"pipelines.actions.githubusercontent.com", "actions.githubusercontent.com"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        # Never forward the GitHub OIDC bearer token to a redirect target.
        return None


def _open(request: Request, *, timeout: float):
    return build_opener(_NoRedirect).open(request, timeout=timeout)


def validate_worker_base(value: str) -> str:
    if len(value) > 300:
        raise IncidentOpsAuthError("incident_ops_url_invalid")
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not hostname.endswith(".workers.dev")
        or hostname == "workers.dev"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.netloc.casefold() != hostname
    ):
        raise IncidentOpsAuthError("incident_ops_url_invalid")
    return f"https://{hostname}"


def oidc_environment_diagnostics(environment: dict[str, str], *, audience: str) -> list[str]:
    """Return safe input-shape codes without exposing endpoint or bearer values."""
    endpoint = environment.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    bearer = environment.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    reasons: list[str] = []
    if not endpoint:
        reasons.append("request_url_missing")
    elif len(endpoint) > 12_000:
        reasons.append("request_url_too_long")
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        parsed = None
        reasons.append("request_url_malformed")
    if parsed is not None:
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme.casefold() != "https":
            reasons.append("request_url_scheme_invalid")
        if not hostname:
            reasons.append("request_url_host_missing")
        elif hostname not in _OIDC_HOSTS:
            reasons.append("request_url_host_untrusted")
        if parsed.username is not None or parsed.password is not None:
            reasons.append("request_url_userinfo_present")
        try:
            has_port = parsed.port is not None
        except ValueError:
            has_port = True
            reasons.append("request_url_port_invalid")
        if has_port:
            reasons.append("request_url_explicit_port")
        if parsed.fragment:
            reasons.append("request_url_fragment_present")
        if parsed.netloc and hostname and parsed.netloc.casefold() != hostname:
            reasons.append("request_url_authority_noncanonical")
    if not bearer:
        reasons.append("request_token_missing")
    elif len(bearer) > 32_000:
        reasons.append("request_token_too_long")
    if not audience:
        reasons.append("audience_missing")
    elif len(audience) > 240:
        reasons.append("audience_too_long")
    return sorted(set(reasons))


def fetch_oidc_token(environment: dict[str, str], *, audience: str) -> str:
    endpoint = environment.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    bearer = environment.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    diagnostics = oidc_environment_diagnostics(environment, audience=audience)
    if diagnostics:
        raise IncidentOpsAuthError("github_oidc_request_environment_invalid:" + ",".join(diagnostics))
    parsed = urlsplit(endpoint)
    query = parsed.query
    separator = "&" if query else ""
    endpoint_with_audience = urlunsplit((
        parsed.scheme, parsed.netloc, parsed.path,
        f"{query}{separator}{urlencode({'audience': audience})}", "",
    ))
    request = Request(endpoint_with_audience, headers={
        "Authorization": f"Bearer {bearer}", "Accept": "application/json",
    })
    try:
        with _open(request, timeout=10) as response:
            raw = response.read(100_001)
        if len(raw) > 100_000:
            raise IncidentOpsAuthError("github_oidc_response_too_large")
        value = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raise IncidentOpsAuthError(f"github_oidc_http_{exc.code}") from exc
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IncidentOpsAuthError("github_oidc_token_unavailable") from exc
    token = value.get("value") if isinstance(value, dict) else None
    if not isinstance(token, str) or not token or len(token) > 32_000:
        raise IncidentOpsAuthError("github_oidc_token_invalid")
    return token


def request_worker_json(
    url: str, *, method: str, token: str, payload: dict[str, Any] | None = None,
    require_ok: bool = True,
) -> dict[str, Any]:
    if len(url) > 512 or len(token) > 32_000 or not token:
        raise IncidentOpsAuthError("incident_ops_request_invalid")
    parsed = urlsplit(url)
    base = validate_worker_base(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
    path = parsed.path
    normalized_method = method.upper()
    if (normalized_method, path) not in _ALLOWED_PATHS or parsed.query or parsed.fragment:
        raise IncidentOpsAuthError("incident_ops_endpoint_not_allowed")
    body: bytes | None = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if normalized_method == "POST":
        if payload is None:
            raise IncidentOpsAuthError("incident_ops_payload_required")
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif payload is not None:
        raise IncidentOpsAuthError("incident_ops_get_payload_invalid")
    request = Request(f"{base}{path}", data=body, headers=headers, method=normalized_method)
    try:
        with _open(request, timeout=15) as response:
            raw = response.read(256_001)
        if len(raw) > 256_000:
            raise IncidentOpsAuthError("incident_ops_response_too_large")
        value = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raise IncidentOpsAuthError(f"incident_ops_http_{exc.code}") from exc
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IncidentOpsAuthError("incident_ops_transport_or_response_unknown") from exc
    if not isinstance(value, dict) or (require_ok and value.get("ok") is not True):
        raise IncidentOpsAuthError("incident_ops_response_contract_invalid")
    return value


def worker_get_json(base_url: str, path: str, *, token: str, require_ok: bool = True) -> dict[str, Any]:
    base = validate_worker_base(base_url)
    return request_worker_json(f"{base}{path}", method="GET", token=token, require_ok=require_ok)


def worker_post_json(base_url: str, path: str, payload: dict[str, Any], *, token: str) -> dict[str, Any]:
    base = validate_worker_base(base_url)
    return request_worker_json(f"{base}{path}", method="POST", token=token, payload=payload)
