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
2. **Add a SQLAlchemy `connect` event listener** that applies per-dialect
   per-connection knobs to every connection checked out of the
   SQLAlchemy pool. The listener dispatches by `engine.dialect.name`,
   with helpers for Oracle, PostgreSQL, MySQL, and MSSQL. INI keys are
   dialect-prefixed (`ORACLE_*`, `POSTGRES_*`, `MYSQL_*`, `MSSQL_*`)
   because the underlying driver mechanisms differ too much to abstract
   cleanly. In 2.1.12 only the Oracle branch is non-empty — most
   importantly applying `python-oracledb`'s thin-mode `call_timeout`;
   the PostgreSQL / MySQL / MSSQL branches ship as documented no-op
   stubs ready to be filled in by follow-on releases.
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

Nginx and Grapinator are deployed on **separate hosts**. Nginx runs
on a dedicated API-gateway machine (machine A); Grapinator runs
inside a Docker container on a separate application machine
(machine B). The two communicate over a private TCP network —
typically a VPC subnet, a private VLAN, or a VPN / WireGuard
overlay. Nothing in the design assumes the two hosts share a
filesystem, a loopback interface, or a network namespace.

```
  ┌─ Machine A (Nginx host) ────────────┐         ┌─ Machine B (Docker host) ─────────────┐
  │                                     │         │  ┌─ grapinator container ──────────┐ │
  │  Nginx (API gateway)                │   TCP   │  │ Gunicorn (gthread)              │ │
  │  • TLS termination                  │ ──────▶ │  │ ──────────────────────────────  │ │
  │  • Rate & connection limits         │ private │  │  Per worker process:            │ │
  │  • Real-IP / proto forwarding       │ network │  │    WSGILogger                   │ │
  │  • Upstream keepalive               │ (VPC /  │  │      SecurityHeadersMiddleware  │ │
  │  • Passive upstream health checks   │  VPN)   │  │        CorsMiddleware           │ │
  │                                     │         │  │          BearerAuthMiddleware   │ │
  │                                     │         │  │            Flask app            │ │
  └─────────────────────────────────────┘         │  └─────────────────────────────────┘ │
                                                  └───────────────────────────────────────┘
```

Key changes vs. baseline:

- **HTTP transport** is owned by Gunicorn. CherryPy is removed entirely
  from the runtime dependency set.
