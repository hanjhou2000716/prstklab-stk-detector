import hashlib
import json
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from src import pages_deployment
from src.pages_deployment import (
    PagesDeploymentError,
    _request_json,
    create_deployment,
    derive_build_version,
    verify_deployment,
)

SOURCE_REVISION = "a" * 40
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "site" / "data" / "release-manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
MANIFEST_SHA256 = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
ARTIFACT_DIGEST = "sha256:" + "c" * 64
BUILD_VERSION = derive_build_version(
    source_revision=SOURCE_REVISION,
    release_id=MANIFEST["release_id"],
    snapshot_id=MANIFEST["market_snapshot_id"],
    run_id="17",
    run_attempt=1,
    phase="release",
    manifest_sha256=MANIFEST_SHA256,
    artifact_id="202",
    artifact_digest=ARTIFACT_DIGEST,
)
DEPLOYMENT_ID = "pages-run-17"
STATUS_URL = f"https://api.github.test/repos/owner/repo/pages/deployments/{DEPLOYMENT_ID}/status"
DEPLOYMENT_URL = f"https://api.github.test/repos/owner/repo/pages/deployments/{DEPLOYMENT_ID}"
LEGACY_STATUS_URL = f"https://api.github.test/repos/owner/repo/pages/deployment/status/{DEPLOYMENT_ID}"


@pytest.fixture(autouse=True)
def _stub_downloaded_artifact_manifest(monkeypatch):
    monkeypatch.setattr(
        pages_deployment, "_download_pages_artifact_manifest",
        lambda **_kwargs: MANIFEST_PATH.read_bytes(),
    )


def _pages_artifact_archive(manifest_bytes: bytes) -> bytes:
    tar_stream = BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as packed:
        info = tarfile.TarInfo("./data/release-manifest.json")
        info.size = len(manifest_bytes)
        packed.addfile(info, BytesIO(manifest_bytes))
    zip_stream = BytesIO()
    with zipfile.ZipFile(zip_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("artifact.tar", tar_stream.getvalue())
    return zip_stream.getvalue()


def test_pages_artifact_manifest_is_extracted_from_digest_bound_tarball():
    artifact = _pages_artifact_archive(MANIFEST_PATH.read_bytes())
    digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
    assert pages_deployment._manifest_from_pages_artifact_archive(artifact, expected_digest=digest) == MANIFEST_PATH.read_bytes()


def test_pages_artifact_manifest_rejects_digest_mismatch():
    artifact = _pages_artifact_archive(MANIFEST_PATH.read_bytes())
    with pytest.raises(PagesDeploymentError, match="digest does not match"):
        pages_deployment._manifest_from_pages_artifact_archive(artifact, expected_digest=ARTIFACT_DIGEST)


def test_create_rejects_pages_artifact_manifest_mismatch_before_deployment(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pages_deployment, "_download_pages_artifact_manifest",
        lambda **_kwargs: json.dumps({
            "release_id": "release-from-another-artifact",
            "market_snapshot_id": MANIFEST["market_snapshot_id"],
        }).encode(),
    )

    def request_json(url, **_kwargs):
        calls.append(url)
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{
                "id": 202, "name": "github-pages", "expired": False,
                "digest": ARTIFACT_DIGEST,
                "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION},
            }]}
        raise AssertionError("mismatched frozen manifest must stop before OIDC or deployment create")

    with pytest.raises(PagesDeploymentError, match="differs from the frozen local manifest") as captured:
        create_deployment(
            api_url="https://api.github.test", repository="owner/repo", token="token",
            run_id="17", artifact_name="github-pages", source_revision=SOURCE_REVISION,
            oidc_request_url="https://oidc.actions.test/token", oidc_request_token="request-token",
            request_json=request_json,
        )
    assert captured.value.error_code == "pages_artifact_manifest_mismatch"
    assert len(calls) == 1


