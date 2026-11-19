from __future__ import annotations

import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from src.github_issue_api import (
    IssuePaginationError,
    read_issues_by_identity,
    read_open_issues,
    read_open_issues_by_title_prefixes,
)


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


def _search_row(number, *, title="filler issue", body="", state="closed"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "url": f"https://api.github.com/repos/owner/repo/issues/{number}",
        "repository_url": "https://api.github.com/repos/owner/repo",
    }


def test_identity_search_is_repo_scoped_complete_and_finds_exact_control_issue():
    marker = "incident-notification-control=incident-notification-journal-v1"
    issue = _search_row(1143, title="PRStK incident notification control", body=f"{marker}\n{{}}", state="open")
    queries = []

    def fetch(_api, _repo, token, method, url, *, response_headers=None, deadline_monotonic=None):
        assert token == "token" and method == "GET"
        parsed = urlsplit(url)
        assert parsed.path == "/search/issues"
        query = parse_qs(parsed.query)
        queries.append(query["q"][0])
        response_headers["link"] = ""
        return {"total_count": 1, "incomplete_results": False, "items": [issue]}

    rows = read_issues_by_identity(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        fetch_json=fetch, deadline_monotonic=time.monotonic() + 10,
        title="PRStK incident notification control", marker=marker,
    )
    assert rows == [issue]
    assert queries == [
        'repo:owner/repo is:issue ("PRStK incident notification control" in:title OR '
        '"incident-notification-control=incident-notification-journal-v1" in:body)'
    ]


def test_identity_search_paginates_and_checks_exact_coverage():
    marker = "incident-notification-control=incident-notification-journal-v1"
    title = "PRStK incident notification control"
    rows = [_search_row(n) for n in range(1, 101)]
    rows.append(_search_row(101, title=title, body=marker, state="open"))
    calls = []

    def fetch(_api, _repo, _token, method, url, *, response_headers=None, deadline_monotonic=None):
        assert method == "GET"
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        calls.append((query["q"][0], int(query["page"][0])))
        page = int(query["page"][0])
        if page == 1:
            next_query = urlencode({"q": query["q"][0], "per_page": 100, "page": 2})
            response_headers["link"] = f'<https://api.github.com/search/issues?{next_query}>; rel="next"'
            return {"total_count": 101, "incomplete_results": False, "items": rows[:100]}
        response_headers["link"] = ""
        return {"total_count": 101, "incomplete_results": False, "items": rows[100:]}

    found = read_issues_by_identity(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        fetch_json=fetch, deadline_monotonic=time.monotonic() + 10, title=title, marker=marker,
    )
    assert [row["number"] for row in found] == [101]
    assert len(calls) == 2
    assert [page for _query, page in calls] == [1, 2]


def test_identity_search_rejects_incomplete_results_and_cross_repository_rows():
    marker = "incident-notification-control=incident-notification-journal-v1"
    valid = _search_row(1143, title="PRStK incident notification control", body=marker, state="open")

    def incomplete(_api, _repo, _token, _method, _url, *, response_headers=None, **_kwargs):
        response_headers["link"] = ""
        return {"total_count": 1, "incomplete_results": True, "items": [valid]}

    with pytest.raises(IssuePaginationError, match="response_incomplete"):
        read_issues_by_identity(
            api_url="https://api.github.com", repository="owner/repo", token="token",
            fetch_json=incomplete, deadline_monotonic=time.monotonic() + 10,
            title="PRStK incident notification control", marker=marker,
        )

    cross_repo = {**valid, "repository_url": "https://api.github.com/repos/other/repo"}
    def wrong_repo(_api, _repo, _token, _method, _url, *, response_headers=None, **_kwargs):
        response_headers["link"] = ""
        return {"total_count": 1, "incomplete_results": False, "items": [cross_repo]}

    with pytest.raises(IssuePaginationError, match="row_identity_invalid"):
        read_issues_by_identity(
            api_url="https://api.github.com", repository="owner/repo", token="token",
            fetch_json=wrong_repo, deadline_monotonic=time.monotonic() + 10,
            title="PRStK incident notification control", marker=marker,
        )


def test_open_issue_title_prefix_search_is_scoped_and_filters_exact_prefixes():
    prefixes = ("Official event monitor stalled", "Official event delivery degraded")
    expected_query = (
        "repo:owner/repo is:issue is:open "
        '("Official event monitor stalled" in:title OR '
        '"Official event delivery degraded" in:title)'
    )
    items = [
        _search_row(8, title="Official event delivery degraded / main", state="open"),
        _search_row(9, title="Official event monitor stalled / main", state="open"),
        _search_row(10, title="Older note: Official event monitor stalled", state="open"),
        _search_row(11, title="Official event monitor stalled / closed", state="closed"),
    ]
    observed_queries = []

    def fetch(_api, _repo, _token, method, url, *, response_headers=None, deadline_monotonic=None):
        assert method == "GET"
        query = parse_qs(urlsplit(url).query)
        observed_queries.append(query["q"][0])
        response_headers["link"] = ""
        return {"total_count": len(items), "incomplete_results": False, "items": items}

    rows = read_open_issues_by_title_prefixes(
        api_url="https://api.github.com",
        repository="owner/repo",
        token="token",
        fetch_json=fetch,
        deadline_monotonic=time.monotonic() + 10,
        title_prefixes=prefixes,
    )

    assert [row["number"] for row in rows] == [8, 9]
    assert observed_queries == [expected_query]


def test_open_issue_title_prefix_search_paginates_complete_results():
    prefixes = ("Official event monitor stalled",)
    rows = [
        _search_row(n, title="Official event monitor stalled / main", state="open")
        for n in range(1, 102)
    ]
    pages = []

    def fetch(_api, _repo, _token, method, url, *, response_headers=None, deadline_monotonic=None):
        assert method == "GET"
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        page = int(query["page"][0])
        pages.append(page)
        if page == 1:
            response_headers["link"] = (
                "<https://api.github.com/search/issues?"
                + urlencode({"q": query["q"][0], "per_page": 100, "page": 2})
                + '>; rel="next"'
            )
            return {"total_count": 101, "incomplete_results": False, "items": rows[:100]}
        response_headers["link"] = ""
        return {"total_count": 101, "incomplete_results": False, "items": rows[100:]}

    found = read_open_issues_by_title_prefixes(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        fetch_json=fetch, deadline_monotonic=time.monotonic() + 10, title_prefixes=prefixes,
    )
    assert [row["number"] for row in found] == list(range(1, 102))
    assert pages == [1, 2]
