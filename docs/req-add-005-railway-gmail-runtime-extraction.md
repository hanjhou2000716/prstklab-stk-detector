# REQ-ADD-005 — Railway Gmail runtime extraction

## Scope

This bounded architecture slice extracts Gmail ingress construction from
`railway-monitor/app.py` into `railway-monitor/gmail_runtime.py`.  The module
only wires the existing `GmailWatchConfig`, `EmailStore` and
`GmailIngressService`; parsing, authentication, routing and persistence
remain in their canonical modules.

The factory accepts injected constructors for offline contract tests and
returns a redacted health projection.  Missing configuration and constructor
failures remain explicit states; no Gmail transport identifiers or message
content enters the health response.

## Verification

- `tests/test_railway_gmail_runtime.py` covers configured, missing and failed
  construction without credentials.
- `tests/test_railway_monitor.py` preserves the legacy `app.py` health and
  standalone-import behavior.
- Targeted result: 92 passed.
- Ruff and standalone Mypy pass; `python -m compileall -q railway-monitor`
  passes.

## Rollback

Revert this atomic extraction commit.  The app-level `configure_gmail_ingress`
entry point remains intact, so no data migration is needed.

## Remaining work

Email routing, persistence, dispatch and poll-loop extraction remain separate
tasks.  Live Gmail OAuth/PubSub and Railway delivery evidence are external
acceptance gates.

