# Post-merge acceptance evidence — 2026-08-21

This record covers the post-merge verification of PR #667 and the controlled
single-recipient photo delivery. It is evidence for the release and transport
gates; it is not a claim that optional providers are configured.

## GitHub Actions

| Check | Run | Result |
|---|---|---|
| Pages fallback (invalid candidate must not replace last-good) | [32417839816](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32417839816) | PASS; publish skipped safely |
| Dashboard refresh and release publication | [32417964673](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32417964673) | PASS |
| Single-recipient photo smoke | [32418325859](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32418325859) | PASS |

## Public release

- Main: `f2b6e90a1ef289a1ce4fc3f76e4c936433b9c2b2`
- Release: `release-e43a55e29d580bc1`
- Market snapshot: `389b72b2fb5ff27`
- Research snapshot: `research-8b8ec8f6e5ee51aa`
- Event snapshot: `event-a889bf10a4141a3b`
- Manifest: `status=ready`
- Creator/news: `ready`
- Research: `freshness=stale_fallback` (observation-only)
- Artifact integrity: 7/7 public SHA-256 hashes matched the manifest.

The Pages fallback workflow found no newer **production-complete** research
release and preserved the last valid public release. It did not deploy an
`invalid` manifest and did not send Telegram as a consequence of that failed
candidate.

## Telegram and Railway

The smoke was explicitly limited to the configured test recipient
`8869592162`; no broadcast was performed.

- `photo_card_dimensions=1080x1350`
- delivered: `1`
- failed: `0`
- renderer error: none
- trace: `photo-smoke-34fcf6718bc341f5`
- Railway: `last_outbox_status=delivered`
- Railway: `last_receipt_status=delivered`
- Railway: `receipt_matches_last_outbox=true`
- Railway: recipient count `1`, failure count `0`

This validates the renderer, Telegram `sendPhoto`, deep-link payload plumbing,
and delivery receipt correlation. It is a synthetic smoke identity, not a
claim that a live market event was generated.

## Explicit residual states

- GDELT remains `HTTP_429`; bounded backoff/cache is active and the source is
  not eligible to create a high-risk alert by itself.
- Gmail/Creator ingress remains `configuration_missing` until the operator
  supplies the approved OAuth/PubSub configuration. No private mail content is
  published or inferred.
- A stale research fallback is visible as stale and cannot pass the formal
  research/advice gate.

These states are intentionally fail-closed and must remain visible in Source
Health; they are not converted to `no_event` or `healthy`.

## Rollback

If a later release fails validation, keep the current manifest and rerun the
Pages fallback workflow. Restore the prior immutable `data-release` commit;
never copy individual artifacts between releases.
