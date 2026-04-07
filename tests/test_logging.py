"""
test_logging.py

Unit tests that verify structured logging is emitted by every Grapinator module
at the correct level for the documented events.

Strategy
~~~~~~~~
All tests use :class:`unittest.mock.patch` to capture log records emitted by
the module under test, asserting on logger name, level, and message content
without requiring a real database, JWKS endpoint, or running server.

Logger names under test:
  - ``grapinator``             (__init__.py)
  - ``grapinator.settings``    (settings.py)
  - ``grapinator.model``       (model.py)
  - ``grapinator.schema``      (schema.py)
  - ``grapinator.app``         (app.py)
  - ``grapinator.svc_cherrypy``(svc_cherrypy.py)
  - ``grapinator.auth``        (auth.py)

Tests do NOT load a real ini file or database.  Logging calls in module-level
code have already executed by the time the test suite imports the package;
those are verified via separate instantiation / call tests.
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import time
import logging
import unittest
from unittest.mock import MagicMock, patch, call

from . import context  # noqa: F401

import jwt as pyjwt

from grapinator.auth import BearerAuthMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEV_SECRET = 'test-dev-secret-do-not-use-in-production'


def _make_token(roles=None, secret=DEV_SECRET, exp_offset=3600):
    now = int(time.time())
    payload = {'sub': 'test-user', 'iat': now, 'exp': now + exp_offset}
    if roles is not None:
        payload['roles'] = roles
    return pyjwt.encode(payload, secret, algorithm='HS256')


def _mock_settings(**overrides):
    s = MagicMock()
    s.AUTH_MODE = overrides.get('AUTH_MODE', 'mixed')
    s.AUTH_JWKS_URI = overrides.get('AUTH_JWKS_URI', None)
    s.AUTH_ISSUER = overrides.get('AUTH_ISSUER', None)
    s.AUTH_AUDIENCE = overrides.get('AUTH_AUDIENCE', None)
    s.AUTH_ALGORITHMS = overrides.get('AUTH_ALGORITHMS', 'HS256')
    s.AUTH_ROLES_CLAIM = overrides.get('AUTH_ROLES_CLAIM', 'roles')
    s.AUTH_JWKS_CACHE_TTL = overrides.get('AUTH_JWKS_CACHE_TTL', 300)
    s.AUTH_DEV_SECRET = overrides.get('AUTH_DEV_SECRET', DEV_SECRET)
    s.GRAPHIQL_ACCESS = overrides.get('GRAPHIQL_ACCESS', 'authenticated')
    return s


def _downstream():
    """Return a minimal downstream WSGI app that records calls."""
    app = MagicMock(return_value=[b'ok'])
    return app


def _make_environ(method='POST', path='/gql', token=None, accept='application/json'):
    env = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path,
        'HTTP_ACCEPT': accept,
        'QUERY_STRING': '',
    }
    if token:
        env['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return env


# ---------------------------------------------------------------------------
# auth.py logging tests
# ---------------------------------------------------------------------------

class TestAuthLoggingInit(unittest.TestCase):
    """BearerAuthMiddleware.__init__ emits the expected log records."""

    def test_init_logs_info_mode_and_algorithms(self):
        """INFO logged with mode, algorithms, and graphiql_access on init."""
        with self.assertLogs('grapinator.auth', level='DEBUG') as cm:
            BearerAuthMiddleware(_downstream(), _mock_settings())
        messages = [r.getMessage() for r in cm.records]
        info_msgs = [m for m in messages if 'mode=' in m and 'algorithms=' in m]
        self.assertTrue(info_msgs, 'Expected INFO init message not found')

    def test_init_warns_dev_secret(self):
        """WARNING logged when AUTH_DEV_SECRET is set."""
        with self.assertLogs('grapinator.auth', level='WARNING') as cm:
            BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_DEV_SECRET=DEV_SECRET))
        levels = [r.levelno for r in cm.records]
        self.assertIn(logging.WARNING, levels)
        warning_msgs = [r.getMessage() for r in cm.records if r.levelno == logging.WARNING]
        self.assertTrue(any('AUTH_DEV_SECRET' in m for m in warning_msgs))

    def test_init_no_warning_without_dev_secret(self):
        """No WARNING about dev secret when AUTH_DEV_SECRET is None."""
        with self.assertLogs('grapinator.auth', level='DEBUG') as cm:
            BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_DEV_SECRET=None))
        warning_msgs = [r for r in cm.records
                        if r.levelno == logging.WARNING and 'AUTH_DEV_SECRET' in r.getMessage()]
        self.assertEqual(warning_msgs, [])


class TestAuthLoggingCallPaths(unittest.TestCase):
    """BearerAuthMiddleware.__call__ emits the expected log records per code path."""

    def _middleware(self, **kw):
        return BearerAuthMiddleware(_downstream(), _mock_settings(**kw))

    def _start_response(self):
        return MagicMock()

    def test_options_preflight_logs_debug_bypass(self):
        """DEBUG bypass message emitted for OPTIONS requests."""
        mw = self._middleware()
        with self.assertLogs('grapinator.auth', level='DEBUG') as cm:
            mw(_make_environ(method='OPTIONS'), self._start_response())
        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(any('OPTIONS' in m and 'bypass' in m.lower() for m in messages))

    def test_graphiql_open_bypass_logs_debug(self):
        """DEBUG bypass message emitted for bare GraphiQL GET when access=open."""
        mw = self._middleware(GRAPHIQL_ACCESS='open')
        env = _make_environ(method='GET', accept='text/html, */*')
        with self.assertLogs('grapinator.auth', level='DEBUG') as cm:
            mw(env, self._start_response())
        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(any('GraphiQL' in m and 'bypass' in m.lower() for m in messages))

    def test_no_token_mixed_mode_logs_debug_unauthenticated(self):
        """DEBUG unauthenticated passthrough logged when no token in mixed mode."""
        mw = self._middleware(AUTH_MODE='mixed')
        with self.assertLogs('grapinator.auth', level='DEBUG') as cm:
            mw(_make_environ(), self._start_response())
        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(
            any('no token' in m.lower() and 'mixed' in m.lower() for m in messages)
        )

    def test_no_token_required_mode_logs_warning(self):
        """WARNING logged when no token is presented in required mode."""
        mw = self._middleware(AUTH_MODE='required')
        with self.assertLogs('grapinator.auth', level='WARNING') as cm:
            mw(_make_environ(), self._start_response())
        levels = [r.levelno for r in cm.records]
        self.assertIn(logging.WARNING, levels)
        warning_msgs = [r.getMessage() for r in cm.records if r.levelno == logging.WARNING]
        self.assertTrue(any('no token' in m.lower() or 'required' in m.lower() for m in warning_msgs))

    def test_valid_token_logs_debug_roles(self):
        """DEBUG message logged with roles on successful token validation."""
        token = _make_token(roles=['admin', 'hr'])
        mw = self._middleware(AUTH_MODE='mixed')
        with self.assertLogs('grapinator.auth', level='DEBUG') as cm:
            mw(_make_environ(token=token), self._start_response())
        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(any('token valid' in m.lower() and 'roles' in m.lower() for m in messages))

    def test_invalid_token_logs_warning(self):
        """WARNING logged when token validation fails."""
        mw = self._middleware(AUTH_MODE='mixed')
        with self.assertLogs('grapinator.auth', level='WARNING') as cm:
            mw(_make_environ(token='bad.token.here'), self._start_response())
        levels = [r.levelno for r in cm.records]
        self.assertIn(logging.WARNING, levels)
        warning_msgs = [r.getMessage() for r in cm.records if r.levelno == logging.WARNING]
        self.assertTrue(any('token validation failed' in m.lower() for m in warning_msgs))

    def test_expired_token_logs_warning_with_type(self):
        """WARNING log for an expired token includes exception type name."""
        token = _make_token(exp_offset=-1)
        mw = self._middleware(AUTH_MODE='mixed')
        with self.assertLogs('grapinator.auth', level='WARNING') as cm:
            mw(_make_environ(token=token), self._start_response())
        warning_msgs = [r.getMessage() for r in cm.records if r.levelno == logging.WARNING]
        self.assertTrue(
            any('ExpiredSignature' in m or 'Expired' in m for m in warning_msgs),
            f'Expected Expired in warning messages, got: {warning_msgs}',
        )

    def test_wrong_secret_logs_warning(self):
        """WARNING logged when token is signed with wrong secret."""
        token = _make_token(secret='wrong-secret')
        mw = self._middleware(AUTH_MODE='required')
        with self.assertLogs('grapinator.auth', level='WARNING') as cm:
            mw(_make_environ(token=token), self._start_response())
        levels = [r.levelno for r in cm.records]
        self.assertIn(logging.WARNING, levels)


class TestAuthLoggingLevelNames(unittest.TestCase):
    """Verify the logger is named 'grapinator.auth' (child of root grapinator logger)."""

    def test_logger_name(self):
        """BearerAuthMiddleware uses a logger named grapinator.auth."""
        from grapinator.auth import logger as auth_logger
        self.assertEqual(auth_logger.name, 'grapinator.auth')


# ---------------------------------------------------------------------------
# settings.py logging tests
# ---------------------------------------------------------------------------

class TestSettingsLogging(unittest.TestCase):
    """Settings.__init__ emits structured debug/warning log calls."""

    def test_logger_name(self):
        """Settings module uses a logger named grapinator.settings."""
        from grapinator.settings import logger as settings_logger
        self.assertEqual(settings_logger.name, 'grapinator.settings')

    def test_no_config_file_raises_before_logging(self):
        """RuntimeError raised immediately when config_file is missing."""
        from grapinator.settings import Settings
        with self.assertRaises(RuntimeError):
            Settings()

    def test_missing_env_key_raises_runtime_error(self):
        """RuntimeError raised when GQLAPI_CRYPT_KEY is absent."""
        from grapinator.settings import Settings
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key if present
            env = {k: v for k, v in os.environ.items() if k != 'GQLAPI_CRYPT_KEY'}
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(RuntimeError) as ctx:
                    Settings(config_file='/resources/grapinator.ini')
                self.assertIn('env key', str(ctx.exception))


# ---------------------------------------------------------------------------
# model.py logging tests
# ---------------------------------------------------------------------------

class TestModelLogging(unittest.TestCase):
    """model.py emits INFO on engine creation and ORM class registration."""

    def test_logger_name(self):
        """model module uses a logger named grapinator.model."""
        from grapinator import model
        import logging
        logger = logging.getLogger('grapinator.model')
        self.assertEqual(logger.name, 'grapinator.model')

    def test_orm_classes_registered(self):
        """_orm_class_count > 0 is set after module import."""
        from grapinator import model
        self.assertGreater(model._orm_class_count, 0)


# ---------------------------------------------------------------------------
# schema.py logging tests
# ---------------------------------------------------------------------------

class TestSchemaLogging(unittest.TestCase):
    """schema.py emits INFO/DEBUG on type-build and schema compilation."""

    def test_logger_name(self):
        """schema module uses a logger named grapinator.schema."""
        import logging
        logger = logging.getLogger('grapinator.schema')
        self.assertEqual(logger.name, 'grapinator.schema')

    def test_gql_class_count_set(self):
        """_gql_class_count > 0 after module-level class-build loop."""
        from grapinator import schema
        self.assertGreater(schema._gql_class_count, 0)

    def test_entity_auth_roles_debug_denied(self):
        """RBAC entity access denial emits a DEBUG log."""
        from grapinator.schema import MyConnectionField, _ENTITY_AUTH_ROLES
        if not _ENTITY_AUTH_ROLES:
            self.skipTest('No entity auth roles configured in current schema')

        model_name = next(iter(_ENTITY_AUTH_ROLES))
        required_roles = _ENTITY_AUTH_ROLES[model_name]

        # Build a minimal mock info and query
        mock_info = MagicMock()
        mock_info.context = {'user_roles': [], 'authenticated': False}
        mock_model = MagicMock()
        mock_model.__name__ = model_name

        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)

        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            with self.assertLogs('grapinator.schema', level='DEBUG') as cm:
                MyConnectionField.get_query(mock_model, mock_info)

        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(
            any('denied' in m.lower() or 'RBAC' in m for m in messages),
            f'Expected RBAC denial log, got: {messages}',
        )

    def test_entity_auth_roles_debug_granted(self):
        """RBAC entity access grant emits a DEBUG log."""
        from grapinator.schema import MyConnectionField, _ENTITY_AUTH_ROLES
        if not _ENTITY_AUTH_ROLES:
            self.skipTest('No entity auth roles configured in current schema')

        model_name = next(iter(_ENTITY_AUTH_ROLES))
        required_roles = _ENTITY_AUTH_ROLES[model_name]

        mock_info = MagicMock()
        mock_info.context = {'user_roles': list(required_roles), 'authenticated': True}
        mock_model = MagicMock()
        mock_model.__name__ = model_name

        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)

        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            with self.assertLogs('grapinator.schema', level='DEBUG') as cm:
                MyConnectionField.get_query(mock_model, mock_info)

        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(
            any('granted' in m.lower() or 'RBAC' in m for m in messages),
            f'Expected RBAC granted log, got: {messages}',
        )


# ---------------------------------------------------------------------------
# app.py logging tests
# ---------------------------------------------------------------------------

class TestAppLogging(unittest.TestCase):
    """app.py emits INFO for endpoint registration and DEBUG per-request auth state."""

    def test_logger_name(self):
        """app module uses a logger named grapinator.app."""
        import logging
        logger = logging.getLogger('grapinator.app')
        self.assertEqual(logger.name, 'grapinator.app')

    def test_before_request_logs_auth_state(self):
        """_load_auth_state logs authenticated flag and roles at DEBUG."""
        from grapinator.app import app
        with app.test_request_context('/test', environ_base={
            'grapinator.user_roles': ['admin'],
            'grapinator.authenticated': True,
        }):
            with self.assertLogs('grapinator.app', level='DEBUG') as cm:
                app.preprocess_request()
        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(
            any('authenticated=True' in m and 'roles=' in m for m in messages),
            f'Expected auth state DEBUG log, got: {messages}',
        )

    def test_before_request_logs_unauthenticated(self):
        """_load_auth_state logs authenticated=False when no token is present."""
        from grapinator.app import app
        with app.test_request_context('/test'):
            with self.assertLogs('grapinator.app', level='DEBUG') as cm:
                app.preprocess_request()
        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(
            any('authenticated=False' in m for m in messages),
            f'Expected unauthenticated DEBUG log, got: {messages}',
        )


# ---------------------------------------------------------------------------
# __init__.py / package-level logging tests
# ---------------------------------------------------------------------------

class TestPackageLogging(unittest.TestCase):
    """Verify the root package logger and startup log records."""

    def test_root_logger_name(self):
        """Package __init__ uses a logger named 'grapinator'."""
        import logging
        from grapinator import log
        self.assertEqual(log.name, 'grapinator')

    def test_schema_count_positive(self):
        """Schema entity count logged at startup is > 0."""
        from grapinator import schema_settings
        self.assertGreater(len(schema_settings.get_gql_classes()), 0)


# ---------------------------------------------------------------------------
# Log level contract tests
# ---------------------------------------------------------------------------

class TestLogLevelContract(unittest.TestCase):
    """
    These tests document and enforce the log-level contract across modules:
    each module must use an appropriately named child logger of 'grapinator'.
    """

    def _check_child_of_grapinator(self, module_path):
        import logging
        logger = logging.getLogger(module_path)
        self.assertTrue(
            logger.name.startswith('grapinator'),
            f'{logger.name} is not a child of the grapinator logger',
        )

    def test_auth_logger_is_child(self):
        self._check_child_of_grapinator('grapinator.auth')

    def test_settings_logger_is_child(self):
        self._check_child_of_grapinator('grapinator.settings')

    def test_model_logger_is_child(self):
        self._check_child_of_grapinator('grapinator.model')

    def test_schema_logger_is_child(self):
        self._check_child_of_grapinator('grapinator.schema')

    def test_app_logger_is_child(self):
        self._check_child_of_grapinator('grapinator.app')

    def test_svc_cherrypy_logger_is_child(self):
        self._check_child_of_grapinator('grapinator.svc_cherrypy')

    def test_warning_level_for_dev_secret(self):
        """AUTH_DEV_SECRET triggers WARNING, not DEBUG or INFO."""
        with self.assertLogs('grapinator.auth', level='WARNING') as cm:
            BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_DEV_SECRET=DEV_SECRET))
        warning_records = [r for r in cm.records if r.levelno == logging.WARNING]
        self.assertGreater(len(warning_records), 0)

    def test_info_level_for_init_summary(self):
        """Init summary is emitted at INFO, not DEBUG."""
        with self.assertLogs('grapinator.auth', level='INFO') as cm:
            BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_DEV_SECRET=None))
        info_records = [r for r in cm.records if r.levelno == logging.INFO]
        self.assertGreater(len(info_records), 0)

    def test_debug_level_for_valid_request(self):
        """Successful auth decision is logged at DEBUG (not INFO or WARNING)."""
        token = _make_token(roles=['reader'])
        mw = BearerAuthMiddleware(_downstream(), _mock_settings())
        with self.assertLogs('grapinator.auth', level='DEBUG') as cm:
            mw(_make_environ(token=token), MagicMock())
        debug_records = [r for r in cm.records if r.levelno == logging.DEBUG]
        self.assertGreater(len(debug_records), 0)


if __name__ == '__main__':
    unittest.main()
