# News source-diversity contract

The canonical news artifact now records the evidence breadth behind the ranked
stories in `source_diversity`.  This is an evidence label, not a severity or
notification decision.

## States

- `no_event`: no ranked stories were retained in this market for the release.
- `single_source`: stories are available, but only one independent source
  domain/provider is represented; the Mini App shows that a second source is
  still pending.
- `multi_source`: at least two independent source domains/providers are
  represented and `cross_checked` is true.

The summary counts canonical domains first and falls back to provider IDs when
an item has no URL.  `supporting_sources` are counted as retained evidence but
do not override the normal market scope, freshness, or release gates.  A
multi-source label therefore never upgrades an alert by itself.

## Compatibility and failure behaviour

`source_diversity` is emitted by `build_news_intelligence` for every new
artifact.  The JSON schema keeps the field additive so older releases remain
readable; runtime validation enforces consistency whenever the field is
present.  Inconsistent counts/statuses are rejected by the artifact contract.

The Mini App shows the state directly above each market's list, keeping
Taiwan/US routing separate and making single-source coverage visible instead
of implying confirmation.

## Rollback

Reverting the producer/UI commit removes the new label while preserving the
existing provider registry, ranking, deduplication, freshness, and fail-soft
behaviour.  Existing artifacts remain compatible because the field is
optional for historical documents.
