# Post-merge acceptance evidence — 2026-08-24

This record is based on `main` after PR #738 (`dc8e945995061bf4618b3d6a30a16daed668ea59`).
It is evidence-only: it does not promote a degraded provider to healthy and does not
contain secrets, recipient identifiers, raw mail, or Telegram response bodies.

## Local verification

| Check | Result | Evidence |
|---|---|---|
| Full pytest on merged `main` | PASS | 1375 passed in 78.46s |
| Canonical intelligence contract audit | PASS | `scripts/verify_intelligence_contracts.py` |
| Creator notification offline E2E | PASS | command exited 0 |
| FinancialJuice notification offline E2E | PASS | command exited 0 |
| Runtime audit | PASS with sample-data warnings | `ok=true`; warnings are checked-in fixture gaps, not live release claims |

## External read-only acceptance

Workflow: `External acceptance (read-only)` run `32661041562`.

| Surface | Result | Evidence |
|---|---|---|
| Railway service / heartbeat | PASS | HTTP 200; monitor running and heartbeat healthy |
| Gmail ingress and Watch | PASS | status and Watch both healthy; lease present |
| GitHub Pages release | PASS | manifest `ready`; release and snapshot lineage present; 5/5 artifact hashes verified |
| Delivery receipt contract | PASS | latest controlled single-recipient photo receipt was delivered; post-merge acceptance now accepts `delivered` |
| Creator live input | NEEDS_REVERIFY | current poll reported `no_new_content`; no real message was fabricated |
| FinancialJuice live input | NEEDS_REVERIFY | current poll reported `no_new_content`; no real message was fabricated |
| GDELT discovery | NEEDS_REVERIFY | provider returned HTTP 429; bounded backoff remained active and no alert was promoted |

The external report status is therefore `NEEDS_REVERIFY`, intentionally. This is not
treated as “no event”: GDELT is explicitly `failed`/rate-limited, while Creator and
FinancialJuice are explicitly `no_new_content`. A provider failure cannot be used to
infer that no market risk exists.

## Safety decisions confirmed

- A successful delivery receipt is not misclassified as a provider-health failure.
- GDELT rate limits remain bounded by backoff; stale cache, when available, is visible
  and cannot qualify a high-risk alert.
- Pages artifacts are accepted only when the public manifest is `ready` and hashes and
  snapshot IDs match.
- No broadcast test was run. The only Telegram side effect was the previously approved
  single-recipient production photo acceptance.
- No Creator or FinancialJuice real-world email was invented; those lanes remain
  pending live evidence until an actual sanitized observation arrives.

## Residual actions

1. Wait for the next GDELT retry window and capture a successful or stale-cache health
   observation without bypassing the provider rate limit.
2. When a real sanitized Creator or FinancialJuice observation arrives, run the
   release-gated lane and record its release, snapshot, observation, and delivery
   receipt lineage.
3. Keep the previous successful release as rollback until a new live release passes
   the same manifest/hash audit.

## Rollback

This document is additive and can be reverted without changing runtime behavior. For
runtime rollback, restore the previous immutable `data-release` release; do not mix
market, research, event, Creator, or FinancialJuice artifacts from different releases.
