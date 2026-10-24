from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import pytest

from src.github_issue_api import IssuePaginationError, read_open_issues


def test_reads_numeric_repository_link_and_opaque_cursor_after_verifying_id():
    calls: list[tuple[str, str]] = []
    first = [{"number": number, "title": f"issue {number}"} for number in range(10, 0, -1)]
    last = [{"number": 11, "title": "issue 11"}, {"number": 12, "title": "issue 12"}]

    def fetch(_api, _repo, token, method, url, *, response_headers=None, deadline_monotonic=None):
        assert token == "test-token"
        assert method == "GET"
        calls.append((url, token))
        if url.endswith("/repos/owner/repo"):
            return {"id": 1309835643}
        if url.startswith("issues?"):
            assert response_headers is not None
            response_headers["link"] = (
                "<https://api.github.com/repositories/1309835643/issues?"
                "state=open&per_page=10&sort=created&direction=desc&page=2&after=opaque.cursor%2Fv1>; rel=\"next\""
            )
            return first
        parsed = urlsplit(url)
        assert parsed.path == "/repositories/1309835643/issues"
        assert parse_qs(parsed.query)["after"] == ["opaque.cursor/v1"]
        return last

    rows = read_open_issues(
        api_url="https://api.github.com",
        repository="owner/repo",
        token="test-token",
        fetch_json=fetch,
        deadline_monotonic=time.monotonic() + 10,
    )
    assert [row["number"] for row in rows] == list(range(10, 0, -1)) + [11, 12]
    assert calls[1][0] == "https://api.github.com/repos/owner/repo"
    assert len(calls) == 3


def test_full_page_without_link_is_forward_probed_to_prove_completion():
    calls: list[str] = []

    def fetch(_api, _repo, _token, _method, url, *, response_headers=None, deadline_monotonic=None):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        return [{"number": number, "title": str(number)} for number in range(1, 11)] if page == 1 else []

    rows = read_open_issues(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        fetch_json=fetch, deadline_monotonic=time.monotonic() + 10, repository_id=1309835643,
    )
    assert len(rows) == 10
    assert len(calls) == 2
    assert parse_qs(urlsplit(calls[1]).query)["page"] == ["2"]


def test_numeric_repository_route_rejects_wrong_repository_id():
    def fetch(_api, _repo, _token, _method, url, *, response_headers=None, deadline_monotonic=None):
        if url.startswith("issues?"):
            response_headers["link"] = (
                "<https://api.github.com/repositories/999/issues?state=open&per_page=10"
                "&sort=created&direction=desc&page=2>; rel=\"next\""
            )
            return [{"number": n} for n in range(1, 11)]
        return {"id": 1309835643}

    with pytest.raises(IssuePaginationError, match="identity_invalid"):
        read_open_issues(
            api_url="https://api.github.com", repository="owner/repo", token="token",
            fetch_json=fetch, deadline_monotonic=time.monotonic() + 10,
        )


def test_link_filter_drift_is_rejected():
    def fetch(_api, _repo, _token, _method, url, *, response_headers=None, deadline_monotonic=None):
        response_headers["link"] = (
            "<https://api.github.com/repos/owner/repo/issues?state=closed&per_page=10"
            "&sort=created&direction=desc&page=2>; rel=\"next\""
        )
        return [{"number": n} for n in range(1, 11)]

    with pytest.raises(IssuePaginationError, match="query_invalid"):
        read_open_issues(
            api_url="https://api.github.com", repository="owner/repo", token="token",
            fetch_json=fetch, deadline_monotonic=time.monotonic() + 10, repository_id=1309835643,
        )
