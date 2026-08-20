# 主線回歸與公開 Release 驗證（2026-08-20）

## Scope

這份紀錄補充 PR #642 的 post-merge evidence，針對 `main` 在 PR #641、#642
合併後的實際主線執行完整離線回歸與公開 Pages release smoke。這是驗證紀錄，
不代表尚未取得的外部憑證或正式 Telegram 收件證據已完成。

## Repository

- main HEAD：`f0b15b99809f1f03cfa26688c8713df47e50abd3`
- PR #641：canonical Railway external-parser bundle（已合併）
- PR #642：post-merge production evidence（已合併）

## Verification evidence

| Check | Result | Evidence |
|---|---|---|
| Full pytest + coverage | PASS | `1261 passed`; total coverage `81.06%` (floor 80%) |
| Ruff | PASS | `uv run --locked --all-groups ruff check src tests` |
| Mypy | PASS | `Success: no issues found in 167 source files` |
| Compile / JS syntax | PASS | `compileall -q src railway-monitor scripts`; `node --check site/app.js` |
| Runtime audit | PASS with explicit warnings | exit 0; local checkout lacks generated event/research snapshots |
| Telegram dry-run | PASS | one dummy recipient; no token/network delivery |
| Offline production E2E | PASS | fixed `1080×1350` card, mock Telegram contract, release/deep-link checks |
| External intelligence dry-run | PASS | sanitized FinancialJuice fixture; no credentials/network |
| Public Pages release smoke | PASS | `release_id=release-1c15de259d0044d6`, `snapshot_id=5eb1dd579349fc73`, no hash errors |

## Public release evidence

The public manifest returned HTTP 200 with `status=ready`, and the downloaded
market, research, event, source-health, news, creator-release and creator-insights
artifacts matched the manifest hashes. No Telegram delivery was performed by
the public smoke check.

## Remaining external gates

The Railway health endpoint remains HTTP 200 and the monitor is healthy, but its
current diagnostics still report:

- GDELT provider `HTTP_429` (bounded retry; not promoted to evidence)
- health callback `HTTP_403` (local Railway health remains authoritative)
- Gmail ingress `configuration_missing`
- delivery receipt `not_checked`

These are explicitly retained as `NEEDS_REVERIFY` / external configuration
debt. They must not be hidden, converted to success, or used to trigger a
high-risk alert without the required credentials and a controlled recipient.

## Rollback

This is documentation only. Revert this commit to remove the record; it does
not alter market data, release artifacts, Railway state or Telegram delivery.
