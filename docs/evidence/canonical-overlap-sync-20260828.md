# Canonical Creator／FinancialJuice／News sync checkpoint — 2026-08-28

This checkpoint records the current mainline and external evidence after the
canonical overlap fixes. Secret values, recipient IDs and private mail content
are intentionally excluded.

## Mainline

- `main`: `b2136a44bb06e8...` (merge commit for PR #811)
- PR #808: canonicalize known quote crosscheck policy metadata — merged
- PR #809: keep raw observations usable on long paths — merged
- PR #810: omit unregistered quote crosscheck policy — merged
- PR #811: record canonical intelligence sync checkpoint — merged

## Canonical ownership audit

The following checks pass on the merged mainline:

- `python scripts/verify_canonical_overlap.py`
- `python scripts/verify_intelligence_contracts.py`
- `ruff check src tests`
- `mypy src` (183 source files)
- Python compilation and Mini App syntax check
- full local regression on the current mainline: 1,509 passed (2026-08-28)

Creator, FinancialJuice and News remain additive projections over the existing
market/event release path. Creator records stay editorial and cannot become
event evidence. FinancialJuice vendor importance stays separate from PRStK
risk. News remains fail-soft and uses the central provider/URL contract.

## Release evidence

The first post-merge `refresh-dashboard` run exposed a real producer defect in
unregistered quote policy metadata and failed closed (`33178909050`). PR #810
removed the empty policy/fallback mismatch. The rerun succeeded:

- refresh run: `33179621859` — success
- public release: `release-0c17992be7a6c05c`
- market snapshot: `1090a9f03cc907bc`
- research snapshot: `research-8b8ec8f6e5ee51aa`
- event snapshot: `event-2668aef41e66e57b`
- manifest status: `ready`
- Public release smoke run: `33180061232` — success, no delivery performed
- public manifest/artifact hash audit: 7/7 hashes matched

The release is therefore valid and release-gated. Research remains explicitly
labelled as a stale fallback where applicable; no high-risk research delivery
is inferred from this checkpoint.

## Secret/configuration boundary

Only presence and names were checked:

| Name | GitHub Actions | Cloudflare Worker | Note |
|---|---|---|---|
| `SUPABASE_URL` | present | present | same project endpoint |
| `SUPABASE_SERVICE_ROLE_KEY` | missing | present | required for `report-worker` |
| `GITHUB_DISPATCH_TOKEN` | not required | present | Worker-only dispatch credential |
| `TELEGRAM_BOT_TOKEN` | present | present | no values logged |
| `DELIVERY_RECEIPT_SHARED_SECRET` | present | present | names aligned |
| `RAILWAY_STATUS_SHARED_SECRET` | present | not a Worker requirement | Railway/Actions boundary |

The public Worker health endpoint is HTTP 200 and reports Supabase, report
dispatch and Telegram as configured. The deployed `/api/delivery-receipt`
route still returns `404 NOT_FOUND`, which proves the live Worker source has
not yet been redeployed to the latest receipt implementation. Presence of a
secret is not treated as proof of value equality.

The secret-name audit was repeated against GitHub Actions and the authenticated
Cloudflare Worker settings on 2026-08-28. It confirms the same boundary: the
Worker has the service-role key while GitHub Actions does not. No secret value
was read, copied, logged or committed.

## Open gates

- Add `SUPABASE_SERVICE_ROLE_KEY` to GitHub Actions without exposing its value.
- Redeploy the latest `worker/` source, then run a signed single-recipient
  receipt canary.
- Re-run the live Gmail/Creator/FJ/News acceptance capture; offline contract
  tests do not prove external ingress health.
- Keep the existing GDELT 429, Railway callback and Gmail persistence items in
  the regression/debt ledger until fresh external evidence closes them.

## Rollback

Restore the previous successful `data-release` commit and Pages release if a
future manifest or public hash check fails. Revert PR #808–#810 individually
only when diagnosing a regression; do not copy artifacts between releases.
