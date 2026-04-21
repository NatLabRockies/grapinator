# OIDC / Bearer Token Authentication

Grapinator supports IdP-agnostic JWT bearer token authentication via the `[AUTH]` section of
`grapinator.ini`.  Any OIDC-compliant provider works; provider-specific values are listed below.

---

## Auth settings reference

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTH_MODE` | `off` | `off` — no auth; `mixed` — token optional, bad token always 401; `required` — token mandatory |
| `AUTH_JWKS_URI` | — | URL of the provider's JWKS endpoint |
| `AUTH_ISSUER` | — | Expected `iss` claim in the JWT |
| `AUTH_AUDIENCE` | — | Expected `aud` claim in the JWT |
| `AUTH_ALGORITHMS` | `RS256` | Comma-separated list of accepted signing algorithms (`none` is always rejected) |
| `AUTH_ROLES_CLAIM` | `roles` | Dotted path to the roles list inside the JWT payload (e.g. `realm_access.roles`) |
| `AUTH_JWKS_CACHE_TTL` | `300` | Seconds to cache the fetched JWK set |
| `GRAPHIQL_ACCESS` | `authenticated` | `authenticated` — IDE requires token; `open` — IDE served without auth; `off` — IDE disabled |
| `AUTH_DEV_SECRET` | — | HS256 shared secret for local dev tokens — **never use in production** |

---

## Keycloak

Keycloak stores roles under `realm_access.roles` in the JWT payload.  Use the dotted-path
notation for `AUTH_ROLES_CLAIM`.

**JWKS URI format:** `https://<host>/realms/<realm>/protocol/openid-connect/certs`

```ini
[AUTH]
AUTH_MODE        = required
AUTH_JWKS_URI    = https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
AUTH_ISSUER      = https://keycloak.example.com/realms/myrealm
AUTH_AUDIENCE    = grapinator
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = realm_access.roles
```

For local development with the Docker Compose stack in `docker/keycloak.yaml`:

```ini
[AUTH]
AUTH_MODE        = required
AUTH_JWKS_URI    = http://localhost:8080/realms/dev/protocol/openid-connect/certs
AUTH_ISSUER      = http://localhost:8080/realms/dev
AUTH_AUDIENCE    = grapinator
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = realm_access.roles
```

See [docker/keycloak.yaml](../docker/keycloak.yaml) for the Docker Compose stack that spins up
a pre-configured Keycloak instance with a `dev` realm and a `grapinator` client.

---

## Azure Entra ID (formerly Azure AD)

Entra ID places roles in a flat `roles` array at the top level of the JWT payload.

**JWKS URI format:** `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys`

```ini
[AUTH]
AUTH_MODE        = required
AUTH_JWKS_URI    = https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys
AUTH_ISSUER      = https://login.microsoftonline.com/{tenant-id}/v2.0
AUTH_AUDIENCE    = {client-id}
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = roles
```

Replace `{tenant-id}` with your Azure tenant GUID and `{client-id}` with the application
(client) ID of the registered app.

---

## Auth0

Auth0 roles are typically delivered as a custom claim.  The claim name is configured in your
Auth0 Action/Rule; a common convention is `https://your-domain/roles`.

**JWKS URI format:** `https://<your-auth0-domain>/.well-known/jwks.json`

```ini
[AUTH]
AUTH_MODE        = required
AUTH_JWKS_URI    = https://your-tenant.auth0.com/.well-known/jwks.json
AUTH_ISSUER      = https://your-tenant.auth0.com/
AUTH_AUDIENCE    = https://your-api-identifier
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = https://your-tenant.auth0.com/roles
```

The `AUTH_ROLES_CLAIM` value must exactly match the namespace you set in your Auth0 Action.

---

## Okta

Okta embeds group memberships or custom roles in the `groups` claim when the Groups scope is
requested, or in a custom attribute on the access token.

**JWKS URI format:** `https://<okta-domain>/oauth2/<auth-server-id>/v1/keys`

```ini
[AUTH]
AUTH_MODE        = required
AUTH_JWKS_URI    = https://dev-123456.okta.com/oauth2/default/v1/keys
AUTH_ISSUER      = https://dev-123456.okta.com/oauth2/default
AUTH_AUDIENCE    = api://default
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = groups
```

If you use a custom claim name, replace `groups` with your configured claim path.

---

## Local development (no IdP)

Use `AUTH_DEV_SECRET` with HS256 to validate tokens signed with a shared secret.  The helper
script `tools/dev_jwt.py` mints tokens signed with this secret.

```ini
[AUTH]
AUTH_MODE       = required
AUTH_ALGORITHMS = HS256
AUTH_DEV_SECRET = change-me-local-dev-only
```

`AUTH_JWKS_URI` must be absent (or commented out) for the dev secret path to be used.  When
both are present, the JWKS path takes precedence and the dev secret is ignored.

> **Warning:** `AUTH_DEV_SECRET` provides no public-key verification.  Never set it in a
> production or shared environment.

---

## RBAC — restricting fields by role

Set `AUTH_MODE = mixed` or `required` and annotate the schema dictionary with `roles` entries.
Requests that carry a valid token receive `grapinator.user_roles` populated from the JWT;
role-restricted fields return `null` when the caller lacks the required role.

See [grapinator_rbac.ini](../grapinator/resources/grapinator_rbac.ini) and
[schema_docs.md](schema_docs.md) for the full RBAC configuration reference.
