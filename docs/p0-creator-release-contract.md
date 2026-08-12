# Creator release contract hardening

The creator release validator is a second safety boundary after the parser
gate. Even if a caller invokes `build_creator_release` directly, a record with
`parse_failed`, `unsupported_template`, `invalid_source`, or `duplicate` can
never be included in a publishable artifact. Adapter records that explicitly
declare missing required fields are rejected as well.

The check is additive and preserves historical normalized records that do not
carry parser metadata. It does not turn missing creator content into a market
event or a high-risk alert. Rollback is safe: revert this commit to restore the
previous additive artifact validator; the parent market release remains
independent.
