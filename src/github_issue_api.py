"""Bounded, identity-checked pagination for repository incident issues."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

PAGE_SIZE = 10
MAX_PAGES = 10
MAX_RESPONSE_BYTES = 1_000_000


class IssuePaginationError(RuntimeError):
    """Issue pagination could not be proven complete and repository-local."""


def _next_url(
    link_header: str,
    *,
    api_url: str,
    repository: str,
    repository_id: int | None,
    expected_query: Mapping[str, list[str]],
    expected_page: int,
    page_size: int = PAGE_SIZE,
) -> str | None:
    entries = re.findall(r"<([^<>]+)>\s*;\s*rel=\"([^\"]+)\"", link_header)
    next_urls = [url for url, relation in entries if "next" in relation.split()]
    if len(next_urls) > 1:
        raise IssuePaginationError("issues_pagination_link_ambiguous")
    if not next_urls:
        return None
    url = next_urls[0]
    parsed = urlsplit(url)
    api = urlsplit(api_url)
    name_path = f"{api.path.rstrip('/')}/repos/{repository}/issues"
    id_path = (
        f"{api.path.rstrip('/')}/repositories/{repository_id}/issues"
        if repository_id is not None else ""
    )
    if (
        parsed.scheme.casefold() != "https"
        or parsed.netloc.casefold() != api.netloc.casefold()
        or parsed.path not in {name_path, id_path}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise IssuePaginationError("issues_pagination_identity_invalid")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    expected = {key: list(values) for key, values in expected_query.items()}
    expected["per_page"] = [str(page_size)]
    if "after" in query:
        cursor = query["after"]
        if len(cursor) != 1 or not cursor[0] or len(cursor[0]) > 2048:
            raise IssuePaginationError("issues_pagination_cursor_invalid")
        expected["after"] = cursor
        if "page" in query:
            if query["page"] != [str(expected_page)]:
                raise IssuePaginationError("issues_pagination_query_invalid")
            expected["page"] = [str(expected_page)]
    else:
        expected["page"] = [str(expected_page)]
    if query != expected:
        raise IssuePaginationError("issues_pagination_query_invalid")
    return url


def read_open_issues(
    *,
    api_url: str,
    repository: str,
    token: str,
    fetch_json: Callable[..., Any],
    deadline_monotonic: float,
    repository_id: int | None = None,
    state: str = "open",
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
) -> list[dict[str, Any]]:
    """Read all issues under one deadline, bounded pages, and 1MB responses.

    ``fetch_json`` receives a full HTTPS URL and the same response-header and
    deadline arguments used by the repository's authenticated API reader.
    GitHub may switch between the owner/name route and its numeric repository
    route in Link headers. Numeric routes are accepted only after their ID is
    independently resolved from ``GET /repos/{owner}/{repo}``.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise IssuePaginationError("issues_repository_identity_invalid")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise IssuePaginationError("issues_page_size_invalid")
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise IssuePaginationError("issues_page_limit_invalid")
    if state not in {"open", "all"}:
        raise IssuePaginationError("issues_state_filter_invalid")
    api = urlsplit(api_url)
    if api.scheme.casefold() != "https" or not api.netloc:
        raise IssuePaginationError("issues_api_origin_invalid")
    filters = {"state": [state], "sort": ["created"], "direction": ["desc"]}
    query = {**{key: value[0] for key, value in filters.items()}, "per_page": page_size, "page": 1}
    current_url = f"issues?{urlencode(query)}"
    requested: set[str] = set()
    rows_by_number: dict[int, dict[str, Any]] = {}
    page = 1
    while page <= max_pages:
        if time.monotonic() >= deadline_monotonic:
            raise IssuePaginationError("issues_pagination_deadline_exceeded")
        if current_url in requested:
            raise IssuePaginationError("issues_pagination_link_cycle")
        requested.add(current_url)
        headers: dict[str, str] = {}
        payload = fetch_json(
            api_url, repository, token, "GET", current_url,
            response_headers=headers, deadline_monotonic=deadline_monotonic,
        )
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise IssuePaginationError("issues_pagination_response_invalid")
        for row in payload:
            number = row.get("number")
            if not isinstance(number, int) or number <= 0:
                raise IssuePaginationError("issues_pagination_row_identity_invalid")
            previous = rows_by_number.get(number)
            if previous is not None and previous != row:
                raise IssuePaginationError("issues_pagination_duplicate_row_changed")
            rows_by_number[number] = row

        link_header = headers.get("link", "")
        if repository_id is None and "/repositories/" in link_header:
            if time.monotonic() >= deadline_monotonic:
                raise IssuePaginationError("issues_pagination_deadline_exceeded")
            metadata = fetch_json(
                api_url, repository, token, "GET",
                f"{api_url.rstrip('/')}/repos/{repository}",
                deadline_monotonic=deadline_monotonic,
            )
            resolved_id = metadata.get("id") if isinstance(metadata, Mapping) else None
            if not isinstance(resolved_id, int) or resolved_id <= 0:
                raise IssuePaginationError("issues_repository_id_unverified")
            repository_id = resolved_id
        next_page = _next_url(
            link_header, api_url=api_url, repository=repository,
            repository_id=repository_id, expected_query=filters, expected_page=page + 1,
            page_size=page_size,
        )
        if next_page is not None:
            if page == max_pages:
                raise IssuePaginationError("issues_pagination_limit_exceeded")
            current_url = next_page
            page += 1
            continue
        if len(payload) < page_size:
            return list(rows_by_number.values())

        # A full page without Link is ambiguous. Probe one forward page with
        # canonical offset pagination; a short/empty page proves the end.
        page += 1
        if page > max_pages:
            raise IssuePaginationError("issues_pagination_coverage_incomplete")
        query = {
            **{key: value[0] for key, value in filters.items()},
            "per_page": page_size,
            "page": page,
        }
        current_url = f"issues?{urlencode(query)}"
    raise IssuePaginationError("issues_pagination_limit_exceeded")