def test_create_rejects_pages_artifact_from_another_workflow_revision():
    with pytest.raises(PagesDeploymentError, match="different run or source revision"):
        create_deployment(
            api_url="https://api.github.test", repository="owner/repo", token="token",
            run_id="17", artifact_name="github-pages", source_revision=SOURCE_REVISION,
            oidc_request_url="https://oidc.actions.test/token", oidc_request_token="request-token",
            request_json=lambda *_args, **_kwargs: {"artifacts": [{
                "id": 202, "name": "github-pages", "expired": False,
                "digest": ARTIFACT_DIGEST,
                "workflow_run": {"id": 17, "head_sha": "b" * 40},
            }]},
        )


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
    base = {
        "source_revision": SOURCE_REVISION, "release_id": "release-one", "snapshot_id": "snapshot-one",
        "run_id": "17", "run_attempt": 1, "phase": "release", "manifest_sha256": MANIFEST_SHA256,
        "artifact_id": "202", "artifact_digest": ARTIFACT_DIGEST,
    }
    first = derive_build_version(**base)
    assert first.startswith("prstk-v1-")
    assert first != derive_build_version(**{**base, "source_revision": "b" * 40})
    assert first != derive_build_version(**{**base, "release_id": "release-two"})
    assert first != derive_build_version(**{**base, "artifact_digest": "sha256:" + "d" * 64})
    assert first != derive_build_version(**{**base, "phase": "receipt_reconciliation"})


def test_derived_pages_identity_rejects_missing_or_malformed_inputs():
    with pytest.raises(PagesDeploymentError, match="complete run, release, manifest, and Pages artifact identity"):
        derive_build_version(
            source_revision="not-a-sha", release_id="release-one", snapshot_id="snapshot-one",
            run_id="17", run_attempt=1, phase="release", manifest_sha256=MANIFEST_SHA256,
            artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
        )
    with pytest.raises(PagesDeploymentError, match="complete run, release, manifest, and Pages artifact identity"):
        derive_build_version(
            source_revision=SOURCE_REVISION, release_id="", snapshot_id="snapshot-one",
            run_id="17", run_attempt=1, phase="release", manifest_sha256=MANIFEST_SHA256,
            artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
        )


def test_derive_version_cli_reads_release_identity_from_manifest(tmp_path, monkeypatch):
    from src import pages_deployment

    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(json.dumps({
        "release_id": "release-cli-test", "market_snapshot_id": "snapshot-cli-test",
    }), encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "17")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("PAGES_ARTIFACT_ID", "202")
    monkeypatch.setenv("PAGES_ARTIFACT_DIGEST", ARTIFACT_DIGEST)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        "sys.argv",
        ["pages_deployment", "--mode", "derive-version", "--manifest", str(manifest)],
    )

    assert pages_deployment.main() == 0
    text = output.read_text(encoding="utf-8")
    assert "derived=true" in text
    assert f"pages_build_version={derive_build_version(source_revision='c' * 40, release_id='release-cli-test', snapshot_id='snapshot-cli-test', run_id='17', run_attempt=1, phase='release', manifest_sha256=manifest_sha256, artifact_id='202', artifact_digest=ARTIFACT_DIGEST)}" in text


@pytest.mark.parametrize("status_url", [STATUS_URL, DEPLOYMENT_URL, LEGACY_STATUS_URL])
def test_verify_checks_returned_identity_but_queries_official_deployment_id_endpoint(status_url):
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
        status_url=status_url,
        request_json=request_json,
    )

    assert result.deployment_id == DEPLOYMENT_ID
    assert result.build_version == BUILD_VERSION
    assert result.status == "succeed"
    assert result.status_url == status_url
    assert urls == [DEPLOYMENT_URL]


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


def test_status_url_diagnostics_record_only_sanitized_shape():
    from src.pages_deployment import _safe_status_url_shape

    shape = _safe_status_url_shape(
        STATUS_URL + "?signature=must-not-appear#secret-fragment",
        api_url="https://api.github.test",
        repository="owner/repo",
        deployment_id=DEPLOYMENT_ID,
    )
    assert shape == "scheme=https;host=api;route=deployment_status;userinfo=no;query=yes;fragment=yes"
    assert "signature" not in shape
    assert "must-not-appear" not in shape
    assert "secret-fragment" not in shape


