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
                "state=open&per_page=10&sort=created&direction=desc&after=opaque.cursor%2Fv1>; rel=\"next\""
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


def test_large_history_reads_every_page_and_probes_full_last_page():
    calls = []

    def fetch(_api, _repo, _token, method, url, *, response_headers=None, deadline_monotonic=None):
        assert method == "GET"
        query = parse_qs(urlsplit(url).query)
        assert query["state"] == ["all"]
        assert query["per_page"] == ["100"]
        page = int(query["page"][0])
        calls.append(page)
        return [{"number": number} for number in range((page - 1) * 100 + 1, min(page * 100, 1200) + 1)]

    rows = read_open_issues(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        fetch_json=fetch, deadline_monotonic=time.monotonic() + 10,
        state="all", page_size=100, max_pages=100,
    )
    assert len(rows) == 1200
    assert calls == list(range(1, 14))


def test_custom_page_size_rejects_link_page_size_drift():
    def fetch(_api, _repo, _token, _method, _url, *, response_headers=None, deadline_monotonic=None):
        response_headers["link"] = (
            "<https://api.github.com/repos/owner/repo/issues?state=all&per_page=10"
            "&sort=created&direction=desc&page=2>; rel=\"next\""
        )
        return [{"number": 1}]

    with pytest.raises(IssuePaginationError, match="query_invalid"):
        read_open_issues(
            api_url="https://api.github.com", repository="owner/repo", token="token",
            fetch_json=fetch, deadline_monotonic=time.monotonic() + 10,
            state="all", page_size=100, max_pages=100,
        )


@pytest.mark.parametrize(("page_size", "max_pages"), [(0, 10), (101, 10), (10, 0), (10, 101)])
def test_pagination_capacity_remains_bounded(page_size, max_pages):
    def fetch(*_args, **_kwargs):
        pytest.fail("invalid pagination bounds must stop before a request")

    with pytest.raises(IssuePaginationError, match="issues_page_(size|limit)_invalid"):
        read_open_issues(
            api_url="https://api.github.com", repository="owner/repo", token="token",
            fetch_json=fetch, deadline_monotonic=time.monotonic() + 10,
            page_size=page_size, max_pages=max_pages,
        )
