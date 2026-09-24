import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from src.pages_deployment import (
    PagesDeploymentError,
    _request_json,
    create_deployment,
    derive_build_version,
    verify_deployment,
)

BUILD_VERSION = "a" * 40
DEPLOYMENT_ID = "pages-run-17"
STATUS_URL = f"https://api.github.test/repos/owner/repo/pages/deployments/{DEPLOYMENT_ID}/status"


def test_post_request_sends_json_content_type(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"id":"deployment-1"}'

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["content_type"] = request.get_header("Content-type")
        captured["body"] = request.data
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("src.pages_deployment.urlopen", fake_urlopen)
    result = _request_json(
        "https://api.github.test/repos/owner/repo/pages/deployments",
        token="test-token",
        method="POST",
        payload={"artifact_id": 123, "pages_build_version": BUILD_VERSION},
    )

    assert result == {"id": "deployment-1"}
    assert captured["method"] == "POST"
    assert captured["content_type"] == "application/json"
    assert json.loads(captured["body"].decode("utf-8")) == {
        "artifact_id": 123,
        "pages_build_version": BUILD_VERSION,
    }


def test_pages_identity_keeps_source_revision_separate_from_content_release():
    first = derive_build_version(source_revision="a" * 40, release_id="release-one")
    assert first == "a" * 40
    assert first != derive_build_version(source_revision="b" * 40, release_id="release-one")
    assert first == derive_build_version(source_revision="a" * 40, release_id="release-two")


def test_derived_pages_identity_rejects_missing_or_malformed_inputs():
    with pytest.raises(PagesDeploymentError, match="source revision and release identity"):
        derive_build_version(source_revision="not-a-sha", release_id="release-one")
    with pytest.raises(PagesDeploymentError, match="source revision and release identity"):
        derive_build_version(source_revision="a" * 40, release_id="")


def test_derive_version_cli_reads_release_identity_from_manifest(tmp_path, monkeypatch):
    from src import pages_deployment

    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(json.dumps({"release_id": "release-cli-test"}), encoding="utf-8")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        "sys.argv",
        ["pages_deployment", "--mode", "derive-version", "--manifest", str(manifest)],
    )

    assert pages_deployment.main() == 0
    text = output.read_text(encoding="utf-8")
    assert "derived=true" in text
    assert f"pages_build_version={derive_build_version(source_revision='c' * 40, release_id='release-cli-test')}" in text


def test_verify_uses_only_the_api_returned_deployment_id_and_status_url():
    urls = []

    def request_json(url, **_kwargs):
        urls.append(url)
        return {"status": "succeed"}

    result = verify_deployment(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        expected_build_version=BUILD_VERSION,
        deployment_id=DEPLOYMENT_ID,
        status_url=STATUS_URL,
        request_json=request_json,
    )

    assert result.deployment_id == DEPLOYMENT_ID
    assert result.build_version == BUILD_VERSION
    assert result.status == "succeed"
    assert result.status_url == STATUS_URL
    assert urls == [STATUS_URL]


def test_verify_retries_temporarily_missing_pages_deployment_status():
    now = [0.0]
    attempts = [0]

    def request_json(_url, **_kwargs):
        attempts[0] += 1
        if attempts[0] == 1:
            raise PagesDeploymentError("HTTP 404", retryable=True)
        return {"status": "succeed"}

    result = verify_deployment(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        expected_build_version=BUILD_VERSION,
        deployment_id=DEPLOYMENT_ID,
        status_url=STATUS_URL,
        timeout_seconds=10,
        poll_seconds=2,
        request_json=request_json,
        sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
        monotonic=lambda: now[0],
    )
    assert result.status == "succeed"
    assert attempts[0] == 2


def test_verify_fails_closed_if_no_success_status_arrives_before_deadline():
    now = [0.0]

    with pytest.raises(PagesDeploymentError, match="not observed before timeout"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            deployment_id=DEPLOYMENT_ID,
            status_url=STATUS_URL,
            timeout_seconds=3,
            poll_seconds=2,
            request_json=lambda *_args, **_kwargs: {"status": "in_progress"},
            sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
            monotonic=lambda: now[0],
        )


@pytest.mark.parametrize("status", [
    "error", "failure", "inactive", "deployment_failed", "deployment_perms_error",
    "deployment_content_failed", "deployment_cancelled", "deployment_lost",
])
def test_verify_fails_immediately_for_terminal_statuses(status):
    with pytest.raises(PagesDeploymentError, match=status):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            deployment_id=DEPLOYMENT_ID,
            status_url=STATUS_URL,
            request_json=lambda *_args, **_kwargs: {"status": status},
        )


def test_verify_rejects_untrusted_status_url_before_network_access():
    calls = []
    with pytest.raises(PagesDeploymentError, match="does not match the deployment ID"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            deployment_id=DEPLOYMENT_ID,
            status_url="https://attacker.test/status",
            request_json=lambda *_args, **_kwargs: calls.append(True),
        )
    assert calls == []


def test_verify_does_not_retry_permanent_pages_permission_error():
    calls = []

    def request_json(*_args, **_kwargs):
        calls.append(True)
        raise PagesDeploymentError("HTTP 403", retryable=False)

    with pytest.raises(PagesDeploymentError, match="HTTP 403"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            deployment_id=DEPLOYMENT_ID,
            status_url=STATUS_URL,
            request_json=request_json,
        )
    assert len(calls) == 1


