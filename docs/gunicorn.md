# Gunicorn deployment guide

As of release 2.1.12 Grapinator runs under [Gunicorn](https://gunicorn.org/)
instead of the previous embedded CherryPy server.  Gunicorn was chosen for
its mature pre-fork model, simple operations story, and battle-tested
production track record.

This document covers:

1. The launch command and how Gunicorn picks up the bundled config.
2. Every Gunicorn tunable exposed via `grapinator.ini`.
3. Sizing rules of thumb for workers, threads, timeouts, and the Oracle
   per-connection call-timeout.
4. How to validate a config change before deploying it.

For the front-door Nginx reverse-proxy config that fronts Gunicorn in
production, see [`docs/nginx.md`](nginx.md).

---

## 1. Launch command

The Docker image runs:

```sh
exec gunicorn \
    --config /opt/grapinator/grapinator/resources/gunicorn.conf.py \
    grapinator.svc_gunicorn:application
```

`grapinator.svc_gunicorn:application` is the module-level WSGI callable
defined in [`grapinator/svc_gunicorn.py`](../grapinator/svc_gunicorn.py).
The Flask `app` is wrapped at import time by `build_wsgi_stack()` so every
worker fork inherits an identical, fully-wired application:

```
BearerAuthMiddleware (optional) -> CorsMiddleware -> SecurityHeadersMiddleware -> WSGILogger -> Flask app
```

`grapinator/resources/gunicorn.conf.py` reads from
`grapinator.settings.settings`, so the single ini file remains the source
of truth for all runtime knobs.

### Smoke-checking the config

`svc_gunicorn.main()` shells out to `gunicorn --check-config` without
binding a socket -- useful as a CI gate before a deploy:

```sh
python -m grapinator.svc_gunicorn
```

The exit status of the underlying `gunicorn` call is propagated.

---

## 2. Tunable reference

All keys live in the `[GUNICORN]` section of the ini file (with the
exception of the bind address, which stays under `[WSGI]`).  Every key is
optional; the class-level defaults shown below apply when a key is absent.

| Key | Default | Gunicorn attribute | Description |
|-----|---------|--------------------|-------------|
| `GUNICORN_WORKERS` | `2 * CPU + 1` | `workers` | Process count.  See sizing rule below. |
| `GUNICORN_THREADS` | `8` | `threads` | Threads per `gthread` worker.  Total concurrency = `WORKERS * THREADS`. |
| `GUNICORN_WORKER_CLASS` | `gthread` | `worker_class` | Only `gthread` and `sync` are validated for 2.1.12; any other value aborts boot. |
| `GUNICORN_WORKER_CONNECTIONS` | `1000` | `worker_connections` | Per-worker async connection cap.  No effect for `gthread`/`sync`. |
| `GUNICORN_TIMEOUT` | `30` | `timeout` | Seconds before Gunicorn force-kills a worker that is not responding. |
| `GUNICORN_KEEPALIVE` | `75` | `keepalive` | Seconds an idle keepalive connection is held open. |
| `GUNICORN_MAX_REQUESTS` | `1000` | `max_requests` | Worker auto-recycle after N requests, limiting memory-leak growth. |
| `GUNICORN_MAX_REQUESTS_JITTER` | `100` | `max_requests_jitter` | Random offset so workers do not recycle in lockstep. |
| `GUNICORN_LIMIT_REQUEST_LINE` | `8190` | `limit_request_line` | Maximum request-line bytes. |
| `GUNICORN_LIMIT_REQUEST_FIELD_SIZE` | `8190` | `limit_request_field_size` | Maximum header bytes. |

Two `[WSGI]` keys are repurposed as Gunicorn inputs:

| `[WSGI]` key | Gunicorn attribute |
|--------------|--------------------|
| `WSGI_SOCKET_QUEUE_SIZE` | `backlog` (default 2048) |
| `WSGI_SHUTDOWN_TIMEOUT` | `graceful_timeout` (default 30 s) |

### Worker class

* **`gthread`** (default) -- one process per worker, multiple OS threads
  per process.  Good for I/O-bound workloads like GraphQL backed by a
  database.  Requests share the SQLAlchemy connection pool inside one
  process.
* **`sync`** -- one request per worker at a time.  Use when you need
  strict request isolation or are debugging a thread-safety issue.

Other Gunicorn worker classes (`gevent`, `eventlet`, `tornado`) require
extra dependencies and have not been validated against Grapinator's
SQLAlchemy / Flask stack.  Setting `GUNICORN_WORKER_CLASS` to anything
else aborts boot with a non-zero exit and a clear stderr message.

### post_fork hook -- engine disposal

`grapinator/resources/gunicorn.conf.py` defines `post_fork(server,
worker)` which calls `engine.dispose()` immediately after each worker
fork.  SQLAlchemy connection pools are not safe across fork boundaries --
without this hook, every child would inherit the parent's open DBAPI
connections, corrupting protocol state on first use.  Disposing forces
each child to open its own fresh connections lazily.

---

## 3. Sizing rules

### Workers

The standard rule of thumb is **`2 * <CPU cores> + 1`**, applied
automatically when `GUNICORN_WORKERS` is unset.  Override downward for
memory-bound hosts; override upward only after measuring that CPU is the
bottleneck and threads are saturated.

### Threads

Default `8` works well for typical GraphQL queries dominated by database
round-trip time.  Push higher for heavy I/O wait, lower if you observe
GIL contention under CPU-bound resolvers.

### Database pool sizing

The total concurrent request capacity is `WORKERS * THREADS`.  Set
`DB_POOL_SIZE` to that value so every active thread can hold a DBAPI
connection without queuing.  For Oracle, also set:

* `DB_POOL_RECYCLE = 1800` (or shorter than Oracle's idle-session
  timeout) to avoid ORA-03135 / ORA-02396 on cold reconnect.
* `DB_POOL_PRE_PING = True` (the class default) so dead connections are
  evicted instead of returned to a caller.

### Timeout interlocks

Three timeouts must respect a strict ordering:

```
ORACLE_CALL_TIMEOUT (ms)  <  GUNICORN_TIMEOUT * 1000  (ms)  <  Nginx proxy_read_timeout * 1000
```

* `ORACLE_CALL_TIMEOUT` is enforced by the Oracle driver -- a runaway
  query aborts inside the DBAPI before Gunicorn intervenes.  Grapinator
  rejects boot if this is `<= 0` or `>= GUNICORN_TIMEOUT * 1000`.
* `GUNICORN_TIMEOUT` kills any worker that has not responded.  Set this
  generously above the worst-case query so a tail query does not nuke an
  otherwise healthy worker.
* The Nginx `proxy_read_timeout` should exceed `GUNICORN_TIMEOUT` so the
  504 returned to the client comes from Grapinator (with a useful
  message) rather than from Nginx (which is opaque).

### Keepalive

Match `GUNICORN_KEEPALIVE` to your Nginx `keepalive_timeout`.  The
default of 75 s aligns with Nginx's own default and prevents premature
upstream connection churn under sustained traffic.

---

## 4. Validating a config change

1. **Sanity-check the ini file**:
   ```sh
   python -m grapinator.svc_gunicorn /path/to/gunicorn.conf.py
   ```
   This shells out to `gunicorn --check-config` and does not bind a
   socket.  Non-zero exit means the config will not boot.

2. **Watch the boot log**.  Deprecated INI keys (`WSGI_SSL_CERT`,
   `WSGI_MAX_REQUEST_BODY_SIZE`, ...) log `WARNING` and are ignored.
   Removed keys (`WSGI_THREAD_POOL`, `WSGI_ACCEPTED_QUEUE_SIZE`) log
   `ERROR` and abort boot.

3. **Restart the service**.  Gunicorn supports zero-downtime reloads via
   `SIGHUP` (master fork-and-replace), but config keys read at boot time
   only take effect after a full restart.

For the upstream / Nginx-side configuration, continue to
[`docs/nginx.md`](nginx.md).