def test_status_url_diagnostics_identify_legacy_official_action_route_without_leaking_url():
    from src.pages_deployment import _safe_status_url_shape

    shape = _safe_status_url_shape(
        LEGACY_STATUS_URL,
        api_url="https://api.github.test",
        repository="owner/repo",
        deployment_id=DEPLOYMENT_ID,
    )
    assert shape == "scheme=https;host=api;route=legacy_deployment_status;userinfo=no;query=no;fragment=no"
    assert LEGACY_STATUS_URL not in shape


def test_verify_rejects_path_injection_in_deployment_id_before_network_access():
    calls = []
    with pytest.raises(PagesDeploymentError, match="deployment ID is invalid"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            deployment_id="../../other/repo",
            status_url="https://api.github.test/repos/other/repo/pages/deployments/17",
            request_json=lambda *_args, **_kwargs: calls.append(True),
        )
    assert calls == []


@pytest.mark.parametrize("status_url", [
    "https://attacker.test/repos/owner/repo/pages/deployments/pages-run-17/status",
    "https://api.github.test/repos/other/repo/pages/deployments/pages-run-17/status",
    STATUS_URL + "?token=secret",
    STATUS_URL + "#fragment",
    "http://api.github.test/repos/owner/repo/pages/deployments/pages-run-17/status",
    STATUS_URL + "/extra",
    STATUS_URL + "/",
    STATUS_URL.replace("pages-run-17", "other-id"),
    STATUS_URL.replace("/repos/owner/repo/", "/repos/owner%2Frepo/"),
    "https://api.github.test/repos/owner/repo/pages/deployments/pages-run-17/../status",
])
def test_verify_rejects_untrusted_or_ambiguous_status_url_without_network(status_url):
    calls = []
    with pytest.raises(PagesDeploymentError, match="does not match the deployment ID"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            deployment_id=DEPLOYMENT_ID,
            status_url=status_url,
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
                {"id": 202, "name": "github-pages", "expired": False, "digest": ARTIFACT_DIGEST,
                 "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION}},
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
        if url == DEPLOYMENT_URL:
            return {"status": "succeed"}
        raise AssertionError(url)

    deployment = create_deployment(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="github-token",
        run_id="17",
        artifact_name="github-pages",
        source_revision=SOURCE_REVISION,
        build_version=BUILD_VERSION,
        oidc_request_url="https://oidc.actions.test/token",
        oidc_request_token="request-token",
        request_json=request_json,
        sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
        monotonic=lambda: now[0],
    )

    assert deployment.deployment_id == DEPLOYMENT_ID
    assert deployment.artifact_id == "202"
    assert deployment.artifact_digest == ARTIFACT_DIGEST
    assert deployment.manifest_sha256 == MANIFEST_SHA256
    assert deployment.release_id == MANIFEST["release_id"]
    assert deployment.snapshot_id == MANIFEST["market_snapshot_id"]
    assert deployment.page_url == "https://dashboard.example.test"
    assert [url for url, _ in calls][-1] == DEPLOYMENT_URL


def test_create_refuses_stale_supplied_build_identity_before_post():
    calls = []

    def request_json(url, **kwargs):
        calls.append(url)
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{
                "id": 202, "name": "github-pages", "expired": False,
                "digest": ARTIFACT_DIGEST,
                "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION},
            }]}
        raise AssertionError("a mismatched identity must stop before OIDC or deployment create")

    with pytest.raises(PagesDeploymentError, match="does not match the frozen deployment identity"):
        create_deployment(
            api_url="https://api.github.test", repository="owner/repo", token="token",
            run_id="17", artifact_name="github-pages", source_revision=SOURCE_REVISION,
            build_version="a" * 40, oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token", request_json=request_json,
        )
    assert len(calls) == 1


def test_create_fails_closed_when_selected_artifact_has_no_digest():
    calls = []

    def request_json(url, **_kwargs):
        calls.append(url)
        return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False}]}

    with pytest.raises(PagesDeploymentError, match="no verified SHA-256 digest"):
        create_deployment(
            api_url="https://api.github.test", repository="owner/repo", token="token",
            run_id="17", artifact_name="github-pages", source_revision=SOURCE_REVISION,
            oidc_request_url="https://oidc.actions.test/token", oidc_request_token="token",
            request_json=request_json,
        )
    assert len(calls) == 1


