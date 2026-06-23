"""
settings.py

Configuration classes for the Grapinator application.

Two classes are defined here:

:class:`Settings`
    Reads all runtime configuration (WSGI, CORS, HTTP security headers, Flask,
    SQLAlchemy, Graphene) from an INI file encrypted with
    ``crypto_config.cryptoconfigparser``.  The encryption key is read from the
    ``GQLAPI_CRYPT_KEY`` environment variable at startup so that no secrets are
    stored in plain text on disk.

:class:`SchemaSettings`
    Parses the schema dictionary file (``schema.dct``) and exposes pre-built
    lists of ORM-class descriptors and GraphQL-class descriptors consumed by
    :mod:`grapinator.model` and :mod:`grapinator.schema` respectively.

Both classes are instantiated once at module level in :mod:`grapinator.__init__`
and imported throughout the package as singletons.
"""

import graphene
import logging
import os
from os import path
from datetime import datetime
from crypto_config import cryptoconfigparser

logger = logging.getLogger(__name__)


class _RedactedStr(str):
    """
    A ``str`` subclass that replaces its value with ``***REDACTED***`` in
    ``__repr__`` and ``__str__`` output.

    Used to hold database passwords and connection URIs so that accidental
    logging of the ``Settings`` object (e.g. via ``logger.debug('%s', settings.__dict__)``
    or ``repr(settings)``) never exposes credentials in log output.

    The underlying string value is preserved for programmatic use (e.g. when
    passed to SQLAlchemy's ``create_engine``).
    """

    def __repr__(self):
        return "'***REDACTED***'"

    def __str__(self):
        return '***REDACTED***'
from sqlalchemy.orm import (
    scoped_session
    ,sessionmaker
    ,relationship
    ,synonym
)
from sqlalchemy import (
    Column
    ,BigInteger
    ,Boolean
    ,Date
    ,DateTime
    ,Enum
    ,Float
    ,Integer
    ,Interval
    ,LargeBinary
    ,Numeric
    ,PickleType
    ,SmallInteger
    ,String
    ,Text
    ,Time
    ,Unicode
    ,UnicodeText
    )

