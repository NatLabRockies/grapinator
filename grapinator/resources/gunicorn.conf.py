"""
gunicorn.conf.py

Gunicorn configuration loaded via ``gunicorn --config <this-file>``.  All
tunables are sourced from ``grapinator.settings`` so a single INI file
remains the source of truth.

Notes
-----
* ``worker_class`` is restricted to ``gthread`` and ``sync`` for 2.1.12.
  Other classes (gevent, eventlet, tornado) require additional dependencies
  and have not been validated against the Grapinator middleware stack.
* The ``post_fork`` hook disposes the SQLAlchemy engine in each child
  worker so pooled connections opened in the parent before fork are not
  inherited (which would corrupt the DBAPI protocol state).
"""

import logging as _logging
import sys as _sys

from grapinator import settings as _settings

_log = _logging.getLogger('grapinator.gunicorn')

# --- bind ----------------------------------------------------------------
bind = f"{_settings.WSGI_SOCKET_HOST}:{_settings.WSGI_SOCKET_PORT}"

# --- workers / threads ---------------------------------------------------
workers = _settings.GUNICORN_WORKERS
threads = _settings.GUNICORN_THREADS
worker_class = _settings.GUNICORN_WORKER_CLASS

_SUPPORTED_WORKER_CLASSES = {'gthread', 'sync'}
if worker_class not in _SUPPORTED_WORKER_CLASSES:
    _sys.stderr.write(
        f"ERROR: GUNICORN_WORKER_CLASS={worker_class!r} is not supported in "
        f"2.1.12 -- allowed values: {sorted(_SUPPORTED_WORKER_CLASSES)}\n"
    )
    _sys.exit(1)

worker_connections = _settings.GUNICORN_WORKER_CONNECTIONS
timeout = _settings.GUNICORN_TIMEOUT
keepalive = _settings.GUNICORN_KEEPALIVE
max_requests = _settings.GUNICORN_MAX_REQUESTS
max_requests_jitter = _settings.GUNICORN_MAX_REQUESTS_JITTER
limit_request_line = _settings.GUNICORN_LIMIT_REQUEST_LINE
limit_request_field_size = _settings.GUNICORN_LIMIT_REQUEST_FIELD_SIZE

# --- socket / shutdown tuning -------------------------------------------
# WSGI_SOCKET_QUEUE_SIZE and WSGI_SHUTDOWN_TIMEOUT are repurposed in 2.1.12
# as Gunicorn ``backlog`` / ``graceful_timeout`` -- only set them when the
# operator opted in via the INI file.
if _settings.WSGI_SOCKET_QUEUE_SIZE is not None:
    backlog = _settings.WSGI_SOCKET_QUEUE_SIZE
if _settings.WSGI_SHUTDOWN_TIMEOUT is not None:
    graceful_timeout = _settings.WSGI_SHUTDOWN_TIMEOUT

# --- logging (stdout for container friendliness) ------------------------
accesslog = '-'
errorlog = '-'
loglevel = 'info'


def post_fork(server, worker):  # noqa: ARG001 -- Gunicorn signature
    """Dispose the SQLAlchemy engine after each worker fork.

    SQLAlchemy pools are not safe across fork boundaries -- inherited
    connections share protocol state with the parent.  Disposing here
    forces each child to open fresh DBAPI connections lazily.
    """
    try:
        from grapinator.model import engine
        engine.dispose()
        _log.info('post_fork: engine disposed for worker pid=%s', worker.pid)
    except Exception as err:  # noqa: BLE001
        _log.error('post_fork: failed to dispose engine: %s', err)
