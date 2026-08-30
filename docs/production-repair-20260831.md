# PRStK Targeted Production Repair — 2026-08-31

This evidence record is tied to the baseline `main` commit
`59755f2ae4c38b8b0aff24de29248385bc716bda` and the `data-release` commit
`94e05c0b542518173f37f152bdf2c3531ef57db7`.

## Production baseline

| Check | Observed value |
|---|---|
| Public release | `release-d86729fd2824588` |
| Market snapshot | `493fe705d8e27810` |
| Research snapshot | `research-8b8ec8f6e5ee51aa` |
| News snapshot | `news-ced79fddf95ba1f7` |
| Event snapshot | `event-2668aef41e66e57b` |
| Public manifest | `status=ready`, validation errors empty |
| Worker health | HTTP 200, API/database/receipt backend healthy |
| Legacy Railway | HTTP 404; retained as optional rollback only |

The checked-in `site/data/release-manifest.json` on the baseline main commit
was an older invalid artifact. Production verification therefore uses the
public, release-gated artifact above rather than treating the main checkout's
stale data tree as production truth.

## Targeted evidence

### TASK-01 — Taiwan VIX validity

The live TAIFEX MIS response on 2026-08-31 returned `CLastPrice=0.00`,
`CRefPrice=24.99`, and a pre-open timestamp. The repaired parser rejects zero
as a live observation and returns the positive reference as
`freshness_state=recent_reference`, `value_status=recent_reference`, and
`change_percent=null`. No `-100%` movement or fabricated intraday state is
produced. Invalid live and reference values return unavailable.

### TASK-02 — Taiwan Value and compact cards

The latest-main full scan was executed with the official universe and share
adapters. This run recorded external source failures (Yuanta constituent
endpoints and TPEx/TWSE requests in the execution environment), so it
returned `scan_state=failed`, `candidate_state=data_unavailable`, and
`source_failure_count=17`; no Yahoo denominator fallback was added. The UI
projection now renders one `璞玉價值` label and score while retaining
`value_checks` in the JSON for audit.

### TASK-03 — News candidate funnel

The combined provider pool is no longer globally truncated before ranking.
Provider observability now records `fetched_count`, `normalized_count`,
`market_compatible_count`, `eligible_count`, `excluded_count`,
`deduped_count`, and `ranked_count`, so a healthy source's path to (or reason
for exclusion from) the five-item market list is auditable. Generic SEC filings
remain excluded unless contextual relevance is present.

### TASK-04 — Telegram canonical text

All non-Creator send paths use the canonical short-message boundary before
`sendMessage`. It emits one risk token with a severity icon, preserves an
FinancialJuice vendor score separately from the PRStK risk grade, and bounds
output at 30 characters without cutting a ``｜`` segment. Creator verified
original attachments remain the only photo exception.

## Verification run

- Targeted risk, news, Mini App, and Telegram tests: 93 passed.
- Ruff on changed files: passed.
- Mypy on changed modules: passed.
- JavaScript syntax check: passed.

Full repository regression and post-merge production acceptance remain
required before this record can be marked complete.