- **Cross-host deployment is the canonical topology.** The Nginx host
  and the Grapinator host(s) are independent virtual or physical
  machines connected by a private TCP network. Unix-domain sockets
  between Nginx and Gunicorn are therefore **not supported** in the
  canonical topology (per [§11 decision #2](#11-resolved-decisions)).
- **Deployment unit** is one Docker container per application host
  running a single Gunicorn instance with `N` workers (per
  [§11 decision #1](#11-resolved-decisions)). Multiple application
  hosts can sit behind one Nginx via additional `server` entries in
  the upstream block ([§6.1](#61-upstream-block)).
- **TLS termination** happens at Nginx on machine A. Between Nginx and
  Gunicorn the traffic is plain HTTP/1.1 over the private network by
  default (optional `stunnel` / sidecar upstream TLS is described in
  [§6.5](#65-network-security-between-nginx-and-grapinator)). Gunicorn
  must therefore bind to a network interface that machine A can
  reach. The bundled INI files keep `WSGI_SOCKET_HOST = 127.0.0.1`
  so a developer can run Grapinator standalone without exposing it
  to the network; production operators change this to `0.0.0.0` and
  rely on the Docker private-interface port mapping plus a firewall
  rule to constrain reachability (see [§6.5](#65-network-security-between-nginx-and-grapinator)).
  TLS certificate paths in the INI file (`WSGI_SSL_CERT` /
  `WSGI_SSL_PRIVKEY`) become **deprecated**: still accepted, but
  logged with a warning that says "TLS is now terminated by Nginx;
  remove these keys".
- **The WSGI middleware stack is unchanged.** The
  `SecurityHeadersMiddleware`, `CorsMiddleware`, `BearerAuthMiddleware`,
  and `WSGILogger` classes continue to be applied in the same order. Only
  the *outermost* container changes from CherryPy to Gunicorn.
- **Per-connection dialect tuning** is added via a new
  [`db_listener` module](#5-sqlalchemy-event-listener--per-dialect-connect-settings)
  that registers a SQLAlchemy `connect` event handler and dispatches on
  `engine.dialect.name`. In 2.1.12 the Oracle branch is non-trivial;
  PostgreSQL, MySQL, and MSSQL branches ship as no-op stubs.

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
| `bind` | `WSGI_SOCKET_HOST`, `WSGI_SOCKET_PORT` | e.g. `127.0.0.1:8443` (developer laptop, no Nginx) or `0.0.0.0:8443` (Docker container exposed to the Nginx host across the private network). Unix-socket binds (`unix:/path/…`) are accepted by Gunicorn but are not part of the canonical cross-host topology (see [§11 decision #2](#11-resolved-decisions)). |
| `workers` | `GUNICORN_WORKERS` *(new)* | Default: `2 * CPU + 1` |
| `threads` | `GUNICORN_THREADS` *(new)* | Replaces `WSGI_THREAD_POOL`; default `8` |
| `worker_class` | `GUNICORN_WORKER_CLASS` *(new)* | Default: `gthread` |
| `worker_connections` | `GUNICORN_WORKER_CONNECTIONS` *(new)* | Only used with async workers |
| `timeout` | `GUNICORN_TIMEOUT` *(new)* | Default `30` s — must exceed worst-case Oracle query |
| `graceful_timeout` | `WSGI_SHUTDOWN_TIMEOUT` *(reused)* | Existing key, repurposed |
| `keepalive` | `GUNICORN_KEEPALIVE` *(new)* | Default `75` s — long enough that the Nginx upstream-keepalive pool on machine A actually reuses cross-host TCP connections (Nginx default `keepalive_timeout` is `75s`). The Gunicorn upstream default of `5s` is only appropriate for same-host loopback deployments. |
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

## 5. SQLAlchemy event listener — per-dialect `connect` settings

### 5.1 Motivation

Every SQLAlchemy backend Grapinator can target (Oracle, PostgreSQL,
MySQL, MSSQL) exposes per-connection knobs that cannot be configured
through SQLAlchemy's `create_engine` kwargs because they are
attributes — or session-level `SET` statements — on the DBAPI
**connection** object, not the URI. The proximate motivation for
2.1.12 is `python-oracledb`'s `connection.call_timeout`: the maximum
wall-clock time, in milliseconds, that any single Oracle round-trip
(parse, execute, fetch) is allowed to take before `oracledb` raises
`DPI-1067`. Without it, a single bad query or a stalled network path
can wedge a Gunicorn worker thread indefinitely, eventually starving
the pool and triggering Gunicorn's hard `timeout` kill.

PostgreSQL (`SET statement_timeout`), MySQL
(`SET SESSION MAX_EXECUTION_TIME`, SELECT-only), and MSSQL
(`SET LOCK_TIMEOUT` / `pyodbc` `cursor.timeout`) have analogous
per-query timeout knobs, plus their own analogues of
`application_name` / `module` for DBA observability and
`current_schema` / `search_path` for schema scoping. The mechanisms
differ enough across drivers — attribute set vs. SQL `SET` vs.
connect-string arg vs. per-cursor attribute — that each backend
needs its own helper rather than a single abstract interface.

### 5.2 Design

A new module `grapinator/db_listener.py` exposes:

```python
def register(engine, settings) -> None:
    """Attach a SQLAlchemy `connect` event listener that applies
    per-dialect settings to every new DBAPI connection. Dispatches by
    `engine.dialect.name` to a private `_apply_<dialect>` helper.
    Helpers for dialects with no shipped configuration in 2.1.12 are
    present as documented no-ops."""
```

`grapinator/model.py` will call `register(engine, settings)`
immediately after `create_engine(...)`. The listener uses
`sqlalchemy.event.listens_for(engine, "connect")`, so it fires once
per **physical** DBAPI session (i.e. when the pool opens a new
connection, not on every checkout). This matches the lifetime of the
per-connection settings being configured.

Inside the listener, dispatch is a plain `dict` lookup on
`engine.dialect.name`:

```python
_DIALECT_HELPERS = {
    'oracle':     _apply_oracle,
    'postgresql': _apply_postgresql,   # no-op stub in 2.1.12
    'mysql':      _apply_mysql,        # no-op stub in 2.1.12
    'mssql':      _apply_mssql,        # no-op stub in 2.1.12
    'sqlite':     _apply_noop,         # explicit no-op (used in tests)
}
```

Each helper receives `(dbapi_conn, settings)` and is responsible for
applying its own dialect-prefixed INI keys via either attribute set
(`oracledb`, `psycopg`), short `SET` SQL executed on the new
connection (`postgresql`, `mysql`, `mssql`), or connect-string args
handed off via `create_engine(... connect_args=)` (handled in
`model.py`, not in the listener). `register()` logs the selected
helper at `INFO` once at startup and at `DEBUG` on every fire.
Unknown dialect names log `WARNING` (`"no db_listener helper
registered for dialect ..."`) and fall through as a no-op so an
experimental backend never blocks startup.

**Why per-dialect prefixes rather than generic keys.** The per-query
timeout — the most useful shared concept — is implemented in four
different ways across the drivers Grapinator targets: an attribute
set in `oracledb`, a `SET statement_timeout = ...` in `psycopg`, a
`SET SESSION MAX_EXECUTION_TIME = ...` (SELECT-only) in MySQL, and a
per-cursor `cursor.timeout` (or `SET LOCK_TIMEOUT`, different
semantics) in `pyodbc`. Even where names line up the unit differs
(ms in Oracle and MySQL, seconds + interval strings in PostgreSQL).
A notional unified `DB_CALL_TIMEOUT` INI key that silently mapped to
four different runtime behaviours would be a foot-gun for operators,
so the spec keeps the prefixes honest: `ORACLE_*`, `POSTGRES_*`,
`MYSQL_*`, `MSSQL_*`. This is reinforced as a non-goal in
[§12](#12-non-goals).

### 5.3 Oracle helper — `_apply_oracle`

For Oracle deployments (`engine.dialect.name == 'oracle'`), the
helper walks each `ORACLE_*` value present and non-`None` on
`settings` and sets the corresponding attribute on the raw DBAPI
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

Only keys that are non-`None` are written, mirroring the
`has_option` pattern already used throughout `settings.py`. All
`ORACLE_*` keys are **optional** and load only inside
`if 'oracle' in self.DB_TYPE:` so non-Oracle deployments never carry
their defaults. The `_apply_postgresql`, `_apply_mysql`, and
`_apply_mssql` helpers ship as documented no-ops in 2.1.12 — the
`POSTGRES_*` / `MYSQL_*` / `MSSQL_*` namespaces are reserved for
follow-on releases that will add per-dialect knobs (likely starting
with the per-query timeout for each backend).

### 5.4 Error handling (shared across helpers)

If applying any per-dialect value raises (e.g. unsupported attribute
on an older driver, or a `SET` rejected by the server), the helper:

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

No `POSTGRES_*`, `MYSQL_*`, or `MSSQL_*` class-level attributes are
added to `Settings` in 2.1.12 — the corresponding helpers in
`db_listener.py` are no-ops. Those namespaces are reserved on the
dispatcher side so the dispatch table itself is forward-compatible,
and are documented alongside the `ORACLE_*` keys with an explicit
"reserved; not yet wired" annotation so operators are not surprised
when setting one has no effect.

---

## 6. Nginx reverse-proxy recommendations

Nginx fronts Grapinator as an API gateway and runs on a **separate
host** from Grapinator (machine A in [§3](#3-target-architecture)).
Grapinator itself runs in a Docker container on a different host
(machine B), and the two communicate over a private TCP network — a
VPC subnet, private VLAN, or a VPN / WireGuard overlay. None of the
configuration below assumes that Nginx and Grapinator share a
filesystem, a loopback interface, or a network namespace.

The recommended settings are tuned for "many requests per second,
mostly short GraphQL queries" with the cross-host network round-trip
cost factored in. They will be published as a self-contained
`docs/nginx.md` reference and cross-linked from
[docs/grapinator_ini.md](grapinator_ini.md).

### 6.1 Upstream block

```nginx
upstream grapinator {
    # One `server` entry per Grapinator host. Each Grapinator runs as
    # a single Docker container exposing one Gunicorn (with N workers)
    # on a private-network address (per §11 decision #1). Add
    # additional `server` entries to scale horizontally — Nginx will
    # round-robin across them.
    server 10.20.30.41:8443 max_fails=3 fail_timeout=10s;
    # server 10.20.30.42:8443 max_fails=3 fail_timeout=10s;
    # server 10.20.30.43:8443 max_fails=3 fail_timeout=10s;

    # Keep persistent connections from Nginx to Gunicorn so each
    # request does not pay a cross-host TCP handshake cost.
    # `keepalive` is the per-Nginx-worker idle-conn pool; total open
    # conns to each Grapinator host = nginx_workers * 64.
    keepalive          64;
    keepalive_requests 10000;
    keepalive_timeout  75s;       # must be <= GUNICORN_KEEPALIVE (75s)

    # Shared zone so all Nginx workers share `max_fails` health state.
    # Required when health-checking with `workers > 1`.
    zone grapinator_upstream 64k;
}
```

`server` entries take **routable IP addresses or DNS names**, never
unix-socket paths — Nginx and Grapinator do not share a filesystem in
the canonical topology. When using DNS names (e.g. for service
discovery), also configure `resolver` at `http {}` scope
([§6.3](#63-http--block--rate-limit-zones-and-worker-tuning)) so Nginx
re-resolves entries when Docker container IPs change.

The `max_fails` / `fail_timeout` pair gives Nginx passive health
checks: after three consecutive failures within a ten-second window,
the upstream is taken out of rotation for ten seconds. Active health
checks (the `health_check` directive) require Nginx Plus and are out
of scope; the static `/healthz` location at the Nginx tier (see
[§6.2](#62-server-block)) is for *external* probes of the gateway,
not internal probes of Grapinator.

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

    # ── Reverse proxy to Gunicorn (across the private network) ────────
    location /northwind/gql {           # match FLASK_API_ENDPOINT
        proxy_pass http://grapinator;   # upstream from §6.1
        proxy_http_version 1.1;
        proxy_set_header   Connection         "";   # enable keepalive
        proxy_set_header   Host               $host;
        proxy_set_header   X-Real-IP          $remote_addr;
        proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto  $scheme;
        proxy_set_header   X-Forwarded-Host   $host;
        proxy_set_header   X-Forwarded-Port   $server_port;

        # Disable buffering for GraphQL response bodies — they are
        # small and we want them streamed straight to the client.
        proxy_buffering    off;
        proxy_request_buffering on;     # fully buffer requests so a
                                        # slow client cannot hold a
                                        # Gunicorn worker thread on
                                        # the remote host

        # Cross-host retry policy: try the next upstream on transport
        # errors or 502/503/504 (Gunicorn worker recycled mid-request,
        # transient network blip, etc.).
        proxy_next_upstream         error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries   2;
        proxy_next_upstream_timeout 5s;
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

# Resolver for DNS-named upstream `server` entries (§6.1). Point at
# the private DNS used by your VPC / VPN; do NOT use a public resolver
# for internal service names. `valid=10s` re-resolves on a short cadence
# so Docker container restarts that change the upstream IP are picked
# up without an Nginx reload.
resolver 10.20.30.2 valid=10s ipv6=off;
resolver_timeout 5s;

# Worker count = CPU cores; high open-file limit for many keepalive
# connections to upstream Grapinator hosts and downstream clients.
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

On the host running Nginx, also widen the Linux ephemeral-port range
so the upstream-keepalive pool plus inbound client connections do not
exhaust source ports under load:

```sh
sysctl -w net.ipv4.ip_local_port_range="1024 65535"
sysctl -w net.ipv4.tcp_tw_reuse=1
```

Persist both in `/etc/sysctl.d/99-nginx-grapinator.conf`.

### 6.4 Sizing summary

| Layer | Limit | Recommended value | Comment |
|---|---|---|---|
| Nginx | `worker_connections` | `8192` | per Nginx worker process |
| Nginx | `limit_req` zone rate | `100r/s` | per source IP |
| Nginx | `limit_req` burst | `50` | accept short spikes |
| Nginx | `limit_conn` | `20` | concurrent conns per IP |
| Nginx → Grapinator | `keepalive` | `64` | persistent upstream conns *per Nginx worker*; total open conns to each Grapinator host = `nginx_workers * 64`. Keep below the Linux ephemeral-port pool on the Nginx host. |
| Nginx → Grapinator | `keepalive_timeout` | `75s` | must be `<= GUNICORN_KEEPALIVE` so the upstream end never closes a conn the gateway still thinks is alive |
| Linux (Nginx host) | `net.ipv4.ip_local_port_range` | `1024 65535` | widen the ephemeral-port pool; cross-host upstream conns plus client conns can otherwise exhaust source ports |
| Linux (Nginx host) | `net.ipv4.tcp_tw_reuse` | `1` | reuse `TIME_WAIT` sockets for outbound conns |
| Gunicorn | `bind` | `0.0.0.0:8443` | Docker container exposes the port; firewall + private-interface port mapping constrain it ([§6.5](#65-network-security-between-nginx-and-grapinator)) |
| Gunicorn | `workers` | `2 * CPU + 1` | per Grapinator host |
| Gunicorn | `threads` (gthread) | `8` | per worker |
| Gunicorn | `keepalive` (`GUNICORN_KEEPALIVE`) | `75s` | raise from upstream default `5s` for cross-host operation so Nginx upstream keepalive is effective |
| Gunicorn | `timeout` | `30s` | > `ORACLE_CALL_TIMEOUT` |
| Oracle | sessions | `≥ workers * threads * grapinator_hosts + headroom` | DBA-coordinated |

With those numbers a 4-core Grapinator host running one Gunicorn
instance accepts roughly `9 workers * 8 threads = 72` concurrent
in-flight requests before queueing per host; a single Nginx fronting
three such hosts can handle `~216` concurrent backend requests, and
Nginx caps any single misbehaving client at `100 req/s` with a `50`-
request burst window.

### 6.5 Network security between Nginx and Grapinator

The cross-host Nginx → Grapinator deployment exposes a TCP port on the
Grapinator side that must be reachable from the Nginx host but **not**
from the public internet, other tenants on the same VPC, or curious
operators on the Grapinator host's wider network. The settings below
defend that channel in depth. They will be published as a section of
the new `docs/nginx.md` and cross-referenced from `docs/gunicorn.md`.

**Step 1 — constrain the Docker port mapping to a private interface.**
The default Docker port-mapping syntax (`-p 8443:8443`) binds the host
side to `0.0.0.0`, which makes the container reachable on every
interface the host owns — including public ones. Bind to the private
interface explicitly:

```sh
docker run -d \
    --name grapinator \
    -p 10.20.30.41:8443:8443 \         # host private IP, not 0.0.0.0
    -v /etc/grapinator:/opt/grapinator/grapinator/resources:ro \
    -e GQLAPI_CRYPT_KEY="$GQLAPI_CRYPT_KEY" \
    grapinator:2.1.12
```

With this mapping the kernel refuses any incoming SYN on the public
interface before Docker, nftables, or Grapinator are involved.

**Step 2 — firewall the Grapinator port to the Nginx host(s).**
Even with a private-interface bind, an `iptables` / `nftables` rule
gives a second layer that survives an accidental `-p` change:

```sh
# nftables on the Grapinator host — allow only the Nginx host(s).
nft add rule inet filter input \
    tcp dport 8443 ip saddr 10.20.30.10 accept
nft add rule inet filter input \
    tcp dport 8443 drop
```

In cloud environments, prefer the equivalent security-group rule:
allow ingress on port 8443 from the gateway-tier security group only,
and deny everything else.

**Step 3 — isolate the path on a private network or VPN.**
Recommended options:

- Cloud VPC with private subnets and security groups: one security
  group for the gateway tier, one for the application tier; the
  application SG ingress is restricted to the gateway SG by
  reference (not by IP), so adding gateway capacity does not
  require firewall edits on the Grapinator side.
- On-premises VLAN with no route to the public internet.
- WireGuard or other host-to-host VPN when the two hosts must
  traverse an untrusted network.

**Step 4 — optional: TLS to the upstream.**
TLS between Nginx and Grapinator is *not* enabled by default in
2.1.12 because Gunicorn TLS support is being deprecated
([§3](#3-target-architecture)) and operators typically rely on the
private network as the trust boundary. When the network path crosses
an untrusted segment, put a TLS terminator such as `stunnel` or a
service-mesh sidecar in front of Gunicorn on the Grapinator host and
point Nginx at it:

```nginx
upstream grapinator {
    # stunnel listens on 8444 and forwards plain HTTP to Gunicorn:8443
    # inside the Docker host.
    server 10.20.30.41:8444 max_fails=3 fail_timeout=10s;
    keepalive 64;
}
server {
    location /northwind/gql {
        proxy_pass         https://grapinator;
        proxy_ssl_verify   on;
        proxy_ssl_trusted_certificate /etc/nginx/tls/upstream-ca.pem;
        # …
    }
}
```

Adding native TLS back into Gunicorn (i.e. revisiting the deprecation
of `WSGI_SSL_CERT`) is explicitly **out of scope** for 2.1.12 — see
[§12](#12-non-goals).

**Step 5 — real-client IP handling.**
With Nginx on a different host, every request reaching Grapinator
appears at TCP level to originate from the Nginx host's IP. The
`X-Forwarded-For`, `X-Real-IP`, `X-Forwarded-Proto`, `X-Forwarded-Host`,
and `X-Forwarded-Port` headers set in [§6.2](#62-server-block) carry
the true client metadata. Grapinator's current auth layer
([grapinator/auth.py](../grapinator/auth.py)) is IP-agnostic so no
Flask-side `ProxyFix` middleware is needed in 2.1.12. When future
work adds IP-based rate limits or audit logging on the Grapinator
side, a `werkzeug.middleware.proxy_fix.ProxyFix` wrapper will need to
sit between `BearerAuthMiddleware` and the Flask app; this is
recorded as out of scope in [§12](#12-non-goals).

**Step 6 — Docker network mode.**
Use the default bridge network on the Grapinator host. Do **not** use
`--network host` in production: it bypasses the explicit
private-interface bind in step 1 and re-exposes the container on
every host interface.

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
| `tests/test_gunicorn_config.py` | Asserts `gunicorn.conf.py` resolves `bind`, `workers`, `threads`, `timeout`, `graceful_timeout`, `keepalive`, `max_requests` from `Settings`. Asserts `post_fork` calls `engine.dispose()` (mocked engine). Asserts `bind` is rendered as `host:port` for both `127.0.0.1` (developer laptop) and `0.0.0.0` (cross-host production) values of `WSGI_SOCKET_HOST`. Asserts `worker_class` other than `gthread` / `sync` is rejected at config-load time (§4.2). Asserts the new default `GUNICORN_KEEPALIVE = 75` is applied when the INI omits the key (§4.2, §6.4). |
| `tests/test_svc_gunicorn.py` | Imports `application`, checks the middleware order via `type(application.app.app...).__name__` introspection (same pattern used today for `SecurityHeadersMiddleware`), and verifies that `BearerAuthMiddleware` is inserted only when `AUTH_MODE != 'off'`. |
| `tests/test_db_listener.py` | With a stub engine + stub DBAPI connection, asserts the dispatcher selects `_apply_oracle` for `engine.dialect.name == 'oracle'`, `_apply_postgresql` / `_apply_mysql` / `_apply_mssql` for their respective dialect names, and falls through to a logged no-op for an unknown dialect. Asserts `_apply_oracle` applies each `ORACLE_*` value, skips `None` values, and logs (does not raise) on attribute errors for non-call-timeout keys. Asserts the PostgreSQL / MySQL / MSSQL stubs are true no-ops in 2.1.12 (no attribute writes, no `SET` SQL). Includes an explicit case that `ORACLE_CALL_TIMEOUT` defaults to `15000` ms when the INI omits the key and `DB_TYPE` contains `oracle`, and that `ORACLE_CALL_TIMEOUT = 0` or `ORACLE_CALL_TIMEOUT >= GUNICORN_TIMEOUT * 1000` raises at boot. |
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
| [docs/grapinator_ini.md](grapinator_ini.md) | Rewrite `[WSGI]` section: deprecate `WSGI_SSL_CERT` / `WSGI_SSL_PRIVKEY`, repurpose `WSGI_SOCKET_QUEUE_SIZE` → Gunicorn `backlog`, `WSGI_SHUTDOWN_TIMEOUT` → Gunicorn `graceful_timeout`, `WSGI_MAX_REQUEST_BODY_SIZE` (now enforced by Nginx, not Gunicorn — note this). Remove `WSGI_THREAD_POOL` in favour of `GUNICORN_THREADS`. Add a new `[SQLALCHEMY]` subsection documenting all seven `ORACLE_*` keys plus a brief note that the `POSTGRES_*`, `MYSQL_*`, and `MSSQL_*` namespaces are reserved by the dispatcher in `db_listener.py` for follow-on releases (helpers are no-ops in 2.1.12). |
| `docs/nginx.md` *(new)* | Full reverse-proxy recipe from §6, oriented around the **cross-host** canonical topology (Nginx on machine A, Grapinator Docker container on machine B). Annotated configs for: (a) developer laptop standalone (no Nginx, TCP loopback bind), (b) cross-host production with a single Grapinator host, (c) HA deployment with Nginx in front of multiple Grapinator hosts behind one upstream block. Cross-links to the network-security checklist in [§6.5](#65-network-security-between-nginx-and-grapinator). |
| `docs/gunicorn.md` *(new)* | How Gunicorn is wired into Grapinator: the entrypoint module, the bundled `gunicorn.conf.py`, the worker/thread sizing rule, the `post_fork` engine dispose, signal handling, the cross-host `WSGI_SOCKET_HOST = 0.0.0.0` binding pattern + Docker private-interface port-mapping example, the `GUNICORN_KEEPALIVE = 75` rationale, and the operational runbook (graceful reload via `SIGHUP`, single-worker reload via `SIGTERM`, log rotation, etc.). |
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
  behaviour, with four exceptions:
  1. TLS will not be terminated by Grapinator anymore. If
     `WSGI_SSL_CERT` is set, Grapinator logs a `WARNING` at boot but
     starts cleanly on plain HTTP — the operator must put Nginx (or
     another terminator) in front, **on a separate host** in the
     canonical topology ([§3](#3-target-architecture)). Production
     operators must also widen `WSGI_SOCKET_HOST` from `127.0.0.1`
     to `0.0.0.0` (or a specific private IP) so Nginx can reach
     Grapinator across the network; see
     [§6.5](#65-network-security-between-nginx-and-grapinator) for the
     Docker port-mapping and firewall recipe that constrains the
     resulting reachability.
  2. Worker count is now `2 * CPU + 1` rather than `1`. CPU and memory
     usage on the host will rise proportionally. This is called out
     prominently in the release notes.
  3. Oracle deployments that previously had no `call_timeout` set
     will now have one applied (default `15000` ms). Any single Oracle
     round-trip that exceeds 15 s will raise `DPI-1067` and surface as
     a GraphQL error instead of silently consuming a worker thread.
     Operators with legitimately long-running queries must raise
     `ORACLE_CALL_TIMEOUT` (and `GUNICORN_TIMEOUT`) explicitly.
  4. `GUNICORN_KEEPALIVE` defaults to `75` s (not the Gunicorn
     upstream default of `5` s) so the Nginx upstream-keepalive pool
     on the API-gateway host actually reuses the cross-host TCP
     connections. Same-host or loopback-only deployments wanting the
     shorter idle window can lower this explicitly in the INI.

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
3. Add `grapinator/db_listener.py` — the `register(engine, settings)`
   dispatcher plus the non-trivial `_apply_oracle` helper and the
   no-op `_apply_postgresql` / `_apply_mysql` / `_apply_mssql` /
   `_apply_noop` stubs. Wire `register()` into `model.py`
   immediately after `create_engine(...)`. Add
   `tests/test_db_listener.py`.
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
2. **Unix socket vs. TCP loopback bind — resolved: TCP only;
   unix-socket binds are not part of the canonical topology.**
   Because Nginx runs on a separate physical or virtual host from
   Grapinator (Grapinator lives in a Docker container on machine B,
   Nginx on machine A), the two cannot share a filesystem and a
   unix-domain socket between them is not workable. The bundled INI
   files keep `WSGI_SOCKET_HOST = 127.0.0.1` so a developer can run
   Grapinator standalone without exposing it to the network;
   production operators set it to `0.0.0.0` (or a specific private IP
   on the Docker host) and rely on the Docker private-interface port
   mapping plus a firewall rule for reachability constraints (full
   recipe in [§6.5](#65-network-security-between-nginx-and-grapinator)).
   Gunicorn does technically still accept a `unix:` bind string for
   single-host all-in-one experiments, but this is not exercised by
   the bundled config or tests and not documented as a supported
   variant.
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
- No abstract / dialect-agnostic INI keys for per-connection
  settings (e.g. a notional `DB_CALL_TIMEOUT` that would expand to
  each backend's native mechanism). The `db_listener.py` dispatcher
  in [§5.2](#52-design) keeps dialect-prefixed namespaces
  (`ORACLE_*`, `POSTGRES_*`, `MYSQL_*`, `MSSQL_*`) precisely because
  units, scopes, and semantics differ enough across drivers that a
  unified key would mislead operators.
- No HTTP/2 or HTTP/3 termination inside Grapinator — those are
  Nginx-side concerns.
- No Grapinator-implemented `/healthz`, `/livez`, or `/readyz`
  endpoints in 2.1.12. These are deferred to a future release that
  will introduce all three together with documented Kubernetes-style
  semantics (per [§11 decision #4](#11-resolved-decisions)). The
  Nginx `/healthz` location in [§6.2](#62-server-block) is a static
  200 served by Nginx itself — it does **not** proxy to Grapinator.
- No native TLS support inside Gunicorn for the Nginx → Grapinator
  hop. The deprecated `WSGI_SSL_CERT` / `WSGI_SSL_PRIVKEY` keys are
  not re-implemented against Gunicorn. Operators who must encrypt
  cross-host traffic put `stunnel` or a service-mesh sidecar in
  front of Gunicorn on the Grapinator host — see
  [§6.5](#65-network-security-between-nginx-and-grapinator) step 4.
- No `werkzeug.middleware.proxy_fix.ProxyFix` integration in 2.1.12.
  Grapinator does not currently use the client IP for any
  authentication or audit decision (`grapinator/auth.py` is
  IP-agnostic), so the `X-Forwarded-For` chain set by Nginx is
  preserved on the request but is not parsed back into
  `request.remote_addr`. When IP-based rate limits or audit logging
  are added, a future release will wire `ProxyFix` into the
  middleware stack.
- No unix-domain socket bind between Nginx and Grapinator. The
  cross-host topology rules it out; see
  [§11 decision #2](#11-resolved-decisions).