ISSUE_SEARCH_PAGE_SIZE = 100
MAX_ISSUE_SEARCH_PAGES = 10


def _issue_search_next_url(
    link_header: str,
    *,
    api_url: str,
    query_text: str,
    expected_page: int,
) -> str | None:
    entries = re.findall(r'<([^<>]+)>\s*;\s*rel="([^"]+)"', link_header)
    next_urls = [url for url, relation in entries if "next" in relation.split()]
    if len(next_urls) > 1:
        raise IssuePaginationError("issue_search_pagination_link_ambiguous")
    if not next_urls:
        return None
    url = next_urls[0]
    parsed = urlsplit(url)
    api = urlsplit(api_url)
    expected_path = f"{api.path.rstrip('/')}/search/issues"
    if (
        parsed.scheme.casefold() != "https"
        or parsed.netloc.casefold() != api.netloc.casefold()
        or parsed.path.casefold() != expected_path.casefold()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise IssuePaginationError("issue_search_pagination_identity_invalid")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    expected = {
        "q": [query_text],
        "per_page": [str(ISSUE_SEARCH_PAGE_SIZE)],
        "page": [str(expected_page)],
    }
    if query != expected:
        raise IssuePaginationError("issue_search_pagination_query_invalid")
    return url


def _read_issue_search(
    *,
    api_url: str,
    repository: str,
    token: str,
    fetch_json: Callable[..., Any],
    deadline_monotonic: float,
    query_text: str,
) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise IssuePaginationError("issues_repository_identity_invalid")
    if not isinstance(query_text, str) or not query_text or len(query_text) > 500:
        raise IssuePaginationError("issue_search_query_invalid")
    api = urlsplit(api_url)
    if (
        api.scheme.casefold() != "https"
        or not api.netloc
        or api.username is not None
        or api.password is not None
        or api.query
        or api.fragment
    ):
        raise IssuePaginationError("issue_search_api_origin_invalid")
    page = 1
    query_params = {
        "q": query_text,
        "per_page": ISSUE_SEARCH_PAGE_SIZE,
        "page": page,
    }
    current_url = f"{api_url.rstrip('/')}/search/issues?{urlencode(query_params)}"
    requested: set[str] = set()
    rows_by_number: dict[int, dict[str, Any]] = {}
    expected_repository_url = f"{api.scheme}://{api.netloc}{api.path.rstrip('/')}/repos/{repository}".casefold()
    expected_repository_path = f"{api.path.rstrip('/')}/repos/{repository}".casefold()
    while page <= MAX_ISSUE_SEARCH_PAGES:
        if time.monotonic() >= deadline_monotonic:
            raise IssuePaginationError("issue_search_pagination_deadline_exceeded")
        if current_url in requested:
            raise IssuePaginationError("issue_search_pagination_link_cycle")
        requested.add(current_url)
        headers: dict[str, str] = {}
        payload = fetch_json(
            api_url, repository, token, "GET", current_url,
            response_headers=headers, deadline_monotonic=deadline_monotonic,
        )
        if (
            not isinstance(payload, Mapping)
            or type(payload.get("total_count")) is not int
            or payload["total_count"] < 0
            or payload.get("incomplete_results") is not False
            or not isinstance(payload.get("items"), list)
            or any(not isinstance(row, dict) for row in payload["items"])
            or len(payload["items"]) > ISSUE_SEARCH_PAGE_SIZE
        ):
            raise IssuePaginationError("issue_search_response_incomplete")
        total_count = payload["total_count"]
        items = payload["items"]
        if total_count > ISSUE_SEARCH_PAGE_SIZE * MAX_ISSUE_SEARCH_PAGES:
            raise IssuePaginationError("issue_search_result_limit_exceeded")
        for row in items:
            number = row.get("number")
            if type(number) is not int or number <= 0:
                raise IssuePaginationError("issue_search_row_identity_invalid")
            repository_url = urlsplit(str(row.get("repository_url") or ""))
            issue_url = urlsplit(str(row.get("url") or ""))
            expected_issue_path = f"{expected_repository_path}/issues/{number}"
            if (
                f"{repository_url.scheme}://{repository_url.netloc}{repository_url.path}".casefold()
                != expected_repository_url
                or repository_url.scheme.casefold() != "https"
                or repository_url.netloc.casefold() != api.netloc.casefold()
                or repository_url.query
                or repository_url.fragment
                or issue_url.scheme.casefold() != "https"
                or issue_url.netloc.casefold() != api.netloc.casefold()
                or issue_url.path.casefold() != expected_issue_path
                or issue_url.username is not None
                or issue_url.password is not None
                or issue_url.query
                or issue_url.fragment
                or "pull_request" in row
                or not isinstance(row.get("title"), str)
                or row.get("state") not in {"open", "closed"}
                or (row.get("body") is not None and not isinstance(row.get("body"), str))
            ):
                raise IssuePaginationError("issue_search_row_identity_invalid")
            if number in rows_by_number:
                raise IssuePaginationError("issue_search_duplicate_row")
            rows_by_number[number] = row

        next_url = _issue_search_next_url(
            headers.get("link", ""), api_url=api_url,
            query_text=query_text, expected_page=page + 1,
        )
        if next_url is not None:
            if page == MAX_ISSUE_SEARCH_PAGES:
                raise IssuePaginationError("issue_search_pagination_limit_exceeded")
            if len(rows_by_number) >= total_count:
                raise IssuePaginationError("issue_search_pagination_coverage_mismatch")
            current_url = next_url
            page += 1
            continue
        if len(rows_by_number) != total_count:
            raise IssuePaginationError("issue_search_pagination_coverage_incomplete")
        return list(rows_by_number.values())
    raise IssuePaginationError("issue_search_pagination_limit_exceeded")

def read_open_issues_by_title_prefixes(
    *,
    api_url: str,
    repository: str,
    token: str,
    fetch_json: Callable[..., Any],
    deadline_monotonic: float,
    title_prefixes: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Find open repository issues by a bounded set of known title prefixes.

    The search is scoped to known operational issue families so callers do not
    paginate the repository's full historical issue collection.
    """
    phrase_pattern = r"[A-Za-z0-9][A-Za-z0-9 _=:-]{0,199}"
    if (
        not isinstance(title_prefixes, tuple)
        or not 1 <= len(title_prefixes) <= 12
        or any(
            not isinstance(prefix, str)
            or not re.fullmatch(phrase_pattern, prefix)
            for prefix in title_prefixes
        )
        or len(set(title_prefixes)) != len(title_prefixes)
    ):
        raise IssuePaginationError("issue_search_title_prefixes_invalid")
    clauses = " OR ".join(f'"{prefix}" in:title' for prefix in title_prefixes)
    query_text = f"repo:{repository} is:issue is:open ({clauses})"
    rows = _read_issue_search(
        api_url=api_url, repository=repository, token=token,
        fetch_json=fetch_json, deadline_monotonic=deadline_monotonic,
        query_text=query_text,
    )
    folded_prefixes = tuple(prefix.casefold() for prefix in title_prefixes)
    return sorted(
        (
            row for row in rows
            if row.get("state") == "open"
            and str(row.get("title") or "").casefold().startswith(folded_prefixes)
        ),
        key=lambda row: row["number"],
    )


def read_issues_by_identity(
    *,
    api_url: str,
    repository: str,
    token: str,
    fetch_json: Callable[..., Any],
    deadline_monotonic: float,
    title: str,
    marker: str,
) -> list[dict[str, Any]]:
    """Find all issues matching either the exact control title or body marker.

    One narrowly-scoped, complete GitHub Search API scan replaces an unbounded
    walk of every historical issue and pull request. Any incomplete,
    cross-repository, or inconsistent search fails closed before journal
    mutation.
    """
    phrase_pattern = r"[A-Za-z0-9][A-Za-z0-9 _=:-]{0,199}"
    if not isinstance(title, str) or not re.fullmatch(phrase_pattern, title):
        raise IssuePaginationError("issue_search_title_invalid")
    if not isinstance(marker, str) or not re.fullmatch(phrase_pattern, marker):
        raise IssuePaginationError("issue_search_marker_invalid")
    query_text = (
        f'repo:{repository} is:issue '
        f'("{title}" in:title OR "{marker}" in:body)'
    )
    rows = _read_issue_search(
        api_url=api_url, repository=repository, token=token,
        fetch_json=fetch_json, deadline_monotonic=deadline_monotonic,
        query_text=query_text,
    )
    return sorted(
        (
            row for row in rows
            if row.get("title") == title or marker in str(row.get("body") or "").splitlines()
        ),
        key=lambda row: row["number"],
    )
