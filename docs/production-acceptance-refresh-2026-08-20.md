# Production acceptance checkpoint — refresh dashboard (2026-08-20)

This is an evidence checkpoint for the canonical `main` pipeline after the
approved `refresh-dashboard` dispatch. It does not replace the release gate,
the source-health contract, or the Creator/FinancialJuice trust boundaries.

## Main and workflow evidence

| Item | Evidence |
|---|---|
| Main commit before dispatch | `8b42459d9bebfc4678e30b004681b1ab2586237f` |
| Workflow | [Refresh market dashboard #32369914536](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32369914536) |
| Workflow result | `success` (`refresh-and-deploy`, 1m34s) |
| Publish order | restore `data-release` → collect → build release → validate assets → Pages deploy |
| Pages warning | Node.js 20 deprecation annotation only; no job failure |

The workflow did not send Telegram. Notification remains downstream of the
release gate and requires a separate controlled dispatch.

## Public release evidence

The public manifest was fetched after the workflow completed and returned HTTP
200 with `status=ready`:

| Field | Value |
|---|---|
| `release_id` | `release-e5334a0f2e497e86` |
| `market_snapshot_id` | `592fcbc2838814cf` |
| `research_snapshot_id` | `research-8b8ec8f6e5ee51aa` |
| `event_snapshot_id` | `event-ed531dee05c7de49` |
| `created_at` | `2026-08-20T20:39:56.20191+08:00` (Asia/Taipei) |

The manifest is the only public release selector. Market, research, event,
Creator and news artifacts must be fetched by its declared paths and verified
against its hashes; no artifact is copied across releases.

## Creator and news surface

The public `index.html` contains both the `財經內容洞察` and `市場新聞`
surfaces. The public Creator projection is `status=ready`, is release-bound by
`parent_release_id`, and currently reports coverage `1/1` for the sanitized
Creator input available to the scheduled pipeline. It contains no raw Gmail
content, message identifiers, attachment paths or credentials. A single
Creator record is not evidence that Jenny/Gooaye live Gmail ingress is active;
that requires operator-managed Gmail OAuth/Pub/Sub configuration.

## Runtime health and external gates

The release refresh is healthy, but the following are intentionally visible
external gates rather than silently promoted success:

- Gmail watch/Creator and FinancialJuice live ingress remain
  `configuration_missing` until the Railway operator configures the approved
  OAuth/Pub/Sub path.
- GDELT remains fail-closed on `HTTP_429`; its health callback remains
  `HTTP_403`. The bounded retry/cache and permission-denied projection are
  working, but no stale cache is promoted as a fresh event.
- The local `runtime_audit` may warn when checked-in `site/data` is older than
  the public `data-release`; production acceptance uses the public manifest and
  its hash verification, not a mixed local checkout.

These conditions do not invalidate the ready market release, but they do block
claims of full Creator/FJ/GDELT production acceptance and high-risk delivery
from unverified external evidence.

## Verification commands

```text
gh run view 32369914536 --repo hanjhou2000716/prstklab-stk-detector
python -m src.public_release_smoke --manifest <downloaded-public-manifest> \
  --public-url https://hanjhou2000716.github.io/prstklab-stk-detector/ \
  --attempts 5 --delay 3
```

The smoke command must report `ok=true`, matching release/snapshot IDs and no
hash errors before any notification workflow is authorized.

## Rollback

If a later refresh fails validation or Pages propagation, keep the previous
successful manifest and restore the last good `data-release` snapshot. Do not
publish an `invalid` manifest and do not send Telegram from a failed release.
