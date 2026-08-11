# P2 market-news routing hardening

Regional news cards now fail closed for headlines with no auditable Taiwan,
US, global or cross-market evidence. Previously an unclassified provider item
could be retained in both tabs, making a Taiwan card appear to contain a Fed
story or a US card a Taiwan-politics story. Explicit Taiwan/US matches are
still routed to one tab; global and cross-market stories remain eligible for
both and retain classification evidence.

An empty result remains a valid `no_event` state. Provider errors continue to
be reported as `failed`, and the bounded cache is used only after the same
market has passed the classifier.

## Rollback

Revert this PR to restore the previous unclassified fallback behavior. No
stored article is deleted; the next scan rebuilds the market-specific lists.
