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
import os
from os import path
from datetime import datetime
from crypto_config import cryptoconfigparser
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

    # WSGI / CherryPy server settings
    WSGI_SOCKET_HOST = None
    WSGI_SOCKET_PORT = None
    WSGI_SSL_CERT = None       # Optional: path to TLS certificate file
    WSGI_SSL_PRIVKEY = None    # Optional: path to TLS private key file

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
            properties.read(properties_file)

            # load WSGI section
            self.WSGI_SOCKET_HOST = properties.get('WSGI', 'WSGI_SOCKET_HOST')
            self.WSGI_SOCKET_PORT = properties.getint('WSGI', 'WSGI_SOCKET_PORT')
            # SSL cert and key are optional; only set when both options are present.
            if properties.has_option('WSGI', 'WSGI_SSL_CERT') and properties.has_option('WSGI', 'WSGI_SSL_PRIVKEY'):
                self.WSGI_SSL_CERT = properties.get('WSGI', 'WSGI_SSL_CERT')
                self.WSGI_SSL_PRIVKEY = properties.get('WSGI', 'WSGI_SSL_PRIVKEY')

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
            if 'sqlite' in self.DB_TYPE:
                self.SQLALCHEMY_DATABASE_URI = f"{self.DB_TYPE}://{self.DB_CONNECT}"
            else:
                self.SQLALCHEMY_DATABASE_URI = f"{self.DB_TYPE}://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_CONNECT}"

            self.SQLALCHEMY_TRACK_MODIFICATIONS = properties.getboolean('SQLALCHEMY', 'SQLALCHEMY_TRACK_MODIFICATIONS')

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
