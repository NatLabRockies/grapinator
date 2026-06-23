# Grapinator 2.1.12 — Design Specification

> **Status:** Draft — design only. No code changes are produced by this document.
> **Tracking issue:** [NatLabRockies/grapinator#33](https://github.com/NatLabRockies/grapinator/issues/33)
> **Target release:** 2.1.12

---

## 1. Goals

1. **Replace CherryPy with Gunicorn** as the production WSGI server, in order
   to modernize the stack, simplify deployment, and improve sustained
   throughput under typical Grapinator workloads (many short GraphQL
   requests per second, each backed by 1 Oracle round-trip).
2. **Add a SQLAlchemy `connect` event listener** that applies the
   `python-oracledb` thin-mode `call_timeout` (and other vendor-specific
   knobs) to every connection checked out of the SQLAlchemy pool. All
   listener-driven settings will be namespaced with an `ORACLE_` prefix
   in `grapinator.ini`.
3. **Refactor the documentation** so that all CherryPy-specific guidance is
   replaced with Gunicorn-equivalent guidance.
4. **Reshape the unit test suite** — remove tests whose only purpose is
   exercising CherryPy-managed code paths, and add new tests covering the
   Gunicorn-managed code paths where unit testing is meaningful.
5. **Publish recommended Nginx settings** for the API-gateway reverse proxy
   sitting in front of Grapinator, tuned for high request-per-second
   workloads.

This release is **API-compatible with 2.1.11**. The GraphQL endpoint URL,
auth behaviour, schema dictionary format, encrypted-INI handling, and
GraphiQL UI behaviour all remain unchanged.

---

## 2. Current architecture (baseline)

```
┌──────────────────────────────────────────────────────────────────┐
│  CherryPy built-in HTTP server  (svc_cherrypy.run_server)        │
│  └── WSGILogger                       (Apache-format access log) │
│      └── SecurityHeadersMiddleware    (security response headers)│
│          └── CorsMiddleware           (CORS preflight + headers) │
│              └── BearerAuthMiddleware (optional, AUTH_MODE)      │
│                  └── Flask app        (graphql_server endpoint)  │
└──────────────────────────────────────────────────────────────────┘
```

Configuration is loaded from an encrypted INI file
([grapinator/resources/grapinator.ini](../grapinator/resources/grapinator.ini))
by [grapinator/settings.py](../grapinator/settings.py).
The CherryPy server is started by
[grapinator/svc_cherrypy.py](../grapinator/svc_cherrypy.py).
The container entrypoint
[docker/resources/grapinator_service.sh](../docker/resources/grapinator_service.sh)
invokes that script directly.

---

## 3. Target architecture

```
┌─────────────────────┐    ┌──────────────────────────────────────────┐
│  Nginx (API gateway)│───▶│ Gunicorn  (sync workers + threads)       │
│  TLS termination    │    │ ──────────────────────────────────────── │
│  Connection limits  │    │ Per worker process:                      │
│  Rate limiting      │    │   WSGILogger                             │
│  Static GraphiQL?   │    │     SecurityHeadersMiddleware            │
│                     │    │       CorsMiddleware                     │
│                     │    │         BearerAuthMiddleware (optional)  │
│                     │    │           Flask app                      │
└─────────────────────┘    └──────────────────────────────────────────┘
```

Key changes vs. baseline:

- **HTTP transport** is owned by Gunicorn. CherryPy is removed entirely
  from the runtime dependency set.
- **Deployment unit** is one container per host running a single
  Gunicorn instance with `N` workers (per [§11 decision #1](#11-resolved-decisions)).
  This preserves today's one-container deployment model and keeps log
  aggregation, metrics scraping, and Nginx upstream config simple.
- **TLS termination** moves to Nginx. Gunicorn binds plain HTTP on
  `127.0.0.1:<port>` by default. A unix-domain socket bind is fully
  supported and documented as the recommended production option (see
  [§6.5](#65-unix-domain-socket-setup-recommended-for-production)), but
  the bundled INI files keep TCP loopback as the default so local-dev
  workflows work without Nginx (per [§11 decision #2](#11-resolved-decisions)).
  TLS certificate paths in the INI file (`WSGI_SSL_CERT` /
  `WSGI_SSL_PRIVKEY`) become **deprecated**: still accepted, but logged
  with a warning that says "TLS is now terminated by Nginx; remove these
  keys".
- **The WSGI middleware stack is unchanged.** The
  `SecurityHeadersMiddleware`, `CorsMiddleware`, `BearerAuthMiddleware`,
  and `WSGILogger` classes continue to be applied in the same order. Only
  the *outermost* container changes from CherryPy to Gunicorn.
- **Per-connection Oracle tuning** is added via a new
  [`oracledb_listener` module](#5-sqlalchemy-event-listener-oracle_-settings)
  that registers a SQLAlchemy `connect` event handler when the configured
  `DB_TYPE` contains `oracle`.

---

## 4. Gunicorn integration

### 4.1 New entrypoint module

A new module `grapinator/svc_gunicorn.py` replaces
`grapinator/svc_cherrypy.py`. It exposes:

- a module-level `application` WSGI callable — the fully wrapped
  middleware stack (CORS → security headers → auth → Flask app, wrapped
  by `WSGILogger`). This is what Gunicorn imports.
- a `main()` function used only for the `--check-config` smoke test (it
  builds `application`, logs the resolved settings, and exits 0). The
  module is never executed directly in production.

Gunicorn is launched from a shell wrapper (and from
[docker/resources/grapinator_service.sh](../docker/resources/grapinator_service.sh)):

```sh
exec gunicorn \
    --config /opt/grapinator/grapinator/resources/gunicorn.conf.py \
    grapinator.svc_gunicorn:application
```

### 4.2 `gunicorn.conf.py`

A bundled config file in `grapinator/resources/gunicorn.conf.py` reads
values from `grapinator.settings.settings` so that operators continue to
have a single source of truth — the encrypted INI file.

| `gunicorn.conf.py` directive | Sourced from `Settings` attribute | Notes |
|---|---|---|
| `bind` | `WSGI_SOCKET_HOST`, `WSGI_SOCKET_PORT` | e.g. `127.0.0.1:8443` or `unix:/run/grapinator.sock` |
| `workers` | `GUNICORN_WORKERS` *(new)* | Default: `2 * CPU + 1` |
| `threads` | `GUNICORN_THREADS` *(new)* | Replaces `WSGI_THREAD_POOL`; default `8` |
| `worker_class` | `GUNICORN_WORKER_CLASS` *(new)* | Default: `gthread` |
| `worker_connections` | `GUNICORN_WORKER_CONNECTIONS` *(new)* | Only used with async workers |
| `timeout` | `GUNICORN_TIMEOUT` *(new)* | Default `30` s — must exceed worst-case Oracle query |
| `graceful_timeout` | `WSGI_SHUTDOWN_TIMEOUT` *(reused)* | Existing key, repurposed |
| `keepalive` | `GUNICORN_KEEPALIVE` *(new)* | Default `5` s — short keepalive behind Nginx |
| `backlog` | `WSGI_SOCKET_QUEUE_SIZE` *(reused)* | Existing key, repurposed |
| `limit_request_line` | `GUNICORN_LIMIT_REQUEST_LINE` *(new)* | Default `8190` |
| `limit_request_field_size` | `GUNICORN_LIMIT_REQUEST_FIELD_SIZE` *(new)* | Default `8190` |
| `max_requests` | `GUNICORN_MAX_REQUESTS` *(new)* | Worker auto-recycle, default `1000` |
| `max_requests_jitter` | `GUNICORN_MAX_REQUESTS_JITTER` *(new)* | Default `100` |
| `accesslog` | always `-` (stdout) | so Docker / journald pick it up |
| `errorlog` | always `-` (stderr) | |
| `proc_name` | always `grapinator` | |

`worker_class` is fixed at `gthread` for 2.1.12 (per
[§11 decision #3](#11-resolved-decisions)) — Grapinator's resolvers
make blocking calls into SQLAlchemy / `oracledb` (thin mode), so a
threaded model is the simplest correct choice and avoids the
workers-equal-threads connection-pool inflation that the `sync` worker
would force. The `GUNICORN_WORKER_CLASS` key is still exposed for
future flexibility, but `gunicorn.conf.py` rejects any value other than
`gthread` (or `sync` for single-developer debugging) with a clear boot
error. Async workers (`gevent` / `uvloop`) are explicitly **not
supported** in this release because `oracledb` thin mode does not
cooperate with monkey-patched sockets, and exposing that option would
foot-gun operators.

### 4.3 Worker / thread / connection-pool sizing rule

The single most important sizing relationship for Grapinator is:

```
   total_db_connections_needed  =  workers * threads
   DB_POOL_SIZE                 ≥  threads
```

Each worker process gets its own SQLAlchemy engine and therefore its own
connection pool, so `DB_POOL_SIZE` is **per worker, not global**. A
deployment with `workers=4`, `threads=8`, `DB_POOL_SIZE=8` therefore
opens up to `4 * 8 = 32` Oracle sessions at steady state, plus burst
overflow from `DB_POOL_MAX_OVERFLOW`. The DBA must size the Oracle
session limit accordingly.

This relationship will be documented prominently in
[docs/grapinator_ini.md](grapinator_ini.md) as part of the doc refactor.

### 4.4 Pre-fork engine handling

`create_engine` is called once at import time in
[grapinator/model.py](../grapinator/model.py). Under Gunicorn the
import happens in the **parent process before forking**, which means the
default behaviour would have all worker children inherit (and share) the
same underlying TCP connections in the pool — a known anti-pattern that
causes `ORA-03113` and corrupted session state.

The fix uses Gunicorn's `post_fork` hook:

```python
# in gunicorn.conf.py
def post_fork(server, worker):
    from grapinator.model import engine
    engine.dispose()
```

`engine.dispose()` discards the pool without closing the underlying
DBAPI connections (they were never opened in the parent — only the pool
objects exist until first checkout). After dispose, the worker's first
request lazily creates fresh connections inside the worker process.

This will be tested in `tests/test_gunicorn_config.py` (see §7).

### 4.5 Removed dependencies

- `cherrypy>=18.10.0` is removed from
  [setup.cfg](../setup.cfg) `install_requires`.

### 4.6 Added dependencies

- `gunicorn>=23.0.0` is added to `install_requires`. (23.x is the first
  release with the security fixes for CVE-2024-1135 request smuggling.)

---

## 5. SQLAlchemy event listener — `ORACLE_*` settings

### 5.1 Motivation

`python-oracledb` thin mode exposes per-connection knobs that cannot be
configured through SQLAlchemy's `create_engine` kwargs because they are
attributes of the DBAPI **connection** object, not the URI. The most
important of these is `connection.call_timeout` — the maximum
wall-clock time, in milliseconds, that any single Oracle round-trip
(parse, execute, fetch) is allowed to take before `oracledb` raises
`DPI-1067`. Without it, a single bad query or a stalled network path
can wedge a Gunicorn worker thread indefinitely, eventually starving
the pool and triggering Gunicorn's hard `timeout` kill.

### 5.2 Design

A new module `grapinator/oracle_listener.py` exposes:

```python
def register(engine, settings) -> None:
    """Attach a SQLAlchemy `connect` event listener that applies ORACLE_*
    settings to every new DBAPI connection. No-op when DB_TYPE does not
    contain 'oracle'."""
```

`grapinator/model.py` will call `register(engine, settings)` immediately
after `create_engine(...)`. The listener uses
`sqlalchemy.event.listens_for(engine, "connect")`, so it fires once per
**physical** Oracle session (i.e. when the pool opens a new connection,
not on every checkout). This matches the lifetime of the per-connection
settings being configured.

### 5.3 Listener behaviour

Inside the listener, for each `ORACLE_*` value present and non-`None`
on `settings`, the corresponding attribute is set on the raw DBAPI
connection:

| INI key (`[SQLALCHEMY]`) | Maps to | Default | Notes |
|---|---|---|---|
| `ORACLE_CALL_TIMEOUT` | `connection.call_timeout` (ms) | **`15000` (15 s)** | **Mandatory and always applied when `DB_TYPE` contains `oracle`** (per [§11 decision #5](#11-resolved-decisions)). If the key is omitted from `grapinator.ini` the default of `15000` ms is applied silently and an `INFO` line is logged so operators can see the effective value. Must be shorter than `GUNICORN_TIMEOUT` (default `30 s`) so `oracledb` raises `DPI-1067` *before* Gunicorn force-kills the worker. Setting `0` is rejected at boot with an `ERROR` — disabling the timeout is no longer a supported configuration. |
| `ORACLE_STMTCACHESIZE` | `connection.stmtcachesize` | `20` (oracledb default) | Increase for workloads with many distinct queries (e.g. `100`). |
| `ORACLE_AUTOCOMMIT` | `connection.autocommit` | `False` | Grapinator is read-only, but leaving this `False` keeps SQLAlchemy's transaction semantics consistent. |
| `ORACLE_MODULE` | `connection.module` | `grapinator` | Surfaces in `V$SESSION.MODULE` for DBA observability. |
| `ORACLE_ACTION` | `connection.action` | unset | Optional finer-grained tag in `V$SESSION.ACTION`. |
| `ORACLE_CLIENT_IDENTIFIER` | `connection.client_identifier` | unset | Optional; populated from a callable hook in a future release. |
| `ORACLE_CURRENT_SCHEMA` | `connection.current_schema` | unset | If set, applies `ALTER SESSION SET CURRENT_SCHEMA=…`. |

Only keys that are non-`None` are written, mirroring the `has_option`
pattern already used throughout `settings.py`. All keys are **optional**
and load only inside `if 'oracle' in self.DB_TYPE:` so SQLite/MySQL
deployments are unaffected.

### 5.4 Error handling

If applying any `ORACLE_*` value raises (e.g. unsupported attribute on
an older `oracledb`), the listener:

1. Logs the failure at `WARNING` level with the attribute name and the
   exception message — **never** the connection string.
2. Continues with the remaining `ORACLE_*` keys.
3. Does **not** raise, so a single typo or version mismatch cannot
   prevent the service from booting.

`ORACLE_CALL_TIMEOUT` is the one exception. It is mandatory for Oracle
deployments, and the listener treats it accordingly:

- Failure to apply it (e.g. `oracledb` version too old to expose the
  attribute) is logged at `ERROR` level and the connection is closed
  before being returned to the pool. The next request retries; if the
  problem is persistent the operator sees a steady stream of `ERROR`
  log lines and the pool stays empty rather than silently running
  without a timeout.
- The validation that `0 < ORACLE_CALL_TIMEOUT < GUNICORN_TIMEOUT * 1000`
  is performed at INI-load time in `settings.py` (not in the listener),
  so misconfigurations fail at boot rather than at first request.

### 5.5 Class-level defaults in `Settings`

Seven new class-level attributes will be added to `Settings`:

```python
ORACLE_CALL_TIMEOUT       = 15000   # ms; mandatory for Oracle, default value applied if INI omits the key
ORACLE_STMTCACHESIZE      = None
ORACLE_AUTOCOMMIT         = None
ORACLE_MODULE             = 'grapinator'
ORACLE_ACTION             = None
ORACLE_CLIENT_IDENTIFIER  = None
ORACLE_CURRENT_SCHEMA     = None
```

`ORACLE_CALL_TIMEOUT` is the only key with a non-`None` numeric
default, reflecting its mandatory status. The loader in `settings.py`
additionally enforces (when `'oracle' in DB_TYPE`):

- `ORACLE_CALL_TIMEOUT > 0` — `0` and negative values raise
  `RuntimeError` at boot.
- `ORACLE_CALL_TIMEOUT < GUNICORN_TIMEOUT * 1000` — violations raise
  `RuntimeError` at boot with a message naming both keys.

The existing `ORCL_NLS_LANG` / `ORCL_NLS_DATE_FORMAT` keys are
**retained unchanged** for backwards compatibility — they configure
the process-level `NLS_*` environment variables, not per-connection
state, and so do not fit the listener model. They will be documented
alongside the new `ORACLE_*` keys for discoverability.

---

## 6. Nginx reverse-proxy recommendations

Nginx fronts Grapinator as an API gateway. The recommended settings
below are tuned for "many requests per second, mostly short GraphQL
queries". They will be published as a self-contained
`docs/nginx.md` reference and referenced from
[docs/grapinator_ini.md](grapinator_ini.md).

### 6.1 Upstream block

```nginx
upstream grapinator {
    # One server line per Gunicorn instance. Grapinator ships as one
    # container per host running a single Gunicorn with N workers,
    # so only one upstream entry is needed (per §11 decision #1).
    server unix:/run/grapinator/grapinator.sock fail_timeout=0;

    # Keep persistent connections from Nginx to Gunicorn so that
    # request-rate spikes don't pay TCP handshake cost.
    keepalive 64;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}
```

A unix-domain socket is preferred over a TCP loopback bind: lower
syscall overhead, no ephemeral-port exhaustion, and no risk of an
accidental external bind. The bundled `grapinator.ini` files keep a
TCP loopback default (per [§11 decision #2](#11-resolved-decisions)) so
that local-dev workflows continue to work without Nginx; operators
opting in to socket binding follow [§6.5](#65-unix-domain-socket-setup-recommended-for-production).

### 6.2 Server block

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.org;

    # ── TLS (terminated here, not in Gunicorn) ────────────────────────
    ssl_certificate     /etc/nginx/tls/api.crt;
    ssl_certificate_key /etc/nginx/tls/api.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;

    # ── Connection / request limits ───────────────────────────────────
    client_max_body_size      1m;     # match WSGI_MAX_REQUEST_BODY_SIZE
    client_body_buffer_size   16k;
    large_client_header_buffers 4 8k;

    # ── Timeouts (upstream Gunicorn timeout = 30s) ────────────────────
    proxy_connect_timeout 5s;
    proxy_send_timeout    30s;
    proxy_read_timeout    30s;
    send_timeout          30s;

    # ── Rate limiting (defined at http {} scope, see §6.3) ────────────
    limit_req      zone=grapinator_rps burst=50 nodelay;
    limit_conn     grapinator_conn 20;

    # ── Logging ───────────────────────────────────────────────────────
    access_log /var/log/nginx/grapinator.access.log main buffer=64k flush=5s;
    error_log  /var/log/nginx/grapinator.error.log warn;

    # ── Reverse proxy to Gunicorn ─────────────────────────────────────
    location /northwind/gql {           # match FLASK_API_ENDPOINT
        proxy_pass http://grapinator;
        proxy_http_version 1.1;
        proxy_set_header   Connection         "";   # enable keepalive
        proxy_set_header   Host               $host;
        proxy_set_header   X-Real-IP          $remote_addr;
        proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto  $scheme;

        # Disable buffering for GraphQL response bodies — they are
        # small and we want them streamed straight to the client.
        proxy_buffering    off;
        proxy_request_buffering on;     # fully buffer requests so
                                        # slow uploads don't hold a
                                        # Gunicorn worker thread
    }

    # Health probe — served entirely by Nginx, never proxied to
    # Grapinator. This is intentional: in 2.1.12 Grapinator does NOT
    # implement /healthz / /livez / /readyz routes (per §11 decision #4,
    # those are deferred to a future release). The static 200 here lets
    # external load balancers and orchestrators probe the Nginx tier
    # without any backend dependency.
    location = /healthz {
        access_log off;
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }
}
```

### 6.3 `http {}` block — rate-limit zones and worker tuning

```nginx
# Place at http {} scope (typically /etc/nginx/nginx.conf).

# One zone per client IP, 100 req/s sustained.
limit_req_zone   $binary_remote_addr  zone=grapinator_rps:10m  rate=100r/s;
limit_conn_zone  $binary_remote_addr  zone=grapinator_conn:10m;

# Worker count = CPU cores; high open-file limit for many keepalive
# connections.
worker_processes      auto;
worker_rlimit_nofile  65535;

events {
    worker_connections 8192;
    multi_accept       on;
    use                epoll;     # Linux
}

# Hide nginx version from responses.
server_tokens off;
```

### 6.4 Sizing summary

| Layer | Limit | Recommended value | Comment |
|---|---|---|---|
| Nginx | `worker_connections` | `8192` | per worker process |
| Nginx | `limit_req` zone rate | `100r/s` | per source IP |
| Nginx | `limit_req` burst | `50` | accept short spikes |
| Nginx | `limit_conn` | `20` | concurrent conns per IP |
| Nginx → Gunicorn | `keepalive` | `64` | persistent conns to upstream |
| Gunicorn | `workers` | `2 * CPU + 1` | per host |
| Gunicorn | `threads` (gthread) | `8` | per worker |
| Gunicorn | `timeout` | `30s` | > `ORACLE_CALL_TIMEOUT` |
| Oracle | sessions | `≥ workers * threads + headroom` | DBA-coordinated |

With those numbers a 4-core host running one Gunicorn instance accepts
roughly `9 workers * 8 threads = 72` concurrent in-flight requests
before queueing, and Nginx caps any single misbehaving client at
`100 req/s` with a `50`-request burst window.

### 6.5 Unix-domain socket setup (recommended for production)

A unix-domain socket gives slightly lower syscall overhead than TCP
loopback, sidesteps ephemeral-port exhaustion under heavy keepalive
churn, and removes any risk of an accidental external bind. The
bundled INI files default to TCP loopback (so `python -m grapinator …`
still works on a developer laptop without Nginx); operators move to a
socket bind by following these steps. This material will be published
verbatim as a section of the new `docs/gunicorn.md` and cross-linked
from `docs/nginx.md`.

**Step 1 — choose a socket path and create its parent directory.**
A dedicated directory keeps permissions narrow and survives `tmpfs`
remounts:

```sh
sudo install -d -o grapinator -g www-data -m 0750 /run/grapinator
```

Use `/run/grapinator/grapinator.sock` rather than `/run/grapinator.sock`
directly so the socket file inherits the directory's `0750` ACL — only
the Nginx user (`www-data` here) can `connect()` to it.

**Step 2 — point Grapinator at the socket.** In `grapinator.ini`:

```ini
[WSGI]
# Unix-socket bind. WSGI_SOCKET_HOST carries the literal token
# `unix:` followed by the absolute socket path; WSGI_SOCKET_PORT
# is then ignored. The gunicorn.conf.py loader recognises the
# `unix:` prefix and emits `bind = "unix:/run/grapinator/grapinator.sock"`.
WSGI_SOCKET_HOST = unix:/run/grapinator/grapinator.sock
WSGI_SOCKET_PORT = 0
```

**Step 3 — set the socket file permissions in `gunicorn.conf.py`.**
Gunicorn creates the socket on `bind`; the bundled config sets
`umask = 0o007` so the resulting socket is mode `0660` and only the
`grapinator` user (owner) and the `www-data` group can use it:

```python
# in grapinator/resources/gunicorn.conf.py
umask = 0o007
```

**Step 4 — tell Nginx to use the socket.** Match the upstream block
in [§6.1](#61-upstream-block):

```nginx
upstream grapinator {
    server unix:/run/grapinator/grapinator.sock fail_timeout=0;
    keepalive 64;
}
```

**Step 5 — confirm SELinux / AppArmor.** On RHEL-family hosts with
SELinux enforcing, Nginx needs `httpd_can_network_connect` (or a
targeted file context on the socket dir):

```sh
sudo setsebool -P httpd_can_network_connect 1
sudo chcon -Rt httpd_var_run_t /run/grapinator
```

**Container deployment note.** When Grapinator and Nginx run in
separate containers on the same host, mount the socket directory as a
shared volume (`-v /run/grapinator:/run/grapinator`) into both
containers and ensure the `grapinator` UID inside the app container
matches the directory owner on the host. The Grapinator Dockerfile
leaves a TCP bind as the default so the image works standalone; the
socket path is opt-in via a mounted `grapinator.ini` override.

---

## 7. Unit test changes

### 7.1 Tests to remove

| File / class | Reason for removal |
|---|---|
| `tests/test_flask_app.py::TestSecurityHeadersMiddleware` — `cherrypy` import paths | The middleware classes themselves stay, but tests must `import` them from the new `grapinator.svc_gunicorn` module (which re-exports them) or, better, from a new `grapinator.middleware` module. |
| Any test that imports `cherrypy` directly | None today, but a regression test will be added (§7.3) to enforce this. |

The `SecurityHeadersMiddleware` and `CorsMiddleware` classes themselves
are **not** CherryPy-specific (they are plain WSGI middleware) and will
be moved verbatim from `svc_cherrypy.py` to a new
`grapinator/middleware.py` module. All existing assertions for header
content, CORS preflight short-circuiting, and credentials handling are
preserved.

### 7.2 Tests to add

| New test file | Coverage |
|---|---|
| `tests/test_gunicorn_config.py` | Asserts `gunicorn.conf.py` resolves `bind`, `workers`, `threads`, `timeout`, `graceful_timeout`, `keepalive`, `max_requests` from `Settings`. Asserts `post_fork` calls `engine.dispose()` (mocked engine). Asserts the `bind` value is rewritten correctly when `WSGI_SOCKET_HOST` starts with `unix:` (§6.5). Asserts `worker_class` other than `gthread` / `sync` is rejected at config-load time (§4.2). |
| `tests/test_svc_gunicorn.py` | Imports `application`, checks the middleware order via `type(application.app.app...).__name__` introspection (same pattern used today for `SecurityHeadersMiddleware`), and verifies that `BearerAuthMiddleware` is inserted only when `AUTH_MODE != 'off'`. |
| `tests/test_oracle_listener.py` | With a stub engine + stub DBAPI connection, asserts that the `connect` listener applies each `ORACLE_*` value, skips `None` values, logs (does not raise) on attribute errors for non-call-timeout keys, and is a no-op when `DB_TYPE` is not Oracle. Includes an explicit case that `ORACLE_CALL_TIMEOUT` defaults to `15000` ms when the INI omits the key and `DB_TYPE` contains `oracle`, and that `ORACLE_CALL_TIMEOUT = 0` or `ORACLE_CALL_TIMEOUT >= GUNICORN_TIMEOUT * 1000` raises at boot. |
| `tests/test_no_cherrypy_imports.py` | Walks every `.py` file under `grapinator/` and asserts `import cherrypy` and `from cherrypy` are absent. Prevents a future regression. |

### 7.3 Tests to update (non-removal)

| File | Update |
|---|---|
| `tests/test_flask_app.py` | Change `from grapinator.svc_cherrypy import SecurityHeadersMiddleware, CorsMiddleware` to `from grapinator.middleware import …`. No behavioural assertions change. |
| `tests/test_bearer_auth.py` | No changes — the auth middleware is WSGI-server-agnostic. |
| `tests/test_settings_class.py` | Add cases for the eight new `ORACLE_*` settings (defaults, override from INI) and the new `GUNICORN_*` settings. |

---

## 8. Documentation refactor

### 8.1 Files to update

| File | Change |
|---|---|
| [README.md](../README.md) | Replace "production WSGI server: CherryPy" sentence and the "running unit tests" example. Add a "Running in production" quick-start section that uses `gunicorn`. |
| [docs/grapinator_ini.md](grapinator_ini.md) | Rewrite `[WSGI]` section: deprecate `WSGI_SSL_CERT` / `WSGI_SSL_PRIVKEY`, repurpose `WSGI_SOCKET_QUEUE_SIZE` → Gunicorn `backlog`, `WSGI_SHUTDOWN_TIMEOUT` → Gunicorn `graceful_timeout`, `WSGI_MAX_REQUEST_BODY_SIZE` (now enforced by Nginx, not Gunicorn — note this). Remove `WSGI_THREAD_POOL` in favour of `GUNICORN_THREADS`. Add a new `[SQLALCHEMY]` subsection documenting all eight `ORACLE_*` keys. |
| `docs/nginx.md` *(new)* | Full reverse-proxy recipe from §6 with annotated configs for: (a) localhost dev, (b) single-host Docker, (c) HA deployment with Nginx in front of multiple Grapinator hosts. Cross-links to the unix-socket setup in `docs/gunicorn.md`. |
| `docs/gunicorn.md` *(new)* | How Gunicorn is wired into Grapinator: the entrypoint module, the bundled `gunicorn.conf.py`, the worker/thread sizing rule, the `post_fork` engine dispose, signal handling, and operational runbook (graceful reload via `SIGHUP`, single-worker reload via `SIGTERM`, log rotation, etc.). Includes the full unix-domain socket setup from [§6.5](#65-unix-domain-socket-setup-recommended-for-production) with the per-step ownership, umask, SELinux, and shared-volume guidance. |
| [docker/Dockerfile.alpine](../docker/Dockerfile.alpine) | No source change in this design phase, but the doc will note that the Dockerfile must add the `gunicorn` install step alongside `pip install -e .` and that the `EXPOSE 8443` line moves to a `127.0.0.1:8443` bind (or socket). |
| [docker/resources/grapinator_service.sh](../docker/resources/grapinator_service.sh) | Documented to call `gunicorn` with the bundled config instead of `python grapinator/svc_cherrypy.py`. |
| [CHANGELOG.md](../CHANGELOG.md) | New `## [2.1.12]` entry summarizing all of the above under **Changed**, **Added**, **Removed**, and **Deprecated**. |
| [docs/oidc.md](oidc.md) | One-line correction: "the WSGI server (Gunicorn)…" — auth behaviour itself does not change. |

### 8.2 Files **not** changed

- [docs/schema_docs.md](schema_docs.md)
- [docs/demo_queries.md](demo_queries.md)
- [docs/graphiql_user_guide.md](graphiql_user_guide.md)
- [db/](../db/)
- [gql-tester/](../gql-tester/) — the external test runner is unaffected.

---

## 9. Backwards compatibility & migration

### 9.1 Behavioural guarantees

- The GraphQL endpoint URL, request/response shapes, security headers,
  CORS behaviour, GraphiQL UI, auth modes, and INI encryption all
  remain bit-for-bit identical for any well-configured deployment.
- A deployment that upgrades to 2.1.12 without changing its INI file
  but **does** swap its entrypoint from `svc_cherrypy.py` to
  `gunicorn grapinator.svc_gunicorn:application` will see equivalent
  behaviour, with three exceptions:
  1. TLS will not be terminated by Grapinator anymore. If
     `WSGI_SSL_CERT` is set, Grapinator logs a `WARNING` at boot but
     starts cleanly on plain HTTP — the operator must put Nginx (or
     another terminator) in front.
  2. Worker count is now `2 * CPU + 1` rather than `1`. CPU and memory
     usage on the host will rise proportionally. This is called out
     prominently in the release notes.
  3. Oracle deployments that previously had no `call_timeout` set
     will now have one applied (default `15000` ms). Any single Oracle
     round-trip that exceeds 15 s will raise `DPI-1067` and surface as
     a GraphQL error instead of silently consuming a worker thread.
     Operators with legitimately long-running queries must raise
     `ORACLE_CALL_TIMEOUT` (and `GUNICORN_TIMEOUT`) explicitly.

### 9.2 INI key transition table

| 2.1.11 key | 2.1.12 status | Replacement / note |
|---|---|---|
| `WSGI_SOCKET_HOST` | kept | unchanged |
| `WSGI_SOCKET_PORT` | kept | unchanged |
| `WSGI_SSL_CERT` | **deprecated** | TLS in Nginx; ignored with warning |
| `WSGI_SSL_PRIVKEY` | **deprecated** | TLS in Nginx; ignored with warning |
| `WSGI_THREAD_POOL` | **removed** | Use `GUNICORN_THREADS` |
| `WSGI_SOCKET_QUEUE_SIZE` | repurposed | Now passes through to Gunicorn `backlog` |
| `WSGI_MAX_REQUEST_BODY_SIZE` | **deprecated** | Enforced by Nginx `client_max_body_size` |
| `WSGI_SHUTDOWN_TIMEOUT` | repurposed | Now passes through to Gunicorn `graceful_timeout` |
| `WSGI_ACCEPTED_QUEUE_SIZE` | **removed** | No Gunicorn equivalent |
| *(new)* `GUNICORN_WORKERS` | added | |
| *(new)* `GUNICORN_THREADS` | added | |
| *(new)* `GUNICORN_WORKER_CLASS` | added | |
| *(new)* `GUNICORN_TIMEOUT` | added | |
| *(new)* `GUNICORN_KEEPALIVE` | added | |
| *(new)* `GUNICORN_MAX_REQUESTS` | added | |
| *(new)* `GUNICORN_MAX_REQUESTS_JITTER` | added | |
| *(new)* `GUNICORN_LIMIT_REQUEST_LINE` | added | |
| *(new)* `GUNICORN_LIMIT_REQUEST_FIELD_SIZE` | added | |
| *(new)* `ORACLE_CALL_TIMEOUT` | added | ms; **mandatory** when `DB_TYPE` contains `oracle`; default `15000` applied silently if absent; `0` rejected at boot |
| *(new)* `ORACLE_STMTCACHESIZE` | added | |
| *(new)* `ORACLE_AUTOCOMMIT` | added | |
| *(new)* `ORACLE_MODULE` | added | default `grapinator` |
| *(new)* `ORACLE_ACTION` | added | |
| *(new)* `ORACLE_CLIENT_IDENTIFIER` | added | |
| *(new)* `ORACLE_CURRENT_SCHEMA` | added | |
| existing `ORCL_NLS_LANG` | kept | unchanged (process-level env var) |
| existing `ORCL_NLS_DATE_FORMAT` | kept | unchanged (process-level env var) |

### 9.3 Removed keys — boot-time handling

When `WSGI_THREAD_POOL` or `WSGI_ACCEPTED_QUEUE_SIZE` is present in the
INI file, `settings.py` logs an `ERROR` and exits with a non-zero status
*before* attempting to start the server. This is a hard error rather
than a warning because silently dropping a thread-pool sizing setting
would leave operators with a much hotter box than they expected.

---

## 10. Implementation plan (out of scope for this document)

Sequenced for the implementation PR(s):

1. Extract `SecurityHeadersMiddleware` and `CorsMiddleware` into
   `grapinator/middleware.py`. Re-export from `svc_cherrypy.py` to
   keep tests green during the transition.
2. Add `Settings` attributes for `ORACLE_*` and `GUNICORN_*` keys
   (with `has_option` loaders). Update `tests/test_settings_class.py`.
3. Add `grapinator/oracle_listener.py` + register call in `model.py`.
   Add `tests/test_oracle_listener.py`.
4. Add `grapinator/svc_gunicorn.py` and
   `grapinator/resources/gunicorn.conf.py`. Add
   `tests/test_gunicorn_config.py` and `tests/test_svc_gunicorn.py`.
5. Update `setup.cfg` — remove `cherrypy`, add `gunicorn>=23.0`.
6. Delete `grapinator/svc_cherrypy.py`. Add
   `tests/test_no_cherrypy_imports.py` regression test.
7. Update `docker/resources/grapinator_service.sh` and (in a separate
   PR) `docker/Dockerfile.alpine`.
8. Documentation refactor (§8).
9. CHANGELOG entry, version bump to `2.1.12` in
   [setup.cfg](../setup.cfg).

Each step is independently mergeable behind the previous one; only step
6 is a true breaking change for downstream users.

---

## 11. Resolved decisions

The five open questions from the initial draft were resolved on
[issue #33](https://github.com/NatLabRockies/grapinator/issues/33). The
resolutions are recorded here so the spec is self-contained and
citeable.

1. **Workers per host vs. containers per host — resolved: one
   container, N workers.** Grapinator continues to ship as a single
   container per host, running one Gunicorn instance with
   `GUNICORN_WORKERS` worker processes. This matches today's
   deployment model, keeps the Nginx upstream block to a single
   `server` line, and avoids the operational overhead of container
   orchestration purely for worker isolation.
2. **Unix socket vs. TCP loopback bind — resolved: keep TCP loopback
   as the default in bundled INI files; document the unix-socket
   setup as the recommended production path.** The bundled
   `grapinator.ini`, `grapinator_rbac.ini`, and
   `grapinator_rbac_keycloakdev.ini` files keep `WSGI_SOCKET_HOST =
   127.0.0.1` so a developer can run Grapinator standalone without
   needing Nginx or socket-permission setup. The full unix-socket
   recipe — directory ownership, `umask`, SELinux contexts, and
   shared-volume guidance for split Grapinator/Nginx containers —
   is published as [§6.5](#65-unix-domain-socket-setup-recommended-for-production)
   and republished in `docs/gunicorn.md`.
3. **`gthread` vs. `sync` workers — resolved: `gthread` (fixed).**
   `GUNICORN_WORKER_CLASS` defaults to `gthread` and
   `gunicorn.conf.py` rejects any value other than `gthread` or
   `sync` (the latter retained only for single-developer debugging
   sessions where thread-safety bisecting is needed). Async workers
   (`gevent`, `uvloop`) are explicitly unsupported because
   `oracledb` thin mode does not cooperate with monkey-patched
   sockets.
4. **Health-check endpoint — resolved: deferred to a future release.**
   Grapinator 2.1.12 will **not** ship `/healthz`, `/livez`, or
   `/readyz` routes. A follow-on release will introduce all three
   together as a coherent Kubernetes-style probe set with documented
   semantics (`/livez` = process up, `/readyz` = ready to serve =
   DB pool reachable + schema loaded, `/healthz` = compound).
   In the meantime the Nginx config in [§6.2](#62-server-block)
   provides a static `/healthz` served entirely by Nginx so external
   load balancers and orchestrators have a probe target — this is
   intentional and documented as such in `docs/nginx.md`.
5. **`ORACLE_CALL_TIMEOUT` mandatory or optional — resolved:
   mandatory, with a sensible default applied silently.** When
   `DB_TYPE` contains `oracle` the listener always applies a
   `connection.call_timeout`. If the INI omits `ORACLE_CALL_TIMEOUT`
   the class-level default of `15000` ms (15 s) is used and an
   `INFO` line is logged so operators can see the effective value.
   `ORACLE_CALL_TIMEOUT = 0` (the "disable timeout" oracledb idiom)
   and any value `>= GUNICORN_TIMEOUT * 1000` are both rejected at
   boot with a `RuntimeError`. The default of `15000` ms sits
   comfortably below the default `GUNICORN_TIMEOUT = 30 s` so the
   shipped configuration is internally consistent.

No further design questions are outstanding. Implementation can begin
from the sequenced plan in [§10](#10-implementation-plan-out-of-scope-for-this-document).

---

## 12. Non-goals

- No change to the GraphQL schema, the schema dictionary format, or
  the dynamic ORM-class construction in `grapinator/model.py`.
- No change to the auth subsystem (`grapinator/auth.py`,
  `grapinator/schema.py` RBAC checks).
- No change to the `gql-tester/` sub-project.
- No new IdP support; OIDC behaviour is unchanged.
- No move to async SQLAlchemy / `oracledb` async mode. Threaded
  blocking I/O remains the model.
- No HTTP/2 or HTTP/3 termination inside Grapinator — those are
  Nginx-side concerns.
- No Grapinator-implemented `/healthz`, `/livez`, or `/readyz`
  endpoints in 2.1.12. These are deferred to a future release that
  will introduce all three together with documented Kubernetes-style
  semantics (per [§11 decision #4](#11-resolved-decisions)). The
  Nginx `/healthz` location in [§6.2](#62-server-block) is a static
  200 served by Nginx itself — it does **not** proxy to Grapinator.
