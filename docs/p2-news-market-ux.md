# P2 News Mini App readability contract

The market-news cards expose why each story appears without leaking internal
ranking codes as the primary UI.  `site/app.js` maps release-provided
`relevance_reasons`, source authority, topic and interest fields to compact
badges:

- `官方` — official source or official evidence reason.
- `研究標的` — linked to a current research candidate.
- `追蹤標的` — linked to a tracked ticker.
- `Creator 提及` — linked to a sanitized creator mention.
- `產業` — linked to a tracked sector.
- `總經` — linked to a macro topic or macro evidence reason.

The source name remains visible and the first two raw reason codes are retained
as escaped secondary detail for auditability.  When no structured reason is
available the card uses `公開來源` rather than implying relevance that the
release did not prove.  Badge rendering is presentation-only: it does not
change provider scope, ranking, severity, alert eligibility or release gates.

Rollback: revert this PR.  Release JSON remains backward compatible because
all badge inputs are optional and the UI has a neutral source fallback.