class Settings(object):
    """
    Runtime configuration holder populated from an encrypted INI file.

    All class-level attributes default to ``None`` and are overwritten with
    values from the INI file by :meth:`__init__`.  Grouping them here makes
    the full set of supported settings visible at a glance and allows type
    checkers to reason about them.

    Attribute groups
    ~~~~~~~~~~~~~~~~
    **WSGI** — CherryPy socket and optional TLS certificate paths.

    **CORS** — Cross-Origin Resource Sharing policy used by
    ``flask_cors`` (or the CherryPy CORS tool).

    **HTTP_HEADERS** — Security-related response headers (X-Frame-Options,
    CSP, Referrer-Policy, etc.).

    **FLASK** — Flask server name, API endpoint path, and debug flag.

    **SQLALCHEMY** — Database connection components assembled into
    ``SQLALCHEMY_DATABASE_URI`` during ``__init__``.

    **GRAPHENE** — Path to the schema dictionary file.
    """

    # WSGI socket / TLS settings.
    #
    # As of release 2.1.12 the production WSGI server is Gunicorn (not
    # CherryPy).  Gunicorn reads WSGI_SOCKET_HOST / WSGI_SOCKET_PORT via the
    # bundled gunicorn.conf.py.  WSGI_SSL_CERT / WSGI_SSL_PRIVKEY are
    # deprecated -- TLS is now terminated by Nginx in front of Grapinator --
    # and a WARNING is logged at boot when either is present.
    WSGI_SOCKET_HOST = None
    WSGI_SOCKET_PORT = None
    WSGI_SSL_CERT = None              # deprecated: TLS terminated by Nginx
    WSGI_SSL_PRIVKEY = None           # deprecated: TLS terminated by Nginx
    WSGI_SOCKET_QUEUE_SIZE = None     # repurposed -> Gunicorn `backlog`
    WSGI_MAX_REQUEST_BODY_SIZE = None # deprecated: enforced by Nginx client_max_body_size
    WSGI_SHUTDOWN_TIMEOUT = None      # repurposed -> Gunicorn `graceful_timeout`

    # Gunicorn server settings (consumed by grapinator/resources/gunicorn.conf.py).
    # GUNICORN_WORKERS defaults to (2 * os.cpu_count() + 1) per the documented
    # sizing rule and is resolved at INI-load time; the other defaults match
    # the values published in docs/gunicorn.md.
    GUNICORN_WORKERS = None
    GUNICORN_THREADS = 8
    GUNICORN_WORKER_CLASS = 'gthread'
    GUNICORN_WORKER_CONNECTIONS = 1000   # only used with async workers
    GUNICORN_TIMEOUT = 30                # seconds; must exceed worst-case query
    GUNICORN_KEEPALIVE = 75              # seconds; matches Nginx upstream keepalive
    GUNICORN_MAX_REQUESTS = 1000         # worker auto-recycle
    GUNICORN_MAX_REQUESTS_JITTER = 100
    GUNICORN_LIMIT_REQUEST_LINE = 8190
    GUNICORN_LIMIT_REQUEST_FIELD_SIZE = 8190

    # CORS policy settings
    CORS_ENABLE = None
    CORS_EXPOSE_ORIGINS = None
    CORS_ALLOW_METHODS = None
    CORS_HEADER_MAX_AGE = None
    CORS_ALLOW_HEADERS = None
    CORS_EXPOSE_HEADERS = None
    CORS_SEND_WILDCARD = None
    CORS_SUPPORTS_CREDENTIALS = None

    # HTTP security-header settings
    HTTP_HEADERS_XFRAME = None
    HTTP_HEADERS_XSS_PROTECTION = None
    HTTP_HEADER_CACHE_CONTROL = None
    HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS = None
    HTTP_HEADERS_REFERRER_POLICY = None
    HTTP_HEADERS_CONTENT_SECURITY_POLICY = None

    # Graphene schema file path
    GQL_SCHEMA = None

    # Authentication / JWT settings (all optional; default to auth off)
    AUTH_MODE = 'off'              # 'off' | 'mixed' | 'required'
    AUTH_JWKS_URI = None           # JWKS endpoint URL (production IdP)
    AUTH_ISSUER = None             # Expected JWT issuer
    AUTH_AUDIENCE = None           # Expected JWT audience
    AUTH_ALGORITHMS = 'RS256'      # Allowed signing algorithms (comma-separated)
    AUTH_ROLES_CLAIM = 'roles'     # Dotted-path to roles list inside the JWT payload
    AUTH_JWKS_CACHE_TTL = 300      # Seconds to cache the JWK set
    GRAPHIQL_ACCESS = 'authenticated'  # 'authenticated' | 'open' | 'off'
    AUTH_DEV_SECRET = None         # HS256 secret for local dev tokens only

    # Flask application settings
    FLASK_SERVER_NAME = None
    FLASK_DEBUG = None
    FLASK_API_ENDPOINT = None

    # SQLAlchemy / database settings
    DB_USER = None
    DB_PASSWORD = None
    DB_CONNECT = None
    DB_TYPE = None
    SQLALCHEMY_TRACK_MODIFICATIONS = None

    # SQLAlchemy connection pool tuning (all optional; None defers to SA's default).
    # Defaults below are appropriate for a single-developer SQLite environment.
    # For Oracle/production deployments set these explicitly in the ini file —
    # see the [SQLALCHEMY] section of grapinator.ini and docs/grapinator_ini.md.
    DB_POOL_SIZE = None           # QueuePool persistent connections (SA default: 5)
    DB_POOL_MAX_OVERFLOW = None   # Burst connections above DB_POOL_SIZE (SA default: 10)
    DB_POOL_TIMEOUT = None        # Seconds to wait for a free connection (SA default: 30)
    DB_POOL_RECYCLE = None        # Seconds before recycling a connection (SA default: -1 = never)
    DB_POOL_PRE_PING = True       # Validate connection health before checkout (recommended: True)

    # Oracle per-connection knobs applied by grapinator.db_listener.
    # See docs/grapinator_ini.md for the full description.
    # ORACLE_CALL_TIMEOUT is mandatory when DB_TYPE contains 'oracle'; the
    # default of 15000 ms (15 s) is applied silently if the INI omits it.
    ORACLE_CALL_TIMEOUT = 15000
    ORACLE_STMTCACHESIZE = None
    ORACLE_AUTOCOMMIT = None
    ORACLE_MODULE = 'grapinator'
    ORACLE_ACTION = None
    ORACLE_CLIENT_IDENTIFIER = None
    ORACLE_CURRENT_SCHEMA = None
    
    def __init__(self, **kwargs):
        """
        Load and parse the encrypted INI configuration file.

        Reads the file path from *config_file*, resolves it relative to this
        module's directory, decrypts it using the ``GQLAPI_CRYPT_KEY``
        environment variable, and populates every attribute on the instance.

        ``SQLALCHEMY_DATABASE_URI`` is assembled here from the individual
        ``DB_*`` components.  For SQLite databases the URI omits credentials;
        all other database types use the
        ``<type>://<user>:<password>@<connect>`` format.

        Oracle-specific locale environment variables (``NLS_LANG``,
        ``NLS_DATE_FORMAT``) are set in ``os.environ`` when present in the
        ``[SQLALCHEMY]`` section so that cx_Oracle picks them up.

        :param config_file: Relative path (from this module's directory) to
                            the encrypted INI configuration file.  **Required**.
        :raises RuntimeError: If *config_file* is not provided, the
                              ``GQLAPI_CRYPT_KEY`` environment variable is
                              missing, or the INI file cannot be parsed.
        """
        config_file = kwargs.pop('config_file', None)
        if config_file != None:
            self.config_file = config_file
        else:
            raise RuntimeError('Could not parse config_file.')

        logger.debug('Settings: resolving config file: %s', config_file)

        # CryptoConfigParser reads the encryption key from the environment
        # so credentials are never stored in plain text.
        try:
            key = os.environ['GQLAPI_CRYPT_KEY']
        except KeyError as err:
            raise RuntimeError(f"Could not get env key: {err}")

        try:
            # Resolve path relative to this module's directory and parse.
            cwd = path.abspath(path.dirname(__file__))
            properties = cryptoconfigparser.CryptoConfigParser(crypt_key=key)
            properties_file = cwd + self.config_file
            logger.debug('Settings: reading properties file: %s', properties_file)
            properties.read(properties_file)

            # load WSGI section
            self.WSGI_SOCKET_HOST = properties.get('WSGI', 'WSGI_SOCKET_HOST')
            self.WSGI_SOCKET_PORT = properties.getint('WSGI', 'WSGI_SOCKET_PORT')
            # WSGI_SSL_* keys are deprecated -- TLS is now terminated by Nginx.
            # We still accept (and ignore) them so existing deployments keep
            # booting; a WARNING tells the operator to remove them.
            if properties.has_option('WSGI', 'WSGI_SSL_CERT') or properties.has_option('WSGI', 'WSGI_SSL_PRIVKEY'):
                logger.warning(
                    'WSGI_SSL_CERT/WSGI_SSL_PRIVKEY are deprecated as of 2.1.12 '
                    '-- TLS is now terminated by Nginx in front of Grapinator. '
                    'These keys are ignored; remove them from grapinator.ini.'
                )
                if properties.has_option('WSGI', 'WSGI_SSL_CERT'):
                    self.WSGI_SSL_CERT = properties.get('WSGI', 'WSGI_SSL_CERT')
                if properties.has_option('WSGI', 'WSGI_SSL_PRIVKEY'):
                    self.WSGI_SSL_PRIVKEY = properties.get('WSGI', 'WSGI_SSL_PRIVKEY')
            if properties.has_option('WSGI', 'WSGI_MAX_REQUEST_BODY_SIZE'):
                logger.warning(
                    'WSGI_MAX_REQUEST_BODY_SIZE is deprecated as of 2.1.12 -- '
                    'enforce request size at Nginx using client_max_body_size.'
                )
                self.WSGI_MAX_REQUEST_BODY_SIZE = properties.getint('WSGI', 'WSGI_MAX_REQUEST_BODY_SIZE')
            # WSGI_SOCKET_QUEUE_SIZE and WSGI_SHUTDOWN_TIMEOUT have been
            # repurposed as Gunicorn `backlog` / `graceful_timeout` inputs and
            # remain valid INI keys.
            if properties.has_option('WSGI', 'WSGI_SOCKET_QUEUE_SIZE'):
                self.WSGI_SOCKET_QUEUE_SIZE = properties.getint('WSGI', 'WSGI_SOCKET_QUEUE_SIZE')
            if properties.has_option('WSGI', 'WSGI_SHUTDOWN_TIMEOUT'):
                self.WSGI_SHUTDOWN_TIMEOUT = properties.getint('WSGI', 'WSGI_SHUTDOWN_TIMEOUT')
            # WSGI_THREAD_POOL and WSGI_ACCEPTED_QUEUE_SIZE were removed in
            # 2.1.12 (Gunicorn does not expose equivalents).  Hard-fail boot
            # rather than silently dropping the operator's intent.
            for _removed in ('WSGI_THREAD_POOL', 'WSGI_ACCEPTED_QUEUE_SIZE'):
                if properties.has_option('WSGI', _removed):
                    logger.error(
                        '%s was removed in 2.1.12; use the [GUNICORN] section '
                        'instead (see docs/gunicorn.md). Remove this key from '
                        'grapinator.ini and restart.', _removed
                    )
                    raise RuntimeError(
                        f'{_removed} is no longer supported (removed in 2.1.12).'
                    )

            # load GUNICORN section (entirely optional -- every key has a default)
            if properties.has_section('GUNICORN'):
                if properties.has_option('GUNICORN', 'GUNICORN_WORKERS'):
                    self.GUNICORN_WORKERS = properties.getint('GUNICORN', 'GUNICORN_WORKERS')
                if properties.has_option('GUNICORN', 'GUNICORN_THREADS'):
                    self.GUNICORN_THREADS = properties.getint('GUNICORN', 'GUNICORN_THREADS')
                if properties.has_option('GUNICORN', 'GUNICORN_WORKER_CLASS'):
                    self.GUNICORN_WORKER_CLASS = properties.get('GUNICORN', 'GUNICORN_WORKER_CLASS')
                if properties.has_option('GUNICORN', 'GUNICORN_WORKER_CONNECTIONS'):
                    self.GUNICORN_WORKER_CONNECTIONS = properties.getint('GUNICORN', 'GUNICORN_WORKER_CONNECTIONS')
                if properties.has_option('GUNICORN', 'GUNICORN_TIMEOUT'):
                    self.GUNICORN_TIMEOUT = properties.getint('GUNICORN', 'GUNICORN_TIMEOUT')
                if properties.has_option('GUNICORN', 'GUNICORN_KEEPALIVE'):
                    self.GUNICORN_KEEPALIVE = properties.getint('GUNICORN', 'GUNICORN_KEEPALIVE')
                if properties.has_option('GUNICORN', 'GUNICORN_MAX_REQUESTS'):
                    self.GUNICORN_MAX_REQUESTS = properties.getint('GUNICORN', 'GUNICORN_MAX_REQUESTS')
                if properties.has_option('GUNICORN', 'GUNICORN_MAX_REQUESTS_JITTER'):
                    self.GUNICORN_MAX_REQUESTS_JITTER = properties.getint('GUNICORN', 'GUNICORN_MAX_REQUESTS_JITTER')
                if properties.has_option('GUNICORN', 'GUNICORN_LIMIT_REQUEST_LINE'):
                    self.GUNICORN_LIMIT_REQUEST_LINE = properties.getint('GUNICORN', 'GUNICORN_LIMIT_REQUEST_LINE')
                if properties.has_option('GUNICORN', 'GUNICORN_LIMIT_REQUEST_FIELD_SIZE'):
                    self.GUNICORN_LIMIT_REQUEST_FIELD_SIZE = properties.getint('GUNICORN', 'GUNICORN_LIMIT_REQUEST_FIELD_SIZE')
            # GUNICORN_WORKERS defaults to (2 * CPU + 1) per the documented
            # sizing rule when not set in the INI.
            if self.GUNICORN_WORKERS is None:
                self.GUNICORN_WORKERS = 2 * (os.cpu_count() or 1) + 1

            # load CORS
            self.CORS_ENABLE = properties.getboolean('CORS', 'CORS_ENABLE')
            self.CORS_EXPOSE_ORIGINS = properties.get('CORS', 'CORS_EXPOSE_ORIGINS')
            self.CORS_ALLOW_METHODS = properties.get('CORS', 'CORS_ALLOW_METHODS')
            self.CORS_HEADER_MAX_AGE = properties.get('CORS', 'CORS_HEADER_MAX_AGE')
            self.CORS_ALLOW_HEADERS = properties.get('CORS', 'CORS_ALLOW_HEADERS')
            self.CORS_EXPOSE_HEADERS = properties.get('CORS', 'CORS_EXPOSE_HEADERS')
            self.CORS_SEND_WILDCARD = properties.getboolean('CORS', 'CORS_SEND_WILDCARD')
            self.CORS_SUPPORTS_CREDENTIALS = properties.getboolean('CORS', 'CORS_SUPPORTS_CREDENTIALS')

            # load HTTP_HEADERS
            self.HTTP_HEADERS_XFRAME = properties.get('HTTP_HEADERS', 'HTTP_HEADERS_XFRAME')
            self.HTTP_HEADERS_XSS_PROTECTION = properties.get('HTTP_HEADERS', 'HTTP_HEADERS_XSS_PROTECTION')
            self.HTTP_HEADER_CACHE_CONTROL = properties.get('HTTP_HEADERS', 'HTTP_HEADER_CACHE_CONTROL')
            self.HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS = properties.get('HTTP_HEADERS', 'HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS')
            self.HTTP_HEADERS_REFERRER_POLICY = properties.get('HTTP_HEADERS', 'HTTP_HEADERS_REFERRER_POLICY')
            self.HTTP_HEADERS_CONTENT_SECURITY_POLICY = properties.get('HTTP_HEADERS', 'HTTP_HEADERS_CONTENT_SECURITY_POLICY')

            # load FLASK section
            self.FLASK_SERVER_NAME = properties.get('FLASK', 'FLASK_SERVER_NAME')
            self.FLASK_API_ENDPOINT = properties.get('FLASK', 'FLASK_API_ENDPOINT')
            self.FLASK_DEBUG = properties.getboolean('FLASK', 'FLASK_DEBUG')

            # load SQLALCHEMY section
            self.DB_TYPE = properties.get('SQLALCHEMY', 'DB_TYPE')
            # DB_USER and DB_PASSWORD are optional (not used for SQLite).
            if properties.has_option('SQLALCHEMY', 'DB_USER'):
                self.DB_USER = properties.get('SQLALCHEMY', 'DB_USER')
            if properties.has_option('SQLALCHEMY', 'DB_PASSWORD'):
                self.DB_PASSWORD = properties.get('SQLALCHEMY', 'DB_PASSWORD')
            self.DB_CONNECT = properties.get('SQLALCHEMY', 'DB_CONNECT')
            # SQLite URIs omit credentials; all other dialects use the standard
            # user:password@host/dbname form.
            # Both DB_PASSWORD and SQLALCHEMY_DATABASE_URI are wrapped in
            # _RedactedStr so accidental logging of the Settings object never
            # exposes credentials in plaintext log output.
            # IMPORTANT: build the URI with the plaintext password BEFORE
            # wrapping DB_PASSWORD in _RedactedStr.  _RedactedStr overrides
            # __str__ to return '***REDACTED***', so using it inside an
            # f-string would embed the literal string '***REDACTED***' in the
            # URI instead of the real password, causing ORA-01017 / auth errors.
            if 'sqlite' in self.DB_TYPE:
                self.SQLALCHEMY_DATABASE_URI = _RedactedStr(
                    f"{self.DB_TYPE}://{self.DB_CONNECT}"
                )
            else:
                self.SQLALCHEMY_DATABASE_URI = _RedactedStr(
                    f"{self.DB_TYPE}://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_CONNECT}"
                )
                self.DB_PASSWORD = _RedactedStr(self.DB_PASSWORD)

            self.SQLALCHEMY_TRACK_MODIFICATIONS = properties.getboolean('SQLALCHEMY', 'SQLALCHEMY_TRACK_MODIFICATIONS')

            # Connection pool settings — all optional; None means use SQLAlchemy's
            # own default.  Only values explicitly present in the ini file are
            # loaded to avoid passing None to create_engine(), which would shadow
            # SQLAlchemy's internal defaults.
            if properties.has_option('SQLALCHEMY', 'DB_POOL_SIZE'):
                self.DB_POOL_SIZE = properties.getint('SQLALCHEMY', 'DB_POOL_SIZE')
            if properties.has_option('SQLALCHEMY', 'DB_POOL_MAX_OVERFLOW'):
                self.DB_POOL_MAX_OVERFLOW = properties.getint('SQLALCHEMY', 'DB_POOL_MAX_OVERFLOW')
            if properties.has_option('SQLALCHEMY', 'DB_POOL_TIMEOUT'):
                self.DB_POOL_TIMEOUT = properties.getfloat('SQLALCHEMY', 'DB_POOL_TIMEOUT')
            if properties.has_option('SQLALCHEMY', 'DB_POOL_RECYCLE'):
                self.DB_POOL_RECYCLE = properties.getint('SQLALCHEMY', 'DB_POOL_RECYCLE')
            if properties.has_option('SQLALCHEMY', 'DB_POOL_PRE_PING'):
                self.DB_POOL_PRE_PING = properties.getboolean('SQLALCHEMY', 'DB_POOL_PRE_PING')

            # Oracle per-connection knobs (consumed by grapinator.db_listener).
            # All optional; defaults are set at class level.
            for _opt, _kind in (
                ('ORACLE_CALL_TIMEOUT', 'int'),
                ('ORACLE_STMTCACHESIZE', 'int'),
                ('ORACLE_AUTOCOMMIT', 'bool'),
                ('ORACLE_MODULE', 'str'),
                ('ORACLE_ACTION', 'str'),
                ('ORACLE_CLIENT_IDENTIFIER', 'str'),
                ('ORACLE_CURRENT_SCHEMA', 'str'),
            ):
                if properties.has_option('SQLALCHEMY', _opt):
                    if _kind == 'int':
                        setattr(self, _opt, properties.getint('SQLALCHEMY', _opt))
                    elif _kind == 'bool':
                        setattr(self, _opt, properties.getboolean('SQLALCHEMY', _opt))
                    else:
                        setattr(self, _opt, properties.get('SQLALCHEMY', _opt))

            # load GRAPHENE section
            self.GQL_SCHEMA = properties.get('GRAPHENE', 'GQL_SCHEMA')

            # load AUTH section (entirely optional — defaults are set above)
            if properties.has_section('AUTH'):
                if properties.has_option('AUTH', 'AUTH_MODE'):
                    self.AUTH_MODE = properties.get('AUTH', 'AUTH_MODE').lower()
                if properties.has_option('AUTH', 'AUTH_JWKS_URI'):
                    self.AUTH_JWKS_URI = properties.get('AUTH', 'AUTH_JWKS_URI')
                if properties.has_option('AUTH', 'AUTH_ISSUER'):
                    self.AUTH_ISSUER = properties.get('AUTH', 'AUTH_ISSUER')
                if properties.has_option('AUTH', 'AUTH_AUDIENCE'):
                    self.AUTH_AUDIENCE = properties.get('AUTH', 'AUTH_AUDIENCE')
                if properties.has_option('AUTH', 'AUTH_ALGORITHMS'):
                    self.AUTH_ALGORITHMS = properties.get('AUTH', 'AUTH_ALGORITHMS')
                if properties.has_option('AUTH', 'AUTH_ROLES_CLAIM'):
                    self.AUTH_ROLES_CLAIM = properties.get('AUTH', 'AUTH_ROLES_CLAIM')
                if properties.has_option('AUTH', 'AUTH_JWKS_CACHE_TTL'):
                    self.AUTH_JWKS_CACHE_TTL = properties.getint('AUTH', 'AUTH_JWKS_CACHE_TTL')
                if properties.has_option('AUTH', 'GRAPHIQL_ACCESS'):
                    self.GRAPHIQL_ACCESS = properties.get('AUTH', 'GRAPHIQL_ACCESS').lower()
                if properties.has_option('AUTH', 'AUTH_DEV_SECRET'):
                    self.AUTH_DEV_SECRET = properties.get('AUTH', 'AUTH_DEV_SECRET')

            # Oracle-specific locale settings consumed by cx_Oracle.
            # Only set when the options are present in the config file.
            if properties.has_option('SQLALCHEMY', 'ORCL_NLS_LANG'):
                os.environ['NLS_LANG'] = properties.get('SQLALCHEMY', 'ORCL_NLS_LANG')
            if properties.has_option('SQLALCHEMY', 'ORCL_NLS_DATE_FORMAT'):
                os.environ['NLS_DATE_FORMAT'] = properties.get('SQLALCHEMY', 'ORCL_NLS_DATE_FORMAT')

            # ORACLE_CALL_TIMEOUT must be strictly positive and strictly less
            # than the Gunicorn request timeout (so the DB driver aborts the
            # query before Gunicorn kills the worker).  Only enforced when
            # the active dialect is Oracle.
            if self.DB_TYPE and 'oracle' in self.DB_TYPE:
                if self.ORACLE_CALL_TIMEOUT is None or self.ORACLE_CALL_TIMEOUT <= 0:
                    raise RuntimeError(
                        'ORACLE_CALL_TIMEOUT must be a positive integer (ms) '
                        'when DB_TYPE is Oracle.'
                    )
                if self.ORACLE_CALL_TIMEOUT >= self.GUNICORN_TIMEOUT * 1000:
                    raise RuntimeError(
                        f'ORACLE_CALL_TIMEOUT ({self.ORACLE_CALL_TIMEOUT} ms) '
                        f'must be strictly less than GUNICORN_TIMEOUT '
                        f'({self.GUNICORN_TIMEOUT} s = {self.GUNICORN_TIMEOUT * 1000} ms) '
                        'so the Oracle driver aborts the call before Gunicorn '
                        'kills the worker.'
                    )

            if self.AUTH_DEV_SECRET:
                _DEFAULT_DEV_SECRET = 'change-me-local-dev-only'
                if (self.AUTH_DEV_SECRET == _DEFAULT_DEV_SECRET
                        and self.AUTH_MODE != 'off'
                        and not self.AUTH_JWKS_URI):
                    raise RuntimeError(
                        'AUTH_DEV_SECRET must be changed from the default value '
                        'before enabling auth (AUTH_MODE is not "off" and no '
                        'AUTH_JWKS_URI is configured).'
                    )
                logger.warning(
                    'AUTH_DEV_SECRET is set — HS256 local-dev mode active. '
                    'Never use AUTH_DEV_SECRET in production.'
                )
            if self.FLASK_DEBUG and self.AUTH_MODE != 'off':
                logger.warning(
                    'FLASK_DEBUG=True with auth enabled (AUTH_MODE=%s) — '
                    'Flask\'s interactive debugger exposes a Python REPL over '
                    'HTTP and bypasses all authentication. Never deploy this '
                    'configuration.',
                    self.AUTH_MODE,
                )
            logger.debug(
                'Settings: WSGI=%s:%s TLS=%s CORS_ENABLE=%s',
                self.WSGI_SOCKET_HOST, self.WSGI_SOCKET_PORT,
                'on' if self.WSGI_SSL_CERT else 'off',
                self.CORS_ENABLE,
            )
            logger.debug(
                'Settings: DB_TYPE=%s AUTH_MODE=%s GRAPHIQL_ACCESS=%s',
                self.DB_TYPE, self.AUTH_MODE, self.GRAPHIQL_ACCESS,
            )
            logger.debug(
                'Settings: pool_size=%s max_overflow=%s timeout=%s recycle=%s pre_ping=%s',
                self.DB_POOL_SIZE, self.DB_POOL_MAX_OVERFLOW,
                self.DB_POOL_TIMEOUT, self.DB_POOL_RECYCLE, self.DB_POOL_PRE_PING,
            )

        except cryptoconfigparser.ParsingError as err:
            raise RuntimeError(f"Could not parse: {err}")

