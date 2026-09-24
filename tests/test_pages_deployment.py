import json

import pytest

from src.pages_deployment import PagesDeploymentError, derive_build_version, verify_deployment

BUILD_VERSION = "a" * 40


def test_derived_pages_identity_is_stable_and_binds_both_revisions():
    first = derive_build_version(source_revision="a" * 40, release_id="release-one")
    assert first == derive_build_version(source_revision="a" * 40, release_id="release-one")
    assert len(first) == 64
    assert first != derive_build_version(source_revision="b" * 40, release_id="release-one")
    assert first != derive_build_version(source_revision="a" * 40, release_id="release-two")


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


def test_verify_uses_pages_build_version_status_endpoint():
    urls = []

    def request_json(url, **_kwargs):
        urls.append(url)
        return {"status": "succeed"}

    result = verify_deployment(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        expected_build_version=BUILD_VERSION,
        request_json=request_json,
    )

    assert result.deployment_id == BUILD_VERSION
    assert result.build_version == BUILD_VERSION
    assert result.status == "succeed"
    assert urls == [
        f"https://api.github.test/repos/owner/repo/pages/deployments/{BUILD_VERSION}"
    ]


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

    def request_json(_url, **_kwargs):
        return {"status": "in_progress"}

    with pytest.raises(PagesDeploymentError, match="not observed before timeout"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            timeout_seconds=3,
            poll_seconds=2,
            request_json=request_json,
            sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
            monotonic=lambda: now[0],
        )


def test_verify_fails_closed_if_pages_reports_terminal_failure():
    def request_json(_url, **_kwargs):
        return {"status": "failure"}

    with pytest.raises(PagesDeploymentError, match="status failure"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version=BUILD_VERSION,
            request_json=request_json,
        )


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
            request_json=request_json,
        )

    assert len(calls) == 1


def test_verify_rejects_non_sha_build_version_before_network_access():
    calls = []

    with pytest.raises(PagesDeploymentError, match="full build-version SHA"):
        verify_deployment(
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            expected_build_version="not/a/sha",
            request_json=lambda *_args, **_kwargs: calls.append(True),
        )

    assert calls == []