def test_create_accepts_official_status_url_shape_without_status_suffix():
    def request_json(url, **_kwargs):
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False, "digest": ARTIFACT_DIGEST,
                                   "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION}}]}
        if url == "https://oidc.actions.test/token":
            return {"value": "oidc"}
        if url.endswith("/pages/deployments"):
            return {"id": DEPLOYMENT_ID, "status_url": DEPLOYMENT_URL, "page_url": "https://dashboard.example.test"}
        if url == DEPLOYMENT_URL:
            return {"status": "succeed"}
        raise AssertionError(url)

    deployment = create_deployment(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="github-token",
        run_id="17",
        artifact_name="github-pages",
        source_revision=SOURCE_REVISION,
        build_version=BUILD_VERSION,
        oidc_request_url="https://oidc.actions.test/token",
        oidc_request_token="request-token",
        request_json=request_json,
    )

    assert deployment.deployment_id == DEPLOYMENT_ID
    assert deployment.status_url == DEPLOYMENT_URL


def test_create_accepts_legacy_official_action_status_url_and_queries_by_trusted_id():
    calls = []

    def request_json(url, **_kwargs):
        calls.append(url)
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False, "digest": ARTIFACT_DIGEST,
                                   "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION}}]}
        if url == "https://oidc.actions.test/token":
            return {"value": "oidc"}
        if url.endswith("/pages/deployments"):
            return {"id": DEPLOYMENT_ID, "status_url": LEGACY_STATUS_URL, "page_url": "https://dashboard.example.test"}
        if url == DEPLOYMENT_URL:
            return {"status": "succeed"}
        raise AssertionError(url)

    deployment = create_deployment(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="github-token",
        run_id="17",
        artifact_name="github-pages",
        source_revision=SOURCE_REVISION,
        build_version=BUILD_VERSION,
        oidc_request_url="https://oidc.actions.test/token",
        oidc_request_token="request-token",
        request_json=request_json,
    )

    assert deployment.status_url == LEGACY_STATUS_URL
    assert calls.count("https://api.github.test/repos/owner/repo/pages/deployments") == 1
    assert calls[-1] == DEPLOYMENT_URL


def test_create_rejects_unknown_status_url_after_one_create_without_status_poll():
    calls = []
    unknown_status_url = f"https://api.github.test/repos/owner/repo/pages/deployment/status/{DEPLOYMENT_ID}/extra"

    def request_json(url, **_kwargs):
        calls.append(url)
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False, "digest": ARTIFACT_DIGEST,
                                   "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION}}]}
        if url == "https://oidc.actions.test/token":
            return {"value": "oidc"}
        if url.endswith("/pages/deployments"):
            return {"id": DEPLOYMENT_ID, "status_url": unknown_status_url, "page_url": "https://dashboard.example.test"}
        raise AssertionError(url)

    with pytest.raises(PagesDeploymentError, match="unexpected status URL") as captured:
        create_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="github-token",
            run_id="17",
            artifact_name="github-pages",
            source_revision=SOURCE_REVISION,
            build_version=BUILD_VERSION,
            oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token",
            request_json=request_json,
        )

    assert captured.value.request_outcome == "created"
    assert captured.value.deployment_id == DEPLOYMENT_ID
    assert captured.value.recoverable is False
    assert "route=other" in captured.value.status_url_shape
    assert unknown_status_url not in str(captured.value)
    assert calls.count("https://api.github.test/repos/owner/repo/pages/deployments") == 1
    assert DEPLOYMENT_URL not in calls


def test_create_preserves_trusted_identity_for_one_safe_status_recovery():
    creates = []
    now = [0.0]

    def request_json(url, **_kwargs):
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False, "digest": ARTIFACT_DIGEST,
                                   "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION}}]}
        if url == "https://oidc.actions.test/token":
            return {"value": "oidc"}
        if url.endswith("/pages/deployments"):
            creates.append(True)
            return {"id": DEPLOYMENT_ID, "status_url": STATUS_URL, "page_url": "https://dashboard.example.test"}
        if url == DEPLOYMENT_URL:
            return {"status": "in_progress"}
        raise AssertionError(url)

    with pytest.raises(PagesDeploymentError, match="not observed before timeout") as captured:
        create_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="github-token",
            run_id="17",
            artifact_name="github-pages",
            source_revision=SOURCE_REVISION,
            build_version=BUILD_VERSION,
            oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token",
            timeout_seconds=3,
            poll_seconds=2,
            request_json=request_json,
            sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
            monotonic=lambda: now[0],
        )

    error = captured.value
    assert error.recoverable is True
    assert error.request_outcome == "created"
    assert error.deployment_id == DEPLOYMENT_ID
    assert error.status_url == STATUS_URL
    assert error.page_url == "https://dashboard.example.test"
    assert error.artifact_id == "202"
    assert len(creates) == 1