class SchemaSettings(object):
    """
    Parser and cache for the Grapinator schema dictionary (``schema.dct``).

    The schema dictionary is a Python list of dicts, each describing one
    database table: its ORM class name, table name, primary key, column
    definitions, and SQLAlchemy relationships.  This class reads the file
    once at construction time and pre-builds two derived lists:

    - ``_db_classes``  — consumed by :mod:`grapinator.model` to create
      SQLAlchemy ORM classes dynamically.
    - ``_gql_classes`` — consumed by :mod:`grapinator.schema` to create
      Graphene ``SQLAlchemyObjectType`` subclasses dynamically.

    The schema file is executed in a restricted namespace (no builtins) to
    prevent arbitrary code execution while still allowing the SQLAlchemy and
    Graphene type references that appear in the schema dictionary.
    """

    def __init__(self, *args, **kwargs):
        """
        Load and pre-process the schema dictionary file.

        Resolves *schema_file* relative to this module's directory, parses it
        via :meth:`_loadSchemaDict`, then builds the ORM and GraphQL class
        descriptor lists that are returned by :meth:`get_db_classes` and
        :meth:`get_gql_classes`.

        :param schema_file: Relative path (from this module's directory) to
                            the schema dictionary file.  **Required**.
        :raises TypeError: If *schema_file* is not provided.
        """
        file = kwargs.pop('schema_file', None)
        if file != None:
            # load file
            cwd = path.abspath(path.dirname(__file__))
            self._schema_dict = self._loadSchemaDict(cwd + file)

            self._db_classes = self._make_db_classes()
            self._gql_classes = self._make_gql_classes()
        else:
            raise TypeError("schema_file arg not set!")


    def _loadSchemaDict(self, file_name):
        """
        Read and evaluate the schema dictionary file in a restricted namespace.

        The file is expected to contain a single Python expression — a list of
        dicts — that is assigned to ``schema_dict``.  Executing it with
        ``__builtins__`` removed and only the required SQLAlchemy / Graphene
        symbols available prevents arbitrary code execution while still
        supporting the type references used in column definitions.

        :param file_name: Absolute path to the schema dictionary file.
        :returns:         The parsed schema list (list of dicts).
        :raises OSError:  If the file cannot be read.
        """
        safe_namespace = {
            '__builtins__': {},  # Remove all builtins for security
            'graphene': graphene,
            'Column': Column,
            'BigInteger': BigInteger,
            'Boolean': Boolean,
            'Date': Date,
            'DateTime': DateTime,
            'Enum': Enum,
            'Float': Float,
            'Integer': Integer,
            'Interval': Interval,
            'LargeBinary': LargeBinary,
            'Numeric': Numeric,
            'PickleType': PickleType,
            'SmallInteger': SmallInteger,
            'String': String,
            'Text': Text,
            'Time': Time,
            'Unicode': Unicode,
            'UnicodeText': UnicodeText,
            'relationship': relationship,
            'synonym': synonym,
        }
        
        with open(file_name, 'r') as f:
            schema_content = f.read()

        # Wrap the raw dict/list expression in an assignment then execute it
        # in the restricted namespace so we can extract the result safely.
        local_namespace = {}
        exec(f"schema_dict = {schema_content}", safe_namespace, local_namespace)
        return local_namespace['schema_dict']

    def _make_db_classes(self):
        """
        Build the list of ORM class descriptor dicts from the schema dictionary.

        Each descriptor contains the information needed by
        :func:`grapinator.model.orm_class_constructor` to create one
        SQLAlchemy mapped class: class name, table name, primary key columns,
        column definitions, and relationship definitions.

        Fields with an empty ``db_col_name`` (e.g. resolver-backed virtual
        fields) are excluded because they have no corresponding DB column.

        :returns: List of ORM class descriptor dicts, one per schema entry.
        """
        db_classes = []
        for row in self._schema_dict:
            db_class_cols = [{
                'name':r['gql_col_name']
                ,'db_col_name':r['db_col_name']
                ,'db_type':r['db_type']
                } for r in row['FIELDS'] if r['db_col_name']]
            db_class_relation = [{
                'name':r['rel_name']
                ,'class_name':r['rel_class_name']
                ,'arguments':r['rel_arguments']
                } for r in row['RELATIONSHIPS']]
            db_class = {
                'db_class': row['DB_CLASS_NAME']
                ,'db_table': row['DB_TABLE_NAME']
                ,'db_pk': row['DB_TABLE_PK']
                ,'db_columns': db_class_cols
                ,'db_relationships': db_class_relation
                }
            db_classes.append(db_class)
        return db_classes

    def _make_gql_classes(self):
        """
        Build the list of GraphQL class descriptor dicts from the schema dictionary.

        Each descriptor contains the information needed by
        :func:`grapinator.schema.gql_class_constructor` to create one
        Graphene ``SQLAlchemyObjectType`` subclass: class name, connection
        query name, backing ORM class name, column metadata, and the default
        sort column.

        Optional per-field keys (``gql_of_type``, ``gql_isqueryable``,
        ``gql_ishidden``, ``gql_isresolver``, ``gql_resolver_func``) are
        normalised with safe defaults here so consumers never need to check
        for missing keys.

        :returns: List of GraphQL class descriptor dicts, one per schema entry.
        """
        gql_classes = []
        for row in self._schema_dict:
            gql_class_cols = [{
                'name':r['gql_col_name']
                ,'type':r['gql_type']
                # check if field gql_description is present and non-empty; if so, use it, otherwise set to None
                ,'desc':r['gql_description'] if 'gql_description' in r and r['gql_description'] else None
                # check if field gql_deprecation_reason is present and non-empty; if so, use it, otherwise set to None
                ,'deprecation_reason': r['gql_deprecation_reason'] if 'gql_deprecation_reason' in r and r['gql_deprecation_reason'] else None
                ,'type_args': r['gql_of_type'] if 'gql_of_type' in r else None
                ,'isqueryable': r['gql_isqueryable'] if 'gql_isqueryable' in r else True
                ,'ishidden': r['gql_ishidden'] if 'gql_ishidden' in r else False
                ,'isresolver': r['gql_isresolver'] if 'gql_isresolver' in r else False
                ,'resolver_func':r['gql_resolver_func'] if 'gql_resolver_func' in r else None
                # gql_auth_roles: list of role strings required to read this field; None/absent = public
                ,'auth_roles': r['gql_auth_roles'] if 'gql_auth_roles' in r and r['gql_auth_roles'] else None
                } for r in row['FIELDS']]
            gql_class = {
                'gql_class': row['GQL_CLASS_NAME']
                ,'gql_conn_query_name': row['GQL_CONN_QUERY_NAME']
                ,'gql_db_class': row['DB_CLASS_NAME']
                ,'gql_columns': gql_class_cols
                ,'gql_db_default_sort_col': row['DB_DEFAULT_SORT_COL']
                # AUTH_ROLES: entity-level role list; absent/None means public (no restriction)
                ,'gql_entity_auth_roles': row['AUTH_ROLES'] if 'AUTH_ROLES' in row and row['AUTH_ROLES'] else None
                }
            gql_classes.append(gql_class)
        return gql_classes

    def get_db_classes(self):
        """
        Return the pre-built list of ORM class descriptor dicts.

        :returns: List of dicts as produced by :meth:`_make_db_classes`.
        """
        return self._db_classes

    def get_gql_classes(self):
        """
        Return the pre-built list of GraphQL class descriptor dicts.

        :returns: List of dicts as produced by :meth:`_make_gql_classes`.
        """
        return self._gql_classes
