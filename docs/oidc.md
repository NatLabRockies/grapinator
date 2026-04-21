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
AUTH_MODE         = mixed
AUTH_JWKS_URI     = https://keycloak.example.com/realms/grapinator-dev/protocol/openid-connect/certs
AUTH_ISSUER       = https://keycloak.example.com/realms/grapinator-dev
AUTH_AUDIENCE     = grapinator-api
AUTH_ALGORITHMS   = RS256
AUTH_ROLES_CLAIM  = realm_access.roles
GRAPHIQL_ACCESS   = open
```

### Manual setup with Docker

If you prefer to configure Keycloak by hand instead of using the compose stack:

#### 1. Start Keycloak

```bash
docker run -d \
  --name keycloak-dev \
  -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:26.1 \
  start-dev
```

Wait ~20 seconds. Open http://localhost:8080/admin and log in as `admin` / `admin`.

#### 2. Create a Realm

1. Top-left dropdown → **Create realm**
2. **Realm name**: `grapinator-dev` → **Create**

#### 3. Create a Client

1. Left nav → **Clients** → **Create client**
2. **Client type**: OpenID Connect, **Client ID**: `grapinator-api` → **Next**
3. **Client authentication**: ON → **Next** → **Save**
4. **Credentials** tab → copy the **Client secret**

#### 4. Create Realm Roles

Left nav → **Realm roles** → **Create role**: `hr` → **Save**.  Repeat for `admin`.

#### 5. Assign Role to Service Account

Left nav → **Clients** → `grapinator-api` → **Service accounts roles** tab →
**Assign role** → filter by Realm roles → select `hr` → **Assign**

#### 6. Verify

```bash
curl -s http://localhost:8080/realms/grapinator-dev/.well-known/openid-configuration \
  | python3 -m json.tool | grep -E '"issuer"|"jwks_uri"'
```

Expected:
```
"issuer": "http://localhost:8080/realms/grapinator-dev",
"jwks_uri": "http://localhost:8080/realms/grapinator-dev/protocol/openid-connect/certs",
```

#### 7. Configure grapinator_rbac_keycloakdev.ini

The `[AUTH]` section should read:

```ini
[AUTH]
AUTH_MODE         = mixed
AUTH_JWKS_URI     = http://localhost:8080/realms/grapinator-dev/protocol/openid-connect/certs
AUTH_ISSUER       = http://localhost:8080/realms/grapinator-dev
AUTH_AUDIENCE     = grapinator-api
AUTH_ALGORITHMS   = RS256
AUTH_ROLES_CLAIM  = realm_access.roles
GRAPHIQL_ACCESS   = open
```

> Do **not** set `AUTH_DEV_SECRET` when `AUTH_JWKS_URI` is configured.

### Automated local setup (Docker Compose)

The compose stack in `docker/keycloak.yaml` automates all of the above.  It imports
`docker/resources/keycloak-realm.json` on first start, which pre-creates the
`grapinator-dev` realm, `grapinator-api` client (`client_secret = grapinator-api-secret`),
`hr` and `admin` realm roles, and two test users:

| Username | Password | Roles |
|----------|----------|-------|
| `hruser` | `hruser` | `hr` |
| `admin`  | `admin`  | `hr`, `admin` |

```bash
docker compose -f docker/keycloak.yaml up -d
```

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

### Testing RBAC with the local Keycloak Docker container

The examples below assume the compose stack from `docker/keycloak.yaml` is running and
Grapinator is started with the RBAC ini file:

```bash
docker compose -f docker/keycloak.yaml up -d
GRAPINATOR_CONFIG=/resources/grapinator_rbac_keycloakdev.ini python grapinator/svc_cherrypy.py
```

The `birth_date` field in the Northwind schema is restricted to the `hr` role.

#### Password grant (test user credentials)

First, verify Keycloak is ready and the realm was imported:

```bash
curl -s http://localhost:8080/realms/grapinator-dev \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('realm','not found'))"
# Expected output: grapinator-dev
```

If the realm is not found, Keycloak may still be starting.  Wait a few seconds and retry, or
check `docker compose -f docker/keycloak.yaml logs keycloak`.

> **Troubleshooting — `"error": "invalid_grant", "error_description": "Account is not fully set up"`**
> Keycloak has attached required actions (e.g. verify email) to the user on import.  The fix
> is already applied in `docker/resources/keycloak-realm.json` (`"requiredActions": []`).
> If you have an existing container, destroy it and recreate so the updated realm JSON is re-imported:
> ```bash
> docker compose -f docker/keycloak.yaml down -v
> docker compose -f docker/keycloak.yaml up -d
> ```

Once the realm is confirmed, obtain a token and query:

```bash
# Check the raw token response first (shows any error details)
curl -s -X POST \
    http://localhost:8080/realms/grapinator-dev/protocol/openid-connect/token \
    -d "client_id=grapinator-api" \
    -d "client_secret=grapinator-api-secret" \
    -d "username=hruser" \
    -d "password=hruser" \
    -d "grant_type=password"

# If the response contains "access_token", extract it and query Grapinator
TOKEN=$(curl -s -X POST \
    http://localhost:8080/realms/grapinator-dev/protocol/openid-connect/token \
    -d "client_id=grapinator-api" \
    -d "client_secret=grapinator-api-secret" \
    -d "username=hruser" \
    -d "password=hruser" \
    -d "grant_type=password" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token') or d)")

curl -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ employees { edges { node { employee_id first_name birth_date} } } }"}' \
    http://localhost:8443/northwind/gql
```

Expected: `birth_date` contains real values because `hruser` carries the `hr` role.

#### No token (mixed mode)

```bash
curl -H "Content-Type: application/json" \
    -d '{"query":"{ employees { edges { node { employee_id first_name birth_date} } } }"}' \
    http://localhost:8443/northwind/gql
```

Expected: `birth_date` is `null` for every node — the field is restricted and no role was presented.

#### Client credentials grant (service account)

The `grapinator-api` service account has the `hr` role assigned (step 5 of the manual setup).

```bash
TOKEN=$(curl -s -X POST \
    http://localhost:8080/realms/grapinator-dev/protocol/openid-connect/token \
    -d "client_id=grapinator-api" \
    -d "client_secret=grapinator-api-secret" \
    -d "grant_type=client_credentials" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ employees { edges { node { employee_id first_name birth_date} } } }"}' \
    http://localhost:8443/northwind/gql
```

#### Inspect the decoded token (optional)

```bash
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool | grep -A5 realm_access
```
