import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from src import pages_deployment
from src.pages_deployment import (
    PagesDeploymentError,
    _request_json,
    create_deployment,
    derive_build_version,
    derive_release_binding_id,
    verify_deployment,
)

_REAL_ARTIFACT_DOWNLOADER = pages_deployment._download_pages_artifact_manifest

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


def _pages_artifact_archive(manifest_bytes: bytes, *, include_root: bool = True) -> bytes:
    tar_stream = BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as packed:
        if include_root:
            root = tarfile.TarInfo(".")
            root.type = tarfile.DIRTYPE
            packed.addfile(root)
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


def test_artifact_download_retries_transient_404_for_the_same_exact_artifact(monkeypatch):
    artifact = _pages_artifact_archive(MANIFEST_PATH.read_bytes())
    digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
    calls = []
    delays = []

    class Response:
        headers = {"x-ms-request-id": "blob-request-123"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://productionresultssa1.blob.core.windows.net/signed-path"

        def getcode(self):
            return 200

        def read(self, _size):
            nonlocal artifact
            if artifact:
                body, artifact = artifact, b""
                return body
            return b""

    def open_artifact(request, *, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise HTTPError(
                request.full_url, 404, "not ready", {"X-GitHub-Request-Id": "gh-req-123"}, BytesIO(),
            )
        return Response()

    monkeypatch.setattr(pages_deployment, "_open_artifact_url", open_artifact)
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    diagnostics = {}
    manifest = pages_deployment._download_pages_artifact_manifest(
        api_url="https://api.github.com", repository="owner/repo", token="secret",
        artifact_id="202", artifact_digest=digest, sleeper=delays.append,
        diagnostics=diagnostics,
    )

    assert manifest == MANIFEST_PATH.read_bytes()
    assert [url for url, _timeout in calls] == [
        "https://api.github.com/repos/owner/repo/actions/artifacts/202/zip",
    ] * 2
    assert all(isinstance(timeout, int) and timeout <= 30 for _url, timeout in calls)
    assert delays == [1.0]
    assert diagnostics == {
        "artifact_read_attempts": 2,
        "artifact_read_http_status": 200,
        "artifact_read_response_host": "github_artifact_blob",
        "artifact_read_request_id": "blob-request-123",
    }


def test_artifact_download_stops_after_three_transient_failures(monkeypatch):
    calls = []
    delays = []

    def unavailable(request, *, timeout):
        calls.append(request.full_url)
        raise HTTPError(
            request.full_url, 404, "not ready", {"X-GitHub-Request-Id": "gh-req-456"}, BytesIO(),
        )

    monkeypatch.setattr(pages_deployment, "_open_artifact_url", unavailable)
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    with pytest.raises(PagesDeploymentError, match="after 3 attempt") as captured:
        pages_deployment._download_pages_artifact_manifest(
            api_url="https://api.github.com", repository="owner/repo", token="secret",
            artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
            sleeper=delays.append, monotonic=lambda: 0.0,
        )

    assert calls == ["https://api.github.com/repos/owner/repo/actions/artifacts/202/zip"] * 3
    assert delays == [1.0, 2.0]
    assert captured.value.error_code == "pages_artifact_download_http_404"
    assert captured.value.request_outcome == "not_started"
    assert captured.value.artifact_read_attempts == 3
    assert captured.value.artifact_read_http_status == 404
    assert captured.value.artifact_read_response_host == "github_api"
    assert captured.value.artifact_read_request_id == "gh-req-456"


def test_redirected_blob_404_is_distinguished_without_logging_signed_url(monkeypatch, capsys):
    calls = []
    blob_url = "https://productionresultssa1.blob.core.windows.net/private?sig=do-not-log"

    def unavailable(request, *, timeout):
        calls.append(request.full_url)
        raise HTTPError(
            blob_url, 404, "not ready", {"x-ms-request-id": "storage-req-789"}, BytesIO(),
        )

    monkeypatch.setattr(pages_deployment, "_open_artifact_url", unavailable)
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    with pytest.raises(PagesDeploymentError) as captured:
        pages_deployment._download_pages_artifact_manifest(
            api_url="https://api.github.com", repository="owner/repo", token="github-secret",
            artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
            sleeper=lambda _delay: None, monotonic=lambda: 0.0,
        )

    assert len(calls) == 3
    assert all(url.endswith("/actions/artifacts/202/zip") for url in calls)
    assert captured.value.artifact_read_response_host == "github_artifact_blob"
    assert captured.value.artifact_read_request_id == "storage-req-789"
    logged = capsys.readouterr().err
    assert "github-secret" not in logged
    assert "do-not-log" not in logged
    assert "private?" not in logged


def test_artifact_download_retries_transient_transport_timeout(monkeypatch):
    archive = _pages_artifact_archive(MANIFEST_PATH.read_bytes())
    calls = []
    delays = []

    def timeout_once_then_succeed(request, *, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise URLError(TimeoutError("timed out"))
        return _BytesResponse(archive)

    monkeypatch.setattr(pages_deployment, "_open_artifact_url", timeout_once_then_succeed)
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    manifest = pages_deployment._download_pages_artifact_manifest(
        api_url="https://api.github.com", repository="owner/repo", token="secret",
        artifact_id="202", artifact_digest="sha256:" + hashlib.sha256(archive).hexdigest(),
        sleeper=delays.append, monotonic=lambda: 0.0,
    )

    assert manifest == MANIFEST_PATH.read_bytes()
    assert calls == ["https://api.github.com/repos/owner/repo/actions/artifacts/202/zip"] * 2
    assert delays == [1.0]


def test_artifact_download_does_not_retry_authorization_or_digest_failures(monkeypatch):
    calls = []

    def forbidden(request, *, timeout):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 403, "forbidden", {}, BytesIO())

    monkeypatch.setattr(pages_deployment, "_open_artifact_url", forbidden)
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    with pytest.raises(PagesDeploymentError) as forbidden_error:
        pages_deployment._download_pages_artifact_manifest(
            api_url="https://api.github.com", repository="owner/repo", token="secret",
            artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
            sleeper=lambda _delay: pytest.fail("403 must not be retried"),
        )
    assert forbidden_error.value.error_code == "pages_artifact_download_http_403"
    assert len(calls) == 1

    archive = _pages_artifact_archive(MANIFEST_PATH.read_bytes())
    monkeypatch.setattr(
        pages_deployment, "_open_artifact_url",
        lambda *_args, **_kwargs: _BytesResponse(archive),
    )
    calls.clear()
    with pytest.raises(PagesDeploymentError) as digest_error:
        pages_deployment._download_pages_artifact_manifest(
            api_url="https://api.github.com", repository="owner/repo", token="secret",
            artifact_id="202", artifact_digest="sha256:" + "0" * 64,
            sleeper=lambda _delay: pytest.fail("digest mismatch must not be retried"),
        )
    assert digest_error.value.error_code == "pages_artifact_digest_mismatch"


class _BytesResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return "https://productionresultssa1.blob.core.windows.net/signed-path"

    def getcode(self):
        return 200

    def read(self, _size):
        body, self.body = self.body, b""
        return body


def test_artifact_download_deadline_prevents_any_read_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pages_deployment, "_open_artifact_url",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    with pytest.raises(PagesDeploymentError) as captured:
        pages_deployment._download_pages_artifact_manifest(
            api_url="https://api.github.com", repository="owner/repo", token="secret",
            artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
            deadline_epoch=99, wall_clock=lambda: 100,
        )
    assert captured.value.error_code == "pages_artifact_download_deadline_exhausted"
    assert captured.value.artifact_read_attempts == 0
    assert calls == []


def test_artifact_download_does_not_round_subsecond_budget_past_deadline(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pages_deployment, "_open_artifact_url",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    with pytest.raises(PagesDeploymentError) as captured:
        pages_deployment._download_pages_artifact_manifest(
            api_url="https://api.github.com", repository="owner/repo", token="secret",
            artifact_id="202", artifact_digest=ARTIFACT_DIGEST,
            timeout=0.5, sleeper=lambda _delay: None, monotonic=lambda: 0.0,
        )
    assert captured.value.error_code == "pages_artifact_download_deadline_exhausted"
    assert captured.value.artifact_read_attempts == 0
    assert calls == []


@pytest.mark.parametrize("include_root", [True, False])
def test_pages_artifact_accepts_root_directory_without_changing_manifest_bytes(include_root):
    artifact = _pages_artifact_archive(MANIFEST_PATH.read_bytes(), include_root=include_root)
    digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
    assert pages_deployment._manifest_from_pages_artifact_archive(
        artifact, expected_digest=digest,
    ) == MANIFEST_PATH.read_bytes()


def test_pages_artifact_accepts_actual_gnu_tar_upload_format(tmp_path):
    tar = shutil.which("tar")
    if tar is None or "GNU tar" not in subprocess.run(
        [tar, "--version"], check=True, capture_output=True, text=True,
    ).stdout:
        pytest.skip("the Linux Pages uploader uses GNU tar")
    source = tmp_path / "payload"
    (source / "data").mkdir(parents=True)
    (source / "data" / "release-manifest.json").write_bytes(MANIFEST_PATH.read_bytes())
    tar_path = tmp_path / "artifact.tar"
    subprocess.run(
        [tar, "--dereference", "--hard-dereference", "--directory", str(source),
         "-cf", str(tar_path), "--exclude=.git", "--exclude=.github", "."],
        check=True, capture_output=True,
    )
    with tarfile.open(tar_path) as packed:
        assert packed.getmembers()[0].name == "."
        assert packed.getmembers()[0].isdir()
    archive_stream = BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("artifact.tar", tar_path.read_bytes())
    artifact = archive_stream.getvalue()
    assert pages_deployment._manifest_from_pages_artifact_archive(
        artifact, expected_digest="sha256:" + hashlib.sha256(artifact).hexdigest(),
    ) == MANIFEST_PATH.read_bytes()


@pytest.mark.parametrize(
    ("root_name", "root_type", "root_size", "duplicate_root"),
    [
        (".", tarfile.REGTYPE, 0, False),
        ("./", tarfile.SYMTYPE, 0, False),
        (".", tarfile.LNKTYPE, 0, False),
        (".", tarfile.DIRTYPE, 1, False),
        (".", tarfile.DIRTYPE, 0, True),
        ("./../", tarfile.DIRTYPE, 0, False),
        ("/", tarfile.DIRTYPE, 0, False),
    ],
)
def test_pages_artifact_root_marker_does_not_allow_unsafe_or_duplicate_entries(
    root_name, root_type, root_size, duplicate_root,
):
    tar_stream = BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as packed:
        root = tarfile.TarInfo(root_name)
        root.type = root_type
        root.size = root_size
        if root_type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
            root.linkname = "../outside"
        packed.addfile(root)
        if duplicate_root:
            duplicate = tarfile.TarInfo("./")
            duplicate.type = tarfile.DIRTYPE
            packed.addfile(duplicate)
        raw = MANIFEST_PATH.read_bytes()
        manifest = tarfile.TarInfo("data/release-manifest.json")
        manifest.size = len(raw)
        packed.addfile(manifest, BytesIO(raw))
    archive_stream = BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("artifact.tar", tar_stream.getvalue())
    artifact = archive_stream.getvalue()
    with pytest.raises(PagesDeploymentError):
        pages_deployment._manifest_from_pages_artifact_archive(
            artifact, expected_digest="sha256:" + hashlib.sha256(artifact).hexdigest(),
        )


def test_pages_artifact_manifest_rejects_digest_mismatch():
    artifact = _pages_artifact_archive(MANIFEST_PATH.read_bytes())
    with pytest.raises(PagesDeploymentError, match="digest does not match"):
        pages_deployment._manifest_from_pages_artifact_archive(artifact, expected_digest=ARTIFACT_DIGEST)


def test_pages_artifact_tar_rejects_path_traversal_before_extracting_manifest():
    tar_stream = BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as packed:
        traversal = tarfile.TarInfo("../escape.txt")
        traversal.size = 1
        packed.addfile(traversal, BytesIO(b"x"))
        info = tarfile.TarInfo("data/release-manifest.json")
        raw = MANIFEST_PATH.read_bytes()
        info.size = len(raw)
        packed.addfile(info, BytesIO(raw))
    archive_stream = BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("artifact.tar", tar_stream.getvalue())
    artifact = archive_stream.getvalue()
    digest = "sha256:" + hashlib.sha256(artifact).hexdigest()

    with pytest.raises(PagesDeploymentError, match="path traversal"):
        pages_deployment._manifest_from_pages_artifact_archive(artifact, expected_digest=digest)


def test_pages_artifact_tar_rejects_link_members():
    tar_stream = BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as packed:
        link = tarfile.TarInfo("data/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../outside"
        packed.addfile(link)
        info = tarfile.TarInfo("data/release-manifest.json")
        raw = MANIFEST_PATH.read_bytes()
        info.size = len(raw)
        packed.addfile(info, BytesIO(raw))
    archive_stream = BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("artifact.tar", tar_stream.getvalue())
    artifact = archive_stream.getvalue()
    digest = "sha256:" + hashlib.sha256(artifact).hexdigest()

    with pytest.raises(PagesDeploymentError, match="unsupported file type"):
        pages_deployment._manifest_from_pages_artifact_archive(artifact, expected_digest=digest)


def test_pages_artifact_tar_enforces_aggregate_formal_payload_budget(monkeypatch):
    monkeypatch.setattr(pages_deployment, "DEFAULT_MAX_BYTES", 1000)
    raw_manifest = json.dumps({"release_id": "r", "market_snapshot_id": "s"}).encode()
    tar_stream = BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as packed:
        for name, body in (
            ("data/release-manifest.json", raw_manifest),
            ("data/large-a.bin", b"a" * 600),
            ("data/large-b.bin", b"b" * 600),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            packed.addfile(info, BytesIO(body))
    artifact_stream = BytesIO()
    with zipfile.ZipFile(artifact_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("artifact.tar", tar_stream.getvalue())
    artifact = artifact_stream.getvalue()

    with pytest.raises(PagesDeploymentError, match="contents exceed the verification size budget"):
        pages_deployment._manifest_from_pages_artifact_archive(
            artifact, expected_digest="sha256:" + hashlib.sha256(artifact).hexdigest(),
        )


def test_pages_artifact_zip_rejects_extra_entries(monkeypatch):
    artifact = _pages_artifact_archive(MANIFEST_PATH.read_bytes())
    extra = BytesIO()
    with zipfile.ZipFile(BytesIO(artifact)) as original, zipfile.ZipFile(extra, "w") as packed:
        for item in original.infolist():
            packed.writestr(item.filename, original.read(item.filename))
        packed.writestr("unexpected.txt", "not part of the Pages artifact")

    with pytest.raises(PagesDeploymentError, match="exactly one artifact.tar"):
        pages_deployment._manifest_from_pages_artifact_archive(extra.getvalue(), expected_digest="sha256:" + hashlib.sha256(extra.getvalue()).hexdigest())


def test_create_rejects_artifact_listing_that_differs_from_upload_output_before_download():
    requested = []

    def request_json(url, **_kwargs):
        requested.append(url)
        return {"artifacts": [{
            "id": 202, "name": "github-pages", "expired": False,
            "digest": ARTIFACT_DIGEST,
            "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION},
        }]}

    with pytest.raises(PagesDeploymentError, match="differs from the upload step output"):
        create_deployment(
            api_url="https://api.github.test", repository="owner/repo", token="token",
            run_id="17", artifact_name="github-pages", source_revision=SOURCE_REVISION,
            expected_artifact_id="203",
            oidc_request_url="https://oidc.actions.test/token", oidc_request_token="request-token",
            request_json=request_json,
        )
    assert len(requested) == 1
    assert "actions/runs/17/artifacts" in requested[0]


def test_create_download_exhaustion_never_starts_pages_deployment(monkeypatch):
    requests = []

    def request_json(url, **_kwargs):
        requests.append(url)
        return {"artifacts": [{
            "id": 202, "name": "github-pages", "expired": False,
            "digest": ARTIFACT_DIGEST,
            "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION},
        }]}

    def unavailable(request, *, timeout):
        raise HTTPError(request.full_url, 404, "not ready", {}, BytesIO())

    monkeypatch.setattr(pages_deployment, "_open_artifact_url", unavailable)
    monkeypatch.setattr(pages_deployment, "_download_pages_artifact_manifest", _REAL_ARTIFACT_DOWNLOADER)
    with pytest.raises(PagesDeploymentError) as captured:
        create_deployment(
            api_url="https://api.github.test", repository="owner/repo", token="token",
            run_id="17", artifact_name="github-pages", source_revision=SOURCE_REVISION,
            expected_artifact_id="202",
            oidc_request_url="https://oidc.actions.test/token", oidc_request_token="request-token",
            request_json=request_json, sleeper=lambda _delay: None, monotonic=lambda: 0.0,
        )

    assert captured.value.error_code == "pages_artifact_download_http_404"
    assert captured.value.artifact_id == "202"
    assert captured.value.artifact_read_attempts == 3
    assert captured.value.request_outcome == "not_started"
    assert len(requests) == 1
    assert "actions/runs/17/artifacts" in requests[0]
    assert not any(url.endswith("/pages/deployments") for url in requests)


def test_create_rechecks_original_deadline_after_oidc_before_pages_post(monkeypatch):
    requests = []
    observed_times = iter([100.0, 200.0])

    def request_json(url, **_kwargs):
        requests.append(url)
        if "actions/runs/17/artifacts" in url:
            return {"artifacts": [{
                "id": 202, "name": "github-pages", "expired": False,
                "digest": ARTIFACT_DIGEST,
                "workflow_run": {"id": 17, "head_sha": SOURCE_REVISION},
            }]}
        if "oidc.actions.test" in url:
            return {"value": "oidc"}
        raise AssertionError(url)

    monkeypatch.setattr(
        pages_deployment, "_download_pages_artifact_manifest",
        lambda **_kwargs: MANIFEST_PATH.read_bytes(),
    )
    monkeypatch.setattr(pages_deployment, "_read_manifest_identity", lambda _path: (MANIFEST, MANIFEST_SHA256))
    with pytest.raises(PagesDeploymentError) as captured:
        create_deployment(
            api_url="https://api.github.test", repository="owner/repo", token="token",
            run_id="17", artifact_name="github-pages", source_revision=SOURCE_REVISION,
            expected_artifact_id="202", artifact_read_deadline_epoch=150,
            oidc_request_url="https://oidc.actions.test/token", oidc_request_token="request-token",
            request_json=request_json, wall_clock=lambda: next(observed_times),
        )

    assert captured.value.error_code == "pages_artifact_download_deadline_exhausted"
    assert captured.value.request_outcome == "not_started"
    assert requests == [
        "https://api.github.test/repos/owner/repo/actions/runs/17/artifacts?per_page=100&page=1",
        "https://oidc.actions.test/token",
    ]


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
    assert derive_build_version(**base) == SOURCE_REVISION
    assert derive_build_version(**{**base, "release_id": "release-two"}) == SOURCE_REVISION
    binding = derive_release_binding_id(**base)
    assert binding.startswith("prstk-v1-")
    assert binding != derive_release_binding_id(**{**base, "source_revision": "b" * 40})
    assert binding != derive_release_binding_id(**{**base, "release_id": "release-two"})
    assert binding != derive_release_binding_id(**{**base, "artifact_digest": "sha256:" + "d" * 64})
    assert binding != derive_release_binding_id(**{**base, "phase": "receipt_reconciliation"})


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
            build_version="b" * 40, oidc_request_url="https://oidc.actions.test/token",
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
            manifest_sha256=MANIFEST_SHA256,
            artifact_manifest_sha256=MANIFEST_SHA256,
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
    assert "artifact_manifest_match_status=verified_match" in result


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
        raise HTTPError(
            "https://api.github.test/pages/deployments", 400, "Bad Request",
            {"X-GitHub-Request-Id": "REQ12345"}, BytesIO(body),
        )

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
    assert error.request_id == "REQ12345"
    assert "Invalid audience" in str(error)
    assert "PagesDeployment/oidc_token/invalid" in str(error)
    assert "secret-token" not in str(error)
    assert "[url]" in str(error)


def test_pages_site_preflight_reads_configuration_without_mutation():
    calls = []

    def request_json(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "status": "built",
            "build_type": "workflow",
            "html_url": "https://owner.github.io/project/",
            "source": {"branch": "main", "path": "/"},
        }

    result = pages_deployment.inspect_pages_site(
        api_url="https://api.github.test",
        repository="owner/repo",
        token="read-write-token",
        request_json=request_json,
    )

    assert calls == [(
        "https://api.github.test/repos/owner/repo/pages",
        {"token": "read-write-token", "timeout": 15.0},
    )]
    assert result == {
        "preflight_passed": True,
        "preflight_http_status": "200",
        "pages_status": "built",
        "pages_build_type": "workflow",
        "pages_source_branch": "main",
        "pages_source_path": "/",
        "pages_html_url": "https://owner.github.io/project/",
    }


def test_pages_site_preflight_cli_records_not_found_without_guessing_cause(tmp_path, monkeypatch):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        pages_deployment,
        "inspect_pages_site",
        lambda **_kwargs: (_ for _ in ()).throw(PagesDeploymentError(
            "GitHub Pages request returned HTTP 404",
            error_code="pages_http_404",
            request_outcome="rejected",
        )),
    )
    monkeypatch.setattr("sys.argv", ["pages_deployment", "--mode", "preflight"])

    assert pages_deployment.main() == 1
    text = output.read_text(encoding="utf-8")
    assert "preflight_passed=false" in text
    assert "preflight_http_status=404" in text
    assert "preflight_error_code=pages_http_404" in text
    assert "pages_build_type=unknown" in text


@pytest.mark.parametrize(
    ("frozen", "downloaded", "expected"),
    [
        (MANIFEST_SHA256, MANIFEST_SHA256, "verified_match"),
        (MANIFEST_SHA256, "0" * 64, "verified_mismatch"),
        ("", MANIFEST_SHA256, "not_checked"),
    ],
)
def test_artifact_manifest_match_status_is_tristate(frozen, downloaded, expected):
    assert pages_deployment._manifest_match_status(frozen, downloaded) == expected


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
    assert captured.value.manifest_sha256 == MANIFEST_SHA256
    assert captured.value.artifact_manifest_sha256 == MANIFEST_SHA256
    assert pages_deployment._manifest_match_status(
        captured.value.manifest_sha256, captured.value.artifact_manifest_sha256,
    ) == "verified_match"
    assert len(creates) == 1
