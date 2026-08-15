# Railway delivery secret migration

`RAILWAY_STATUS_SHARED_SECRET` is the canonical variable name shared by the
Railway health service and GitHub Actions.  `DELIVERY_STATUS_SHARED_SECRET` is
accepted only as a temporary compatibility fallback so an existing deployment
can keep serving while the service is migrated.

The runtime now:

- prefers the canonical variable when both names exist;
- reports only redacted metadata (`active_name` and `migration_required`);
- never logs or returns either secret value; and
- keeps delivery verification fail-closed when neither variable is present.

## Railway operator action

In the Railway service that hosts `railway-monitor`, create or rename the
existing secret to `RAILWAY_STATUS_SHARED_SECRET` without changing its value.
Keep the legacy variable temporarily until a health check reports
`canonical_name_present=true` and `migration_required=false`; then remove the
legacy name in a separate, reviewed change.

The repository code cannot safely perform this operation because the secret
value must remain private and Railway variable mutation requires an
authenticated operator action.

## Verification

The health payload must expose only:

```json
{
  "delivery_secret_configured": true,
  "canonical_name_present": true,
  "legacy_name_present": false,
  "active_name": "RAILWAY_STATUS_SHARED_SECRET",
  "migration_required": false,
  "secret_values_exposed": false
}
```
