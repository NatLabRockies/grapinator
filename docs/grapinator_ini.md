# grapinator.ini Configuration Reference

The `grapinator/resources/grapinator.ini` file controls all runtime behavior of the Grapinator service.
Settings are loaded at startup by `grapinator/settings.py` using the **CryptoConfigParser**, which
transparently decrypts any values that were encrypted with CryptoConfig (see [Encrypted Values](#encrypted-values) below).

---

## Selecting the ini file at runtime

By default Grapinator loads `grapinator/resources/grapinator.ini`.  Set the `GRAPINATOR_CONFIG`
environment variable to override this path at startup without changing any code.  The path is
resolved relative to the **`grapinator/` package directory** (same convention as `GQL_SCHEMA`).

```bash
# Use the default ini file
python grapinator/svc_cherrypy.py

# Use an alternate ini file (e.g. for RBAC testing)
GRAPINATOR_CONFIG=/resources/grapinator_rbac.ini python grapinator/svc_cherrypy.py
```

This follows the same pattern as `GQLAPI_CRYPT_KEY` and makes it easy to run multiple
configurations side-by-side without editing files.

---

## Encrypted Values

Any value in the ini file can be stored in encrypted form using the `enc(...)` wrapper syntax.
This is particularly useful for database credentials.

### How it works

CryptoConfig uses [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption.
At startup, Grapinator reads the encryption key from the `GQLAPI_CRYPT_KEY` environment variable
and passes it to `CryptoConfigParser`.  When the parser encounters a value wrapped in `enc(...)`,
it decrypts the inner token automatically before returning the value.

### Generating a key

CryptoConfig installs a helper command-line utility called `cryptocfg.py`.  Use the `--genkey`
flag to generate a new Fernet encryption key:

```bash
cryptocfg.py --genkey
# Example output: jsZ9EkC3_XnP88UwIGQdFWpKPpeaD61RqJy8DE6lLYk=
```

Store this key in a secure location (e.g. a secrets manager or `.env` file) and export it before
starting the application:

```bash
export GQLAPI_CRYPT_KEY=<your-fernet-key>
```

> **Important:** The same key must be used for both encrypting values and running the application.
> If the key changes, all encrypted values in the ini file must be re-encrypted.

### Encrypting a password

Use `cryptocfg.py` with the `-e` flag to encrypt a value.  Pass the plaintext string via `-i`
and the key via `-p`:

```bash
cryptocfg.py -i 'my_db_password' -p 'jsZ9EkC3_XnP88UwIGQdFWpKPpeaD61RqJy8DE6lLYk=' -e
# Example output: gAAAAABa8Ipc...
```

Place the output inside `enc(...)` in the ini file:

```ini
DB_PASSWORD = enc(gAAAAABa8Ipc...)
```

CryptoConfigParser recognises the `enc(...)` pattern (case-insensitive) and decrypts the value
at read time.  Plain-text values are returned unchanged, so encryption is opt-in per value.

### Decrypting a value (verification)

To verify an encrypted value, use the `-d` flag:

```bash
cryptocfg.py -i 'gAAAAABa8Ipc...' -p 'jsZ9EkC3_XnP88UwIGQdFWpKPpeaD61RqJy8DE6lLYk=' -d
# Output: my_db_password
```

### cryptocfg.py reference

```
use: cryptocfg.py [options]
where options include:
    --decrypt= | -d   decrypt the string, requires -i and -p
    --encrypt= | -e   encrypt the string, requires -i and -p
    --input=   | -i   string to encrypt or decrypt (reads from stdin if omitted)
    --password=| -p   key for encrypting or decrypting (prompted if omitted)
    --genkey          generate a new encryption/decryption key
```

---

## [GRAPHENE]

GraphQL schema configuration.

| Setting | Type | Description |
|---------|------|-------------|
| `GQL_SCHEMA` | path | Path to the schema dictionary file (`.dct`), **relative to the `grapinator/` package directory**.  See [schema_docs.md](schema_docs.md) for the file format. |

**Example:**
```ini
[GRAPHENE]
GQL_SCHEMA = /resources/schema.dct
```

---

## [WSGI]

Network and TLS settings for the CherryPy WSGI server.

| Setting | Required | Type | Description |
|---------|----------|------|-------------|
| `WSGI_SOCKET_HOST` | Yes | string | Hostname or IP address the server binds to.  Use `127.0.0.1` to restrict to localhost or `0.0.0.0` to listen on all interfaces. |
| `WSGI_SOCKET_PORT` | Yes | integer | TCP port the server listens on. |
| `WSGI_SSL_CERT` | No | path | Absolute path to the PEM-encoded TLS certificate file.  **Both** `WSGI_SSL_CERT` and `WSGI_SSL_PRIVKEY` must be present to enable HTTPS. |
| `WSGI_SSL_PRIVKEY` | No | path | Absolute path to the PEM-encoded private key file that corresponds to `WSGI_SSL_CERT`. |

When `WSGI_SSL_CERT` and `WSGI_SSL_PRIVKEY` are omitted, the service runs over plain HTTP.

**Example (HTTPS):**
```ini
[WSGI]
WSGI_SOCKET_HOST = 0.0.0.0
WSGI_SOCKET_PORT = 8443
WSGI_SSL_CERT    = /etc/grapinator/server.crt
WSGI_SSL_PRIVKEY = /etc/grapinator/server.key
```

---

## [CORS]

Cross-Origin Resource Sharing (CORS) policy applied by Flask-Cors.

> **Mutual exclusion:** `CORS_SEND_WILDCARD` and `CORS_SUPPORTS_CREDENTIALS` are mutually exclusive.
> Setting both to `True` violates the CORS specification; use one or the other.

| Setting | Type | Description |
|---------|------|-------------|
| `CORS_ENABLE` | boolean | Master switch. Set to `False` to disable all CORS headers. |
| `CORS_EXPOSE_ORIGINS` | string | Comma-separated list of allowed origins, or `*` to allow any origin. |
| `CORS_ALLOW_METHODS` | string | Comma-separated HTTP methods browsers may use in cross-origin requests (e.g. `GET, POST`). |
| `CORS_HEADER_MAX_AGE` | integer | Number of seconds browsers may cache the preflight response. |
| `CORS_ALLOW_HEADERS` | string | Comma-separated request headers browsers are permitted to send. |
| `CORS_EXPOSE_HEADERS` | string | Comma-separated response headers the browser JavaScript may access. |
| `CORS_SEND_WILDCARD` | boolean | When `True`, send `Access-Control-Allow-Origin: *` regardless of the request origin.  Incompatible with `CORS_SUPPORTS_CREDENTIALS = True`. |
| `CORS_SUPPORTS_CREDENTIALS` | boolean | When `True`, allow cookies and HTTP authentication in cross-origin requests.  Incompatible with `CORS_SEND_WILDCARD = True`. |

**Example (public read-only API):**
```ini
[CORS]
CORS_ENABLE             = True
CORS_EXPOSE_ORIGINS     = *
CORS_ALLOW_METHODS      = GET, POST
CORS_HEADER_MAX_AGE     = 1800
CORS_ALLOW_HEADERS      = Origin, X-Requested-With, Content-Type, Accept
CORS_EXPOSE_HEADERS     = Location
CORS_SEND_WILDCARD      = True
CORS_SUPPORTS_CREDENTIALS = False
```

---

## [HTTP_HEADERS]

Security-related HTTP response headers added to every reply.

| Setting | Recommended value | Description |
|---------|-------------------|-------------|
| `HTTP_HEADERS_XFRAME` | `sameorigin` | `X-Frame-Options` — controls whether the page may be embedded in a `<frame>` or `<iframe>`.  Options: `deny`, `sameorigin`. |
| `HTTP_HEADERS_XSS_PROTECTION` | `1; mode=block` | `X-XSS-Protection` — legacy XSS filter hint for older browsers. |
| `HTTP_HEADER_CACHE_CONTROL` | *(see below)* | `Cache-Control` — directives preventing sensitive API responses from being cached by proxies or browsers. |
| `HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS` | `nosniff` | `X-Content-Type-Options` — prevents browsers from MIME-sniffing the response. |
| `HTTP_HEADERS_REFERRER_POLICY` | `strict-origin-when-cross-origin` | `Referrer-Policy` — controls how much referrer information is sent with requests. |
| `HTTP_HEADERS_CONTENT_SECURITY_POLICY` | *(see below)* | `Content-Security-Policy` — restricts the sources from which scripts, styles, and other resources may be loaded. |

**Default `Cache-Control` value** (prevents all caching):
```
no-cache, no-store, must-revalidate, max-age=0, s-maxage=0, pre-check=0, post-check=0, pragma: no-cache
```

**Default CSP value** (permissive for GraphiQL UI compatibility):
```
default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:;
script-src  'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com;
style-src   'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://unpkg.com;
font-src    'self' https://fonts.gstatic.com https://fonts.googleapis.com data:;
img-src     'self' data: https: http:;
connect-src 'self' ws: wss: http: https:;
frame-src   'self';
worker-src  'self' blob:;
child-src   'self' blob:;
object-src  'none'
```

Tighten the CSP when the GraphiQL UI is not needed in production.

---

## [FLASK]

Flask web framework settings.

| Setting | Type | Description |
|---------|------|-------------|
| `FLASK_SERVER_NAME` | string | Hostname and port Flask uses to build URLs (e.g. `localhost:8443`).  Must match the address the server actually listens on. |
| `FLASK_API_ENDPOINT` | path | URL path at which the GraphQL endpoint is mounted (e.g. `/northwind/gql`).  The GraphiQL interactive UI is also served at this path. |
| `FLASK_DEBUG` | boolean | Enables Flask debug mode.  **Set to `False` in production** — debug mode exposes an interactive debugger and disables certain security checks. |

**Example:**
```ini
[FLASK]
FLASK_SERVER_NAME  = localhost:8443
FLASK_API_ENDPOINT = /northwind/gql
FLASK_DEBUG        = False
```

---

## [SQLALCHEMY]

Database connection settings.  `DB_USER` and `DB_PASSWORD` are optional for databases that do
not require authentication (e.g. SQLite).  `DB_PASSWORD` supports CryptoConfig encryption (see
[Encrypted Values](#encrypted-values) above).

| Setting | Required | Type | Description |
|---------|----------|------|-------------|
| `DB_TYPE` | Yes | string | SQLAlchemy database URL dialect+driver prefix (e.g. `sqlite+pysqlite`, `mysql+pymysql`, `oracle+oracledb`). |
| `DB_USER` | No | string | Database username.  Required for all non-SQLite databases. |
| `DB_PASSWORD` | No | string | Database password.  May be stored as plain text or as an encrypted `enc(...)` value.  Required for all non-SQLite databases. |
| `DB_CONNECT` | Yes | string | For SQLite: absolute path to the database file (e.g. `/db/northwind.db`).  For all other databases: `host/database` or `host:port/database` (the part after the `@` in a standard SQLAlchemy URL). |
| `SQLALCHEMY_TRACK_MODIFICATIONS` | Yes | boolean | When `True`, Flask-SQLAlchemy emits a signal on every model change.  Set to `False` to suppress the deprecation warning and reduce memory overhead. |
| `ORCL_NLS_LANG` | No | string | *(Oracle only)* Value written to the `NLS_LANG` environment variable before the connection is established (e.g. `AMERICAN_AMERICA.AL32UTF8`). |
| `ORCL_NLS_DATE_FORMAT` | No | string | *(Oracle only)* Value written to the `NLS_DATE_FORMAT` environment variable (e.g. `YYYY-MM-DD HH24:MI:SS`). |

The full SQLAlchemy database URI is assembled at runtime:

- **SQLite:** `<DB_TYPE>://<DB_CONNECT>`
- **All other databases:** `<DB_TYPE>://<DB_USER>:<DB_PASSWORD>@<DB_CONNECT>`

**Example (SQLite):**
```ini
[SQLALCHEMY]
DB_TYPE                       = sqlite+pysqlite
DB_CONNECT                    = /db/northwind.db
SQLALCHEMY_TRACK_MODIFICATIONS = False
```

**Example (MySQL with encrypted password):**
```ini
[SQLALCHEMY]
DB_TYPE                       = mysql+pymysql
DB_USER                       = grapinator
DB_PASSWORD                   = enc(gAAAAABn...)
DB_CONNECT                    = db.example.com/mydb
SQLALCHEMY_TRACK_MODIFICATIONS = False
```

**Example (Oracle with NLS settings):**
```ini
[SQLALCHEMY]
DB_TYPE                       = oracle+oracledb
DB_USER                       = grapinator
DB_PASSWORD                   = enc(gAAAAABn...)
DB_CONNECT                    = db.example.com:1521/ORCL
SQLALCHEMY_TRACK_MODIFICATIONS = False
ORCL_NLS_LANG                 = AMERICAN_AMERICA.AL32UTF8
ORCL_NLS_DATE_FORMAT          = YYYY-MM-DD HH24:MI:SS
```

---

## [AUTH]

Optional JWT bearer token authentication.  When omitted (or when `AUTH_MODE = off`), the service
behaves exactly as it did before this section existed — no auth checking occurs and existing
deployments are completely unaffected.

### Auth modes

| `AUTH_MODE` | Behaviour |
|-------------|-----------|
| `off` | *(default)* No auth — every request is allowed. |
| `mixed` | Requests without a token are treated as unauthenticated. Role-restricted fields return `null` and role-restricted entities return empty results for unauthenticated callers. A present-but-invalid token **always** returns 401. |
| `required` | Every request must carry a valid bearer token (except CORS preflight `OPTIONS` and, optionally, the GraphiQL IDE page — see `GRAPHIQL_ACCESS`). |

### Settings reference

| Setting | Default | Type | Description |
|---------|---------|------|-------------|
| `AUTH_MODE` | `off` | string | Auth mode: `off`, `mixed`, or `required`. |
| `AUTH_JWKS_URI` | *(none)* | URL | JWKS endpoint URL of your identity provider. Used for RS256 (and other asymmetric) token validation.  See provider examples below. |
| `AUTH_ISSUER` | *(none)* | string | Expected `iss` claim in the JWT.  When set, tokens with a different issuer are rejected. |
| `AUTH_AUDIENCE` | *(none)* | string | Expected `aud` claim in the JWT (typically your app's client ID). |
| `AUTH_ALGORITHMS` | `RS256` | string | Comma-separated list of accepted signing algorithms (e.g. `RS256` or `RS256,ES256`). |
| `AUTH_ROLES_CLAIM` | `roles` | string | Dotted-path to the roles array inside the JWT payload.  Examples: `roles` (Entra ID / Auth0), `realm_access.roles` (Keycloak). |
| `AUTH_JWKS_CACHE_TTL` | `300` | integer | Seconds to cache the JWK set fetched from `AUTH_JWKS_URI`. Reduces IdP requests without staling. |
| `GRAPHIQL_ACCESS` | `authenticated` | string | Controls GraphiQL IDE access.  See table below. |
| `AUTH_DEV_SECRET` | *(none)* | string | **Local development only.** HS256 HMAC secret for validating dev tokens generated by `tools/dev_jwt.py`. **Never set in production.** |

### GraphiQL access control

| `GRAPHIQL_ACCESS` | Behaviour |
|-------------------|-----------|
| `authenticated` | *(default)* The GraphiQL IDE HTML page requires a valid bearer token, same as any other request. |
| `open` | The IDE HTML is served to any browser without a token.  All actual GraphQL queries still go through auth ($mixed$/$required$ rules apply). |
| `off` | The IDE is disabled entirely.  The endpoint only returns GraphQL JSON responses. |

### CORS note

When auth is enabled, browsers must be allowed to send the `Authorization` header in
cross-origin requests.  Add it to `CORS_ALLOW_HEADERS`:

```ini
CORS_ALLOW_HEADERS = Origin, X-Requested-With, Content-Type, Accept, Authorization
```

### Provider-specific examples

#### Azure Entra ID (formerly Azure AD)

```ini
[AUTH]
AUTH_MODE        = mixed
AUTH_JWKS_URI    = https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys
AUTH_ISSUER      = https://login.microsoftonline.com/<tenant-id>/v2.0
AUTH_AUDIENCE    = <client-id>
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = roles
```

> Roles are defined as App Roles on your Entra ID App Registration and assigned to users/groups
> by an Entra ID admin.  Role values (not display names) must match the values used in
> `gql_auth_roles` / `AUTH_ROLES` in `schema.dct`.

#### Keycloak

```ini
[AUTH]
AUTH_MODE        = required
AUTH_JWKS_URI    = https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
AUTH_ISSUER      = https://keycloak.example.com/realms/myrealm
AUTH_AUDIENCE    = grapinator-api
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = realm_access.roles
```

#### Auth0

```ini
[AUTH]
AUTH_MODE        = mixed
AUTH_JWKS_URI    = https://yourapp.auth0.com/.well-known/jwks.json
AUTH_ISSUER      = https://yourapp.auth0.com/
AUTH_AUDIENCE    = https://grapinator-api
AUTH_ALGORITHMS  = RS256
AUTH_ROLES_CLAIM = https://grapinator/roles
```

### Local development with `AUTH_DEV_SECRET`

> **Important:** JWT authentication is enforced by `BearerAuthMiddleware`, which is only
> inserted into the WSGI stack when the service runs under **`svc_cherrypy.py`**.  Flask's
> built-in development server (`grapinator/app.py` / `flask run`) does **not** invoke the
> middleware, so `Authorization` headers are silently ignored and all fields are returned
> regardless of role.  Always test RBAC against the CherryPy server:
>
> ```bash
> python grapinator/svc_cherrypy.py
> ```

During development you can authenticate without a running IdP by using HS256 tokens signed with
a shared secret.  **This is not suitable for production.**

1. Add to your local `grapinator.ini`:

   ```ini
   [AUTH]
   AUTH_MODE       = mixed
   AUTH_DEV_SECRET = change-me-local-dev-only
   ```

2. Generate a token with the bundled helper script:

   ```bash
   # Optional: export the secret so you don't need --secret every time
   export GRAPINATOR_DEV_SECRET=change-me-local-dev-only

   # Generate a 1-hour token with roles 'admin' and 'reader'
   python tools/dev_jwt.py --roles admin,reader

   # Print the ready-to-paste Authorization header
   python tools/dev_jwt.py --roles admin,reader --print-header

   # Keycloak-style nested claim
   python tools/dev_jwt.py --roles admin --claim realm_access.roles

   # Custom expiry (30 minutes)
   python tools/dev_jwt.py --roles admin --expiry 1800
   ```

3. Pass the token in requests:

   ```bash
   #!/bin/sh
   # RBAC test — queries birth_date which is restricted to the 'hr' role in schema_rbac.dct.
   #
   # IMPORTANT: JWT auth (BearerAuthMiddleware) is only active when the service is
   # running under the CherryPy WSGI server (svc_cherrypy.py).  Flask's built-in
   # development server (app.py / `flask run`) does NOT insert the auth middleware
   # and will return data for ALL fields regardless of role.
   #
   # Start the server with:
   #   python grapinator/svc_cherrypy.py
   #
   # Expected result with role 'hr':  birth_date has a real value.
   # Expected result with no token:   birth_date is null (mixed mode).

   TOKEN=$(python tools/dev_jwt.py --roles hr --secret change-me-local-dev-only)
   curl -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"query":"{ employees { edges { node { employee_id first_name birth_date} } } }"}' \
       http://localhost:8443/northwind/gql
   ```

> **Security note:** `AUTH_DEV_SECRET` enables HS256 validation only when no `AUTH_JWKS_URI` is
> configured.  If both are set, `AUTH_JWKS_URI` takes precedence and the dev secret is ignored.
> In production: set `AUTH_JWKS_URI` only, never `AUTH_DEV_SECRET`.
