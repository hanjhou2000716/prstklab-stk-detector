import json

import pytest

from src.workflow_run_context import fetch_created_at


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"created_at": "2026-09-26T00:23:53Z"}).encode()


def test_fetch_created_at_returns_timezone_aware_run_creation_time():
    request_values = {}

    def opener(request, timeout):
        request_values["url"] = request.full_url
        request_values["auth"] = request.get_header("Authorization")
        request_values["timeout"] = timeout
        return Response()

    result = fetch_created_at("owner/repo", "12345", "secret-token", opener=opener)
    assert result == "2026-09-26T00:23:53+00:00"
    assert request_values == {
        "url": "https://api.github.com/repos/owner/repo/actions/runs/12345",
        "auth": "Bearer secret-token",
        "timeout": 10,
    }


@pytest.mark.parametrize(("repo", "run_id", "token"), [
    ("owner/repo/extra", "123", "token"),
    ("owner/repo", "not-a-run", "token"),
    ("owner/repo", "123", ""),
])
def test_run_metadata_rejects_invalid_identity_before_network(repo, run_id, token):
    with pytest.raises(ValueError, match="workflow_run_identity_invalid"):
        fetch_created_at(repo, run_id, token, opener=lambda *_args, **_kwargs: pytest.fail("network must not run"))
