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
    expected["per_page"] = [str(PAGE_SIZE)]
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
) -> list[dict[str, Any]]:
    """Read all open issues under a single deadline and a 10-page/1MB bound.

    ``fetch_json`` receives a full HTTPS URL and the same response-header and
    deadline arguments used by the repository's authenticated API reader.
    GitHub may switch between the owner/name route and its numeric repository
    route in Link headers. Numeric routes are accepted only after their ID is
    independently resolved from ``GET /repos/{owner}/{repo}``.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise IssuePaginationError("issues_repository_identity_invalid")
    api = urlsplit(api_url)
    if api.scheme.casefold() != "https" or not api.netloc:
        raise IssuePaginationError("issues_api_origin_invalid")
    filters = {"state": ["open"], "sort": ["created"], "direction": ["desc"]}
    query = {**{key: value[0] for key, value in filters.items()}, "per_page": PAGE_SIZE, "page": 1}
    current_url = f"issues?{urlencode(query)}"
    requested: set[str] = set()
    rows_by_number: dict[int, dict[str, Any]] = {}
    page = 1
    while page <= MAX_PAGES:
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
        )
        if next_page is not None:
            if page == MAX_PAGES:
                raise IssuePaginationError("issues_pagination_limit_exceeded")
            current_url = next_page
            page += 1
            continue
        if len(payload) < PAGE_SIZE:
            return list(rows_by_number.values())

        # A full page without Link is ambiguous. Probe one forward page with
        # canonical offset pagination; a short/empty page proves the end.
        page += 1
        if page > MAX_PAGES:
            raise IssuePaginationError("issues_pagination_coverage_incomplete")
        query = {
            **{key: value[0] for key, value in filters.items()},
            "per_page": PAGE_SIZE,
            "page": page,
        }
        current_url = f"issues?{urlencode(query)}"
    raise IssuePaginationError("issues_pagination_limit_exceeded")
