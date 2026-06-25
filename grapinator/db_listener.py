"""
db_listener.py

Dialect-aware SQLAlchemy ``connect`` event listener that applies vendor
specific per-connection knobs after the DBAPI hands a fresh connection to
the pool.

Only :func:`register` is part of the public API.  The dispatcher selects a
``_apply_<dialect>`` helper from :data:`_DIALECT_HELPERS` using
``engine.dialect.name``.  Unknown dialects fall back to a no-op so future
SQLAlchemy backends keep working without changes here.

In release 2.1.12 only the Oracle helper is non-trivial.  PostgreSQL, MySQL,
MSSQL, and SQLite all reuse :func:`_apply_noop`; flesh them out in place when
a future release needs vendor-specific tuning.

Error handling rules (per the design doc):

* Failures applying ORACLE_CALL_TIMEOUT are treated as fatal for the
  connection -- the listener logs ``ERROR`` and closes the DBAPI connection
  so SQLAlchemy discards it from the pool.  A connection without a call
  timeout could let a runaway query consume a Gunicorn worker indefinitely.
* Failures applying any other Oracle attribute are logged at ``WARNING`` and
  the connection is returned to the pool -- losing a session module label
  is annoying but not load-bearing.
"""

from __future__ import annotations

import logging

from sqlalchemy import event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-dialect helpers
# ---------------------------------------------------------------------------

def _apply_noop(dbapi_conn, settings):
    """Dialect that has no per-connection knobs to apply."""
    return


def _apply_oracle(dbapi_conn, settings):
    """Apply Oracle (oracledb / cx_Oracle) per-connection knobs.

    ``ORACLE_CALL_TIMEOUT`` is treated as load-bearing -- if it cannot be
    set, the connection is closed so SQLAlchemy invalidates it from the
    pool.  All other attributes are best-effort and log WARNING on failure.
    """
    # call_timeout is the only attribute we treat as load-bearing: without
    # it, a runaway query can pin a Gunicorn worker until Gunicorn kills it,
    # losing whatever else the worker was serving.
    call_timeout = getattr(settings, 'ORACLE_CALL_TIMEOUT', None)
    if call_timeout is not None:
        try:
            dbapi_conn.call_timeout = int(call_timeout)
        except Exception as err:  # noqa: BLE001 - DBAPI raises vary by driver
            logger.error(
                'Oracle connect-listener: failed to set call_timeout=%s ms (%s); '
                'closing connection so it is evicted from the pool.',
                call_timeout, err,
            )
            try:
                dbapi_conn.close()
            except Exception:  # noqa: BLE001
                pass
            return

    # Best-effort attributes — log WARNING and continue on failure.  Map
    # attr name -> settings key.
    best_effort = (
        ('stmtcachesize',     'ORACLE_STMTCACHESIZE'),
        ('autocommit',        'ORACLE_AUTOCOMMIT'),
        ('module',            'ORACLE_MODULE'),
        ('action',            'ORACLE_ACTION'),
        ('client_identifier', 'ORACLE_CLIENT_IDENTIFIER'),
        ('current_schema',    'ORACLE_CURRENT_SCHEMA'),
    )
    for attr, setting_name in best_effort:
        value = getattr(settings, setting_name, None)
        if value is None:
            continue
        try:
            setattr(dbapi_conn, attr, value)
        except Exception as err:  # noqa: BLE001
            logger.warning(
                'Oracle connect-listener: failed to set %s=%r (%s); continuing.',
                attr, value, err,
            )


def _apply_postgresql(dbapi_conn, settings):
    """Reserved for future PostgreSQL per-connection tuning."""
    return


def _apply_mysql(dbapi_conn, settings):
    """Reserved for future MySQL per-connection tuning."""
    return


def _apply_mssql(dbapi_conn, settings):
    """Reserved for future MSSQL per-connection tuning."""
    return


# Dispatch table keyed on SQLAlchemy dialect name (engine.dialect.name).
_DIALECT_HELPERS = {
    'oracle':     _apply_oracle,
    'postgresql': _apply_postgresql,
    'mysql':      _apply_mysql,
    'mssql':      _apply_mssql,
    'sqlite':     _apply_noop,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register(engine, settings):
    """Attach a ``connect`` event listener to *engine*.

    The listener resolves a per-dialect helper from :data:`_DIALECT_HELPERS`
    once, then calls it with the freshly-minted DBAPI connection on every
    new pool entry.  Unknown dialects silently use :func:`_apply_noop`.
    """
    dialect_name = engine.dialect.name
    helper = _DIALECT_HELPERS.get(dialect_name, _apply_noop)
    logger.debug(
        'db_listener: registering connect-listener for dialect=%s helper=%s',
        dialect_name, helper.__name__,
    )

    @event.listens_for(engine, 'connect')
    def _on_connect(dbapi_conn, connection_record):  # noqa: ARG001
        helper(dbapi_conn, settings)