def test_deploy_cli_exports_only_the_trusted_identity_needed_for_recovery(tmp_path, monkeypatch):
    from src import pages_deployment

    output = tmp_path / "github-output"

    def fail_after_create(**_kwargs):
        raise PagesDeploymentError(
            "status polling timed out",
            retryable=True,
            error_code="pages_deployment_status_timeout",
            request_outcome="created",
            deployment_id=DEPLOYMENT_ID,
            status_url=STATUS_URL,
            page_url="https://dashboard.example.test",
            artifact_id="202",
            recoverable=True,
        )

    monkeypatch.setattr(pages_deployment, "create_deployment", fail_after_create)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_SHA", SOURCE_REVISION)
    monkeypatch.setattr("sys.argv", ["pages_deployment", "--mode", "deploy"])

    assert pages_deployment.main() == 1
    result = output.read_text(encoding="utf-8")
    assert "available=false" in result
    assert "recoverable=true" in result
    assert "request_outcome=created" in result
    assert f"deployment_id={DEPLOYMENT_ID}" in result
    assert f"deployment_status_url={STATUS_URL}" in result
    assert "artifact_id=202" in result


def test_deploy_cli_writes_versioned_exact_artifact_binding(tmp_path, monkeypatch):
    from src import pages_deployment

    output = tmp_path / "github-output"
    binding_path = tmp_path / "binding.json"
    scheduled_build_version = derive_build_version(
        source_revision=SOURCE_REVISION, release_id=MANIFEST["release_id"],
        snapshot_id=MANIFEST["market_snapshot_id"], run_id="17", run_attempt=1,
        phase="scheduled_release", manifest_sha256=MANIFEST_SHA256,
        artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
    )
    deployment = pages_deployment.PagesDeployment(
        deployment_id=DEPLOYMENT_ID,
        status="succeed",
        build_version=scheduled_build_version,
        status_url=STATUS_URL,
        page_url="https://dashboard.example.test",
        artifact_id="202",
        artifact_digest=ARTIFACT_DIGEST,
        manifest_sha256=MANIFEST_SHA256,
        release_id=MANIFEST["release_id"],
        snapshot_id=MANIFEST["market_snapshot_id"],
        run_id="17",
        run_attempt=1,
        phase="scheduled_release",
        artifact_manifest_sha256=MANIFEST_SHA256,
    )
    monkeypatch.setattr(pages_deployment, "create_deployment", lambda **_kwargs: deployment)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_SHA", SOURCE_REVISION)
    monkeypatch.setenv("GITHUB_RUN_ID", "17")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr("sys.argv", [
        "pages_deployment", "--mode", "deploy", "--phase", "scheduled_release",
        "--binding-path", str(binding_path),
    ])

    assert pages_deployment.main() == 0
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    assert binding["schema_version"] == "pages-deployment-binding-v1"
    assert binding["workflow_run_id"] == "17"
    assert binding["workflow_run_attempt"] == 1
    assert binding["artifact_id"] == "202"
    assert binding["artifact_digest"] == ARTIFACT_DIGEST
    assert binding["manifest_sha256"] == MANIFEST_SHA256
    assert binding["artifact_manifest_sha256"] == MANIFEST_SHA256
    assert binding["pages_build_version"] == scheduled_build_version
    assert binding["deployment_id"] == DEPLOYMENT_ID


