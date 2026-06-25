"""Unit tests for grapinator.db_listener.

The listener registers a SQLAlchemy ``connect`` event handler that applies
per-dialect tuning to each freshly-pooled DBAPI connection.  These tests
exercise the dispatcher and the Oracle helper using fakes -- no real
database driver is required.
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from . import context  # noqa: F401  -- adds project root to sys.path

from grapinator import db_listener


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeDbapiConn:
    """Minimal DBAPI connection double that records attribute writes."""
    def __init__(self):
        self.closed = False
        self._writes = {}

    def __setattr__(self, name, value):
        # Allow our own bookkeeping fields through without recording them.
        if name in ('closed', '_writes'):
            object.__setattr__(self, name, value)
        else:
            self._writes[name] = value
            object.__setattr__(self, name, value)

    def close(self):
        self.closed = True


class _FailingCallTimeoutConn(_FakeDbapiConn):
    """Raises ValueError when call_timeout is assigned -- to exercise the
    fatal-failure code path."""
    def __setattr__(self, name, value):
        if name == 'call_timeout':
            raise ValueError('synthetic driver failure')
        super().__setattr__(name, value)


class _FailingModuleConn(_FakeDbapiConn):
    """Raises ValueError when module is assigned -- to exercise the
    best-effort warning path."""
    def __setattr__(self, name, value):
        if name == 'module':
            raise ValueError('synthetic driver failure')
        super().__setattr__(name, value)


def _oracle_settings(**overrides):
    """Build a settings stub carrying ORACLE_* attributes."""
    base = dict(
        ORACLE_CALL_TIMEOUT=15000,
        ORACLE_STMTCACHESIZE=None,
        ORACLE_AUTOCOMMIT=None,
        ORACLE_MODULE='grapinator',
        ORACLE_ACTION=None,
        ORACLE_CLIENT_IDENTIFIER=None,
        ORACLE_CURRENT_SCHEMA=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher(unittest.TestCase):
    """register() resolves the right helper by engine.dialect.name."""

    def _fake_engine(self, dialect_name):
        # SQLAlchemy's @event.listens_for accepts any object with a
        # `dispatch` attribute, but easier to just patch event.listen.
        engine = MagicMock()
        engine.dialect.name = dialect_name
        return engine

    def test_oracle_dialect_uses_oracle_helper(self):
        self.assertIs(db_listener._DIALECT_HELPERS['oracle'], db_listener._apply_oracle)

    def test_postgresql_dialect_present(self):
        self.assertIn('postgresql', db_listener._DIALECT_HELPERS)

    def test_mysql_dialect_present(self):
        self.assertIn('mysql', db_listener._DIALECT_HELPERS)

    def test_mssql_dialect_present(self):
        self.assertIn('mssql', db_listener._DIALECT_HELPERS)

    def test_sqlite_dialect_uses_noop(self):
        self.assertIs(db_listener._DIALECT_HELPERS['sqlite'], db_listener._apply_noop)

    def test_unknown_dialect_falls_back_to_noop(self):
        # register() must not raise for an unknown dialect; calling the
        # resolved helper should be a no-op.
        from sqlalchemy import event as sa_event
        engine = self._fake_engine('madeup')
        # Stub event.listens_for so we don't actually attach to MagicMock.
        original_listens_for = sa_event.listens_for
        captured = {}

        def stub_listens_for(target, identifier):
            def _decorator(fn):
                captured['fn'] = fn
                return fn
            return _decorator

        sa_event.listens_for = stub_listens_for
        try:
            db_listener.register(engine, _oracle_settings())
        finally:
            sa_event.listens_for = original_listens_for
        # The decorated function should be the no-op (calling it with a
        # fresh fake conn must not touch any attributes).
        conn = _FakeDbapiConn()
        captured['fn'](conn, MagicMock())
        self.assertEqual(conn._writes, {})


# ---------------------------------------------------------------------------
# Oracle helper -- happy paths
# ---------------------------------------------------------------------------

class TestApplyOracleHappy(unittest.TestCase):
    """_apply_oracle sets configured attributes on the DBAPI connection."""

    def test_call_timeout_applied(self):
        conn = _FakeDbapiConn()
        db_listener._apply_oracle(conn, _oracle_settings(ORACLE_CALL_TIMEOUT=15000))
        self.assertEqual(conn._writes.get('call_timeout'), 15000)
        self.assertFalse(conn.closed)

    def test_call_timeout_coerced_to_int(self):
        conn = _FakeDbapiConn()
        db_listener._apply_oracle(conn, _oracle_settings(ORACLE_CALL_TIMEOUT='25000'))
        self.assertEqual(conn._writes.get('call_timeout'), 25000)
        self.assertIsInstance(conn._writes['call_timeout'], int)

    def test_module_default_applied(self):
        conn = _FakeDbapiConn()
        db_listener._apply_oracle(conn, _oracle_settings())
        self.assertEqual(conn._writes.get('module'), 'grapinator')

    def test_optional_attrs_only_applied_when_set(self):
        conn = _FakeDbapiConn()
        db_listener._apply_oracle(conn, _oracle_settings(
            ORACLE_STMTCACHESIZE=40,
            ORACLE_CLIENT_IDENTIFIER='alice',
            ORACLE_CURRENT_SCHEMA='APP_OWNER',
        ))
        self.assertEqual(conn._writes.get('stmtcachesize'), 40)
        self.assertEqual(conn._writes.get('client_identifier'), 'alice')
        self.assertEqual(conn._writes.get('current_schema'), 'APP_OWNER')
        self.assertNotIn('action', conn._writes)
        self.assertNotIn('autocommit', conn._writes)

    def test_none_attrs_are_skipped(self):
        conn = _FakeDbapiConn()
        db_listener._apply_oracle(conn, _oracle_settings(
            ORACLE_STMTCACHESIZE=None,
            ORACLE_AUTOCOMMIT=None,
        ))
        self.assertNotIn('stmtcachesize', conn._writes)
        self.assertNotIn('autocommit', conn._writes)


# ---------------------------------------------------------------------------
# Oracle helper -- failure paths
# ---------------------------------------------------------------------------

class TestApplyOracleFailures(unittest.TestCase):
    """Call-timeout failures are fatal; others are best-effort."""

    def test_call_timeout_failure_closes_connection(self):
        conn = _FailingCallTimeoutConn()
        with self.assertLogs(db_listener.logger, level='ERROR') as cm:
            db_listener._apply_oracle(conn, _oracle_settings())
        self.assertTrue(conn.closed)
        self.assertTrue(
            any('call_timeout' in r.getMessage() for r in cm.records),
            'expected ERROR log to mention call_timeout',
        )

    def test_call_timeout_failure_short_circuits(self):
        # When call_timeout fails, subsequent best-effort attrs must NOT be
        # attempted (the connection is being thrown away).
        conn = _FailingCallTimeoutConn()
        with self.assertLogs(db_listener.logger, level='ERROR'):
            db_listener._apply_oracle(conn, _oracle_settings(ORACLE_MODULE='x'))
        self.assertNotIn('module', conn._writes)

    def test_module_failure_logs_warning_does_not_close(self):
        conn = _FailingModuleConn()
        with self.assertLogs(db_listener.logger, level='WARNING') as cm:
            db_listener._apply_oracle(conn, _oracle_settings())
        self.assertFalse(conn.closed)
        # call_timeout still applied successfully.
        self.assertEqual(conn._writes.get('call_timeout'), 15000)
        self.assertTrue(
            any('module' in r.getMessage() for r in cm.records),
            'expected WARNING log to mention module',
        )


# ---------------------------------------------------------------------------
# No-op helper
# ---------------------------------------------------------------------------

class TestApplyNoop(unittest.TestCase):
    def test_does_nothing(self):
        conn = _FakeDbapiConn()
        db_listener._apply_noop(conn, _oracle_settings())
        self.assertEqual(conn._writes, {})
        self.assertFalse(conn.closed)


# ---------------------------------------------------------------------------
# Integration -- the registered listener fires on a real sqlite engine
# ---------------------------------------------------------------------------

class TestRegisterAttachesListener(unittest.TestCase):
    """register() must attach a working ``connect`` listener to the engine."""

    def test_sqlite_listener_fires_on_connect(self):
        from sqlalchemy import create_engine
        engine = create_engine('sqlite:///:memory:')
        # sqlite uses _apply_noop -- registering must not raise.
        db_listener.register(engine, _oracle_settings())
        # Open a connection to trigger the event.
        with engine.connect():
            pass

    def test_oracle_helper_invoked_on_connect(self):
        # Use a sqlite engine but swap _DIALECT_HELPERS['sqlite'] to verify
        # the listener actually calls the resolved helper.
        from sqlalchemy import create_engine
        engine = create_engine('sqlite:///:memory:')
        calls = []

        def _spy(dbapi_conn, settings):
            calls.append((dbapi_conn, settings))

        original = db_listener._DIALECT_HELPERS['sqlite']
        db_listener._DIALECT_HELPERS['sqlite'] = _spy
        try:
            db_listener.register(engine, _oracle_settings())
            with engine.connect():
                pass
        finally:
            db_listener._DIALECT_HELPERS['sqlite'] = original
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
