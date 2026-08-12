# Production research strategy matrix

The strict release gate requires exactly these eight source identities:

| Market | Strategies |
|---|---|
| Taiwan | momentum, price_action, resonance, value |
| US | momentum, price_action, resonance, value |

The check is intentionally based on `(market, strategy)` identities rather
than aggregate row counts. A missing strategy is a data gap, not a successful
empty scan. Duplicate or unknown identities are also rejected because they
could cause one strategy drawer to consume another strategy's rows.

This gate does not relax candidate conditions and does not create candidates.
It only prevents an incomplete research artifact from being labelled a strict
production release. The Mini App may still show the last known good release or
an explicit unavailable/building state.

## Rollback

Reverting the producer and gate commit restores the previous compatibility
behaviour. Do not manually copy individual research files between releases.