def test_finalize_public_observation_binds_exact_phase_and_sanitizes_attempts(tmp_path):
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps({
        "schema_version": "pages-deployment-binding-v1",
        "repository": "owner/repo",
        "workflow_run_id": "17",
        "workflow_run_attempt": 1,
        "source_revision": SOURCE_REVISION,
        "phase": "scheduled_release",
        "artifact_id": "202",
        "artifact_digest": ARTIFACT_DIGEST,
        "manifest_sha256": MANIFEST_SHA256,
        "release_id": MANIFEST["release_id"],
        "snapshot_id": MANIFEST["market_snapshot_id"],
    }), encoding="utf-8")

    result = pages_deployment.finalize_binding_public_observation(
        binding_path=binding_path,
        phase="scheduled_release",
        gate_outcome="success",
        gate_allowed=True,
        gate_status="verified",
        expected_release_id=MANIFEST["release_id"],
        actual_release_id=MANIFEST["release_id"],
        expected_snapshot_id=MANIFEST["market_snapshot_id"],
        actual_snapshot_id=MANIFEST["market_snapshot_id"],
        http_status="200",
        attempts_json=json.dumps([{
            "attempt": 1, "http_status": 200,
            "expected_release_id": MANIFEST["release_id"],
            "actual_release_id": MANIFEST["release_id"],
            "authorization": "secret-token",
            "url": "https://signed.example.test/?sig=secret",
        }]),
    )
    observation = result["public_observation"]
    assert observation["status"] == "verified"
    assert observation["attempts"] == [{"attempt": 1, "http_status": 200,
        "expected_release_id": MANIFEST["release_id"],
        "actual_release_id": MANIFEST["release_id"]}]
    assert "secret-token" not in binding_path.read_text(encoding="utf-8")
    assert "signed.example.test" not in binding_path.read_text(encoding="utf-8")


def test_finalize_public_observation_rejects_phase_or_identity_conflict(tmp_path):
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps({
        "schema_version": "pages-deployment-binding-v1",
        "repository": "owner/repo",
        "workflow_run_id": "17",
        "workflow_run_attempt": 1,
        "source_revision": SOURCE_REVISION,
        "phase": "scheduled_release",
    }), encoding="utf-8")
    with pytest.raises(PagesDeploymentError, match="identity is invalid"):
        pages_deployment.finalize_binding_public_observation(
            binding_path=binding_path, phase="receipt_reconciliation",
            gate_outcome="success", gate_allowed=True, gate_status="verified",
        )
    with pytest.raises(PagesDeploymentError, match="contradictory identity"):
        pages_deployment.finalize_binding_public_observation(
            binding_path=binding_path, phase="scheduled_release",
            gate_outcome="success", gate_allowed=True, gate_status="verified",
            expected_release_id="release-a", actual_release_id="release-a",
            expected_snapshot_id="snapshot-a", actual_snapshot_id="snapshot-b",
        )


def test_verify_cli_never_exports_untrusted_deployment_id_or_signed_url(tmp_path, monkeypatch):
    from src import pages_deployment

    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr("sys.argv", [
        "pages_deployment", "--mode", "verify",
        "--deployment-id", "../../other/repo",
        "--status-url", "https://api.github.com/status?signature=secret-value",
    ])

    assert pages_deployment.main() == 1
    result = output.read_text(encoding="utf-8")
    assert "deployment_id=\n" in result
    assert "deployment_status_url=\n" in result
    assert "signature" not in result
    assert "secret-value" not in result
    assert "deployment_status_url_shape=" in result


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
            source_revision=SOURCE_REVISION,
            build_version=BUILD_VERSION,
            oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token",
            request_json=lambda *_args, **_kwargs: {"artifacts": artifacts},
        )


def test_create_does_not_repeat_an_ambiguous_create_request():
    creates = []

    def request_json(url, **_kwargs):
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False, "digest": ARTIFACT_DIGEST,
                                   "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION}}]}
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
            source_revision=SOURCE_REVISION,
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
            return {"artifacts": [{"id": 202, "name": "github-pages", "expired": False, "digest": ARTIFACT_DIGEST,
                                   "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION}}]}
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
            source_revision=SOURCE_REVISION,
            build_version=BUILD_VERSION,
            oidc_request_url="https://oidc.actions.test/token",
            oidc_request_token="request-token",
            request_json=request_json,
        )

    assert captured.value.error_code == "pages_http_400"
    assert captured.value.request_outcome == "rejected"
    assert len(creates) == 1
