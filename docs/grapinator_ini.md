# grapinator.ini Configuration Reference

The `grapinator/resources/grapinator.ini` file controls all runtime behavior of the Grapinator service.
Settings are loaded at startup by `grapinator/settings.py` using the **CryptoConfigParser**, which
transparently decrypts any values that were encrypted with CryptoConfig (see [Encrypted Values](#encrypted-values) below).

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