def test_create_selects_one_run_artifact_and_uses_deployment_response_identity():
    calls = []
    now = [0.0]

    def request_json(url, **kwargs):
        calls.append((url, kwargs))
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [
                {"id": 101, "name": "other-artifact", "expired": False},
                {"id": 202, "name": "github-pages", "expired": False},
            ]}
        if "oidc.actions.test" in url:
            assert url == "https://oidc.actions.test/token"
            return {"value": "sensitive-oidc-token"}
        if url.endswith("/pages/deployments"):
            assert kwargs["method"] == "POST"
            assert kwargs["payload"]["artifact_id"] == 202
            assert kwargs["payload"]["pages_build_version"] == BUILD_VERSION
            assert kwargs["payload"]["oidc_token"] == "sensitive-oidc-token"
            assert "environment" not in kwargs["payload"]
            return {"id": DEPLOYMENT_ID, "status_url": STATUS_URL, "page_url": "https://dashboard.example.test"}
        if url == STATUS_URL:
            return {"status": "succeed"}
        raise AssertionError(url)

    deployment = create_deployment(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="github-token",
        run_id="17",
        artifact_name="github-pages",
        source_revision=BUILD_VERSION,
        build_version=BUILD_VERSION,
        oidc_request_url="https://oidc.actions.test/token",
        oidc_request_token="request-token",
        request_json=request_json,
        sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
        monotonic=lambda: now[0],
    )

    assert deployment.deployment_id == DEPLOYMENT_ID
    assert deployment.artifact_id == "202"
    assert deployment.page_url == "https://dashboard.example.test"
    assert [url for url, _ in calls][-1] == STATUS_URL


@pytest.mark.parametrize("artifacts", [
    [],
    [
        {"id": 1, "name": "github-pages", "expired": False},
        {"id": 2, "name": "github-pages", "expired": False},
    ],
])
def test_create_fails_closed_when_run_artifact_is_missing_or_ambiguous(artifacts):
    with pytest.raises(PagesDeploymentError, match="exactly one matching"):
        create_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            run_id="17",
            artifact_name="github-pages",
            source_revision=BUILD_VERSION,
            build_version=BUILD_VERSION,
            oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token",
            request_json=lambda *_args, **_kwargs: {"artifacts": artifacts},
        )


def test_create_does_not_repeat_an_ambiguous_create_request():
    creates = []

    def request_json(url, **_kwargs):
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False}]}
        if "oidc.actions.test" in url:
            return {"value": "oidc"}
        if url.endswith("/pages/deployments"):
            creates.append(True)
            raise PagesDeploymentError("HTTP 502", retryable=True)
        raise AssertionError(url)

    with pytest.raises(PagesDeploymentError, match="refusing a duplicate create"):
        create_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            run_id="17",
            artifact_name="github-pages",
            source_revision=BUILD_VERSION,
            build_version=BUILD_VERSION,
            oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token",
            request_json=request_json,
        )
    assert len(creates) == 1


def test_pages_http_error_keeps_safe_diagnostic_without_secrets(monkeypatch):
    body = json.dumps({
        "message": "Invalid audience secret-token eyJhbGciOiJIUzI1NiJ9.payload.signature https://host.test/path?token=secret",
        "errors": [{"resource": "PagesDeployment", "field": "oidc_token", "code": "invalid"}],
    }).encode("utf-8")

    def fail_request(_request, timeout):
        raise HTTPError("https://api.github.test/pages/deployments", 400, "Bad Request", {}, BytesIO(body))

    monkeypatch.setattr("src.pages_deployment.urlopen", fail_request)
    with pytest.raises(PagesDeploymentError) as captured:
        _request_json(
            "https://api.github.test/repos/owner/repo/pages/deployments",
            token="secret-token",
            method="POST",
            payload={"oidc_token": "secret-token"},
        )

    error = captured.value
    assert error.error_code == "pages_http_400"
    assert error.request_outcome == "rejected"
    assert "Invalid audience" in str(error)
    assert "PagesDeployment/oidc_token/invalid" in str(error)
    assert "secret-token" not in str(error)
    assert "[url]" in str(error)


def test_definitive_http_400_create_is_classified_as_rejected_without_retry():
    creates = []

    def request_json(url, **_kwargs):
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False}]}
        if url == "https://oidc.actions.test/token":
            return {"value": "oidc"}
        if url.endswith("/pages/deployments"):
            creates.append(True)
            raise PagesDeploymentError(
                "GitHub Pages request returned HTTP 400: invalid audience",
                error_code="pages_http_400",
                request_outcome="rejected",
            )
        raise AssertionError(url)

    with pytest.raises(PagesDeploymentError, match="was rejected") as captured:
        create_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            run_id="17",
            artifact_name="github-pages",
            source_revision=BUILD_VERSION,
            build_version=BUILD_VERSION,
            oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token",
            request_json=request_json,
        )

    assert captured.value.error_code == "pages_http_400"
    assert captured.value.request_outcome == "rejected"
    assert len(creates) == 1

