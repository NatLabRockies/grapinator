"""Unit tests for grapinator/resources/gunicorn.conf.py.

The conf file is loaded by Gunicorn (not imported via the normal package
machinery), so we load it here with importlib.util.spec_from_file_location
and assert the module-level attributes it sets.
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from . import context  # noqa: F401  -- adds project root to sys.path

_CONF_PATH = (
    Path(__file__).resolve().parent.parent
    / 'grapinator' / 'resources' / 'gunicorn.conf.py'
)


def _load_conf_with_settings(settings_stub):
    """Load gunicorn.conf.py with a stubbed grapinator.settings.

    The conf file does ``from grapinator import settings as _settings``;
    we override that attribute in sys.modules before loading so the conf
    sees our stub instead of the real INI-driven settings.
    """
    import grapinator
    original = grapinator.settings
    grapinator.settings = settings_stub
    try:
        spec = importlib.util.spec_from_file_location(
            'grapinator_test_gunicorn_conf', str(_CONF_PATH),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        grapinator.settings = original


def _default_settings_stub(**overrides):
    base = dict(
        WSGI_SOCKET_HOST='127.0.0.1',
        WSGI_SOCKET_PORT=8443,
        WSGI_SOCKET_QUEUE_SIZE=None,
        WSGI_SHUTDOWN_TIMEOUT=None,
        GUNICORN_WORKERS=5,
        GUNICORN_THREADS=8,
        GUNICORN_WORKER_CLASS='gthread',
        GUNICORN_WORKER_CONNECTIONS=1000,
        GUNICORN_TIMEOUT=30,
        GUNICORN_KEEPALIVE=75,
        GUNICORN_MAX_REQUESTS=1000,
        GUNICORN_MAX_REQUESTS_JITTER=100,
        GUNICORN_LIMIT_REQUEST_LINE=8190,
        GUNICORN_LIMIT_REQUEST_FIELD_SIZE=8190,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Module-level attributes
# ---------------------------------------------------------------------------

class TestGunicornConfAttributes(unittest.TestCase):
    """The conf file must publish the canonical Gunicorn attribute names."""

    def setUp(self):
        self.conf = _load_conf_with_settings(_default_settings_stub())

    def test_bind_combines_host_and_port(self):
        self.assertEqual(self.conf.bind, '127.0.0.1:8443')

    def test_workers(self):
        self.assertEqual(self.conf.workers, 5)

    def test_threads(self):
        self.assertEqual(self.conf.threads, 8)

    def test_worker_class(self):
        self.assertEqual(self.conf.worker_class, 'gthread')

    def test_timeout(self):
        self.assertEqual(self.conf.timeout, 30)

    def test_keepalive(self):
        self.assertEqual(self.conf.keepalive, 75)

    def test_max_requests(self):
        self.assertEqual(self.conf.max_requests, 1000)

    def test_max_requests_jitter(self):
        self.assertEqual(self.conf.max_requests_jitter, 100)

    def test_limit_request_line(self):
        self.assertEqual(self.conf.limit_request_line, 8190)

    def test_limit_request_field_size(self):
        self.assertEqual(self.conf.limit_request_field_size, 8190)

    def test_accesslog_to_stdout(self):
        self.assertEqual(self.conf.accesslog, '-')

    def test_errorlog_to_stderr(self):
        self.assertEqual(self.conf.errorlog, '-')


# ---------------------------------------------------------------------------
# Optional repurposed keys
# ---------------------------------------------------------------------------

class TestOptionalRepurposedKeys(unittest.TestCase):
    """WSGI_SOCKET_QUEUE_SIZE / WSGI_SHUTDOWN_TIMEOUT only set Gunicorn keys
    when present in the INI."""

    def test_backlog_unset_when_socket_queue_none(self):
        conf = _load_conf_with_settings(_default_settings_stub(
            WSGI_SOCKET_QUEUE_SIZE=None,
        ))
        self.assertFalse(hasattr(conf, 'backlog'))

    def test_backlog_set_when_socket_queue_provided(self):
        conf = _load_conf_with_settings(_default_settings_stub(
            WSGI_SOCKET_QUEUE_SIZE=2048,
        ))
        self.assertEqual(conf.backlog, 2048)

    def test_graceful_timeout_unset_when_shutdown_none(self):
        conf = _load_conf_with_settings(_default_settings_stub(
            WSGI_SHUTDOWN_TIMEOUT=None,
        ))
        self.assertFalse(hasattr(conf, 'graceful_timeout'))

    def test_graceful_timeout_set_when_shutdown_provided(self):
        conf = _load_conf_with_settings(_default_settings_stub(
            WSGI_SHUTDOWN_TIMEOUT=45,
        ))
        self.assertEqual(conf.graceful_timeout, 45)


# ---------------------------------------------------------------------------
# Worker-class validation
# ---------------------------------------------------------------------------

class TestWorkerClassValidation(unittest.TestCase):
    """Loading the conf file with an unsupported worker_class must sys.exit."""

    def test_sync_is_allowed(self):
        conf = _load_conf_with_settings(_default_settings_stub(
            GUNICORN_WORKER_CLASS='sync',
        ))
        self.assertEqual(conf.worker_class, 'sync')

    def test_gevent_is_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            _load_conf_with_settings(_default_settings_stub(
                GUNICORN_WORKER_CLASS='gevent',
            ))
        self.assertEqual(ctx.exception.code, 1)

    def test_eventlet_is_rejected(self):
        with self.assertRaises(SystemExit):
            _load_conf_with_settings(_default_settings_stub(
                GUNICORN_WORKER_CLASS='eventlet',
            ))


# ---------------------------------------------------------------------------
# post_fork hook
# ---------------------------------------------------------------------------

class TestPostForkHook(unittest.TestCase):
    """post_fork must dispose the SQLAlchemy engine in the child."""

    def test_post_fork_calls_engine_dispose(self):
        conf = _load_conf_with_settings(_default_settings_stub())
        with patch('grapinator.model.engine') as engine_mock:
            worker = MagicMock()
            worker.pid = 12345
            conf.post_fork(server=MagicMock(), worker=worker)
            engine_mock.dispose.assert_called_once()

    def test_post_fork_swallows_engine_failure(self):
        # If engine.dispose() raises, post_fork must NOT propagate -- a
        # crashed fork hook would prevent Gunicorn from spawning workers.
        conf = _load_conf_with_settings(_default_settings_stub())
        with patch('grapinator.model.engine') as engine_mock:
            engine_mock.dispose.side_effect = RuntimeError('boom')
            worker = MagicMock()
            worker.pid = 12345
            try:
                conf.post_fork(server=MagicMock(), worker=worker)
            except Exception as err:  # noqa: BLE001
                self.fail(f'post_fork should swallow errors, raised: {err!r}')


if __name__ == '__main__':
    unittest.main()
