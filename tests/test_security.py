"""
test_security.py

Regression tests that verify the three HIGH/MEDIUM security fixes from the
April 2026 security analysis:

  1. JWT 'none' algorithm block (HIGH — auth bypass)
  2. sort_by column validation (HIGH — unvalidated getattr)
  3. Regex pattern length cap (MEDIUM — ReDoS)
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import time
import unittest
import hashlib
import tempfile
from unittest.mock import MagicMock, patch

from . import context  # noqa: F401

import jwt as pyjwt

from grapinator.auth import BearerAuthMiddleware
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from grapinator.security import register_model_policy, set_request_context
from grapinator.query_limits import (
    QueryLimitsRule,
    load_persisted_queries,
    resolve_persisted_query,
)
from graphql import (
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    specified_rules,
    validate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEV_SECRET = 'test-dev-secret-do-not-use-in-production'


_PolicyBase = declarative_base()


class _PolicyParent(_PolicyBase):
    __tablename__ = 'policy_parents'
    id = Column(Integer, primary_key=True)
    items = relationship('_PolicyItem', back_populates='parent')


class _PolicyItem(_PolicyBase):
    __tablename__ = 'policy_items'
    id = Column(Integer, primary_key=True)
    parent_id = Column(ForeignKey('policy_parents.id'))
    tenant_id = Column(String, nullable=False)
    value = Column(String)
    parent = relationship('_PolicyParent', back_populates='items')


_policy_engine = create_engine('sqlite:///:memory:')
_PolicyBase.metadata.create_all(_policy_engine)
_PolicySession = sessionmaker(bind=_policy_engine)
register_model_policy(
    _PolicyItem,
    roles=['reader'],
    row_auth_claims={'tenant_id': 'organization.id'},
)

with _PolicySession() as _seed_session:
    _seed_session.add(_PolicyParent(id=1, items=[
        _PolicyItem(id=1, tenant_id='alpha', value='visible'),
        _PolicyItem(id=2, tenant_id='beta', value='other tenant'),
    ]))
    _seed_session.commit()


class TestRequestScopedOrmPolicies(unittest.TestCase):
    def setUp(self):
        self.session = _PolicySession()
        self.addCleanup(self.session.close)

    def _set_context(self, roles=None, claims=None):
        set_request_context(self.session, {
            'user_roles': roles or [],
            'user_claims': claims or {},
        })

    def test_row_policy_scopes_direct_queries(self):
        self._set_context(['reader'], {'organization': {'id': 'alpha'}})
        rows = self.session.query(_PolicyItem).all()
        self.assertEqual([row.id for row in rows], [1])

    def test_missing_row_claim_fails_closed(self):
        self._set_context(['reader'], {})
        self.assertEqual(self.session.query(_PolicyItem).all(), [])

    def test_non_scalar_row_claim_fails_closed(self):
        self._set_context(['reader'], {'organization': {'id': ['alpha']}})
        self.assertEqual(self.session.query(_PolicyItem).all(), [])

    def test_entity_role_applies_to_identity_lookup(self):
        self._set_context([], {'organization': {'id': 'alpha'}})
        self.assertIsNone(self.session.get(_PolicyItem, 1))

    def test_policies_apply_to_relationship_loads(self):
        self._set_context(['reader'], {'organization': {'id': 'alpha'}})
        parent = self.session.get(_PolicyParent, 1)
        self.assertEqual([item.id for item in parent.items], [1])

    def test_entity_role_denies_relationship_loads(self):
        self._set_context([], {'organization': {'id': 'alpha'}})
        parent = self.session.get(_PolicyParent, 1)
        self.assertEqual(parent.items, [])

    def test_generated_relationship_resolver_applies_sql_limit(self):
        from grapinator.schema import _resolve_relationship_list
        self._set_context(['reader'], {'organization': {'id': 'alpha'}})
        parent = self.session.get(_PolicyParent, 1)
        with patch('grapinator.schema.db_session', self.session):
            items = _resolve_relationship_list(parent, 'items', max_rows=1)
        self.assertEqual([item.id for item in items], [1])


class TestGraphQLQueryLimits(unittest.TestCase):
    def setUp(self):
        self.leaf_type = GraphQLObjectType(
            'LimitLeaf', {'value': GraphQLField(GraphQLString)}
        )
        self.query_type = GraphQLObjectType(
            'LimitQuery', {
                'root': GraphQLField(self.leaf_type),
                'value': GraphQLField(GraphQLString),
            }
        )
        self.schema = GraphQLSchema(query=self.query_type)

    def test_measure_counts_fields_aliases_depth_and_cost(self):
        document = parse('query { alias: root { value } }')
        operation = document.definitions[0]
        counts = QueryLimitsRule._measure(operation.selection_set, {})
        self.assertEqual(counts, (2, 1, 2, 3))

    def test_complexity_weights_connection_pages(self):
        from graphql import GraphQLArgument, GraphQLInt, GraphQLList
        edge_type = GraphQLObjectType(
            'LimitEdge', {'node': GraphQLField(self.leaf_type)}
        )
        connection_type = GraphQLObjectType(
            'LimitConnection', {'edges': GraphQLField(GraphQLList(edge_type))}
        )
        query_type = GraphQLObjectType(
            'LimitRoot', {
                'items': GraphQLField(
                    connection_type,
                    args={'first': GraphQLArgument(GraphQLInt)},
                )
            }
        )
        schema = GraphQLSchema(query=query_type)
        document = parse('{ items(first: 2) { edges { node { value } } } }')
        counts = QueryLimitsRule._measure(
            document.definitions[0].selection_set,
            {},
            schema=schema,
            parent_type=query_type,
        )
        self.assertEqual(counts[3], 19)

    def test_depth_limit_is_enforced_during_validation(self):
        class ShallowLimitsRule(QueryLimitsRule):
            GQL_MAX_QUERY_DEPTH = 1

        errors = validate(
            self.schema,
            parse('{ root { value } }'),
            rules=specified_rules + (ShallowLimitsRule,),
        )
        self.assertIn('depth', errors[0].message.lower())

    def test_alias_and_complexity_limits_are_enforced(self):
        class StrictLimitsRule(QueryLimitsRule):
            GQL_MAX_ALIASES = 1
            GQL_MAX_QUERY_COMPLEXITY = 2

        errors = validate(
            self.schema,
            parse('{ first: root { value } second: value }'),
            rules=specified_rules + (StrictLimitsRule,),
        )
        messages = [error.message for error in errors]
        self.assertTrue(any('alias' in message.lower() for message in messages))
        self.assertTrue(any('complexity' in message.lower() for message in messages))

    def test_field_count_limit_is_enforced_during_validation(self):
        class SmallFieldCountRule(QueryLimitsRule):
            GQL_MAX_QUERY_FIELDS = 1

        errors = validate(
            self.schema,
            parse('{ __typename __typename }'),
            rules=specified_rules + (SmallFieldCountRule,),
        )
        self.assertIn('field count', errors[0].message.lower())

    def test_static_persisted_query_can_be_resolved_by_hash(self):
        query = '{ __typename }'
        query_hash = hashlib.sha256(query.encode('utf-8')).hexdigest()
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as query_file:
            import json
            json.dump({query_hash: query}, query_file)
            query_file.flush()
            persisted = load_persisted_queries(query_file.name)
        resolved = resolve_persisted_query(
            None,
            {'persistedQuery': {'version': 1, 'sha256Hash': query_hash}},
            persisted,
        )
        self.assertEqual(resolved, query)

    def test_unregistered_persisted_query_is_rejected(self):
        with self.assertRaises(GraphQLError):
            resolve_persisted_query(
                '{ __typename }', None, {'0' * 64: '{ __typename }'}
            )


def _mock_settings(**overrides):
    s = MagicMock()
    s.AUTH_MODE = overrides.get('AUTH_MODE', 'required')
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
    return MagicMock(return_value=[b'ok'])


def _make_environ(method='POST', token=None):
    env = {
        'REQUEST_METHOD': method,
        'PATH_INFO': '/gql',
        'HTTP_ACCEPT': 'application/json',
        'QUERY_STRING': '',
    }
    if token:
        env['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return env


# ---------------------------------------------------------------------------
# Fix 1: JWT 'none' algorithm block
# ---------------------------------------------------------------------------

class TestJwtNoneAlgorithmBlocked(unittest.TestCase):
    """
    Regression tests for HIGH: JWT 'none' algorithm must never be accepted.

    PyJWT will accept unsigned tokens when 'none' appears in the algorithms
    list passed to jwt.decode(). Verify that BearerAuthMiddleware strips it
    regardless of what AUTH_ALGORITHMS is configured to.
    """

    def test_none_algorithm_stripped_from_list(self):
        """'none' alone raises ValueError because no valid algorithms remain."""
        with self.assertRaises(ValueError):
            BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_ALGORITHMS='none'))

    def test_none_mixed_with_rs256_stripped(self):
        """'none' is stripped when mixed with a valid algorithm."""
        mw = BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_ALGORITHMS='RS256,none'))
        self.assertNotIn('none', mw.algorithms)
        self.assertIn('RS256', mw.algorithms)

    def test_none_case_insensitive(self):
        """'NONE', 'None', 'none' are all stripped."""
        for variant in ('NONE', 'None', 'none', ' none '):
            mw = BearerAuthMiddleware(
                _downstream(), _mock_settings(AUTH_ALGORITHMS=f'HS256,{variant}')
            )
            for alg in mw.algorithms:
                self.assertNotEqual(alg.lower(), 'none',
                                    f"'{variant}' was not stripped from algorithms list")

    def test_only_none_raises_value_error(self):
        """Setting AUTH_ALGORITHMS to only 'none' raises ValueError at init."""
        with self.assertRaises(ValueError) as ctx:
            BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_ALGORITHMS='none'))
        self.assertIn("'none'", str(ctx.exception))

    def test_empty_algorithms_after_strip_raises_value_error(self):
        """All algorithms stripped results in ValueError, not silent fallback."""
        with self.assertRaises(ValueError):
            BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_ALGORITHMS='none, none'))

    def test_none_algorithm_token_rejected_returns_401(self):
        """
        A token that claims alg=none in its header is rejected with 401,
        not accepted as authenticated.
        """
        # Craft a raw 'alg=none' token manually — PyJWT refuses to encode with
        # none, so we build the header/payload manually and leave the signature empty.
        import base64, json as _json
        header = base64.urlsafe_b64encode(
            _json.dumps({'alg': 'none', 'typ': 'JWT'}).encode()
        ).rstrip(b'=').decode()
        payload = base64.urlsafe_b64encode(
            _json.dumps({'sub': 'attacker', 'roles': ['admin'],
                         'exp': int(time.time()) + 3600}).encode()
        ).rstrip(b'=').decode()
        none_token = f'{header}.{payload}.'

        mw = BearerAuthMiddleware(_downstream(), _mock_settings(AUTH_MODE='required'))
        start_response = MagicMock()
        mw(_make_environ(token=none_token), start_response)

        # start_response must have been called with 401
        args = start_response.call_args[0]
        self.assertEqual(args[0], '401 Unauthorized')

    def test_valid_hs256_token_still_accepted(self):
        """Removing 'none' does not break acceptance of a valid HS256 token."""
        now = int(time.time())
        token = pyjwt.encode(
            {'sub': 'user', 'roles': ['reader'], 'iat': now, 'exp': now + 3600},
            DEV_SECRET, algorithm='HS256',
        )
        mw = BearerAuthMiddleware(
            _downstream(), _mock_settings(AUTH_MODE='required', AUTH_ALGORITHMS='HS256,none')
        )
        start_response = MagicMock()
        result = mw(_make_environ(token=token), start_response)
        self.assertEqual(result, [b'ok'])


# ---------------------------------------------------------------------------
# Fix 2: sort_by column validation
# ---------------------------------------------------------------------------

class TestSortByValidation(unittest.TestCase):
    """
    Regression tests for HIGH: sort_by must be validated against real model
    columns before being passed to getattr.
    """

    def _run_get_query(self, model, info, **kwargs):
        from grapinator.schema import MyConnectionField
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.order_by = MagicMock(return_value=mock_query)
        with patch.object(
            MyConnectionField.__bases__[0], 'get_query', return_value=mock_query
        ):
            result = MyConnectionField.get_query(model, info, **kwargs)
        return result, mock_query

    def _make_info(self, roles=None):
        info = MagicMock()
        info.context = {'user_roles': roles or [], 'authenticated': bool(roles)}
        return info

    def _make_model(self, col_name='employee_id'):
        """Return a mock model that has exactly one real column attribute."""
        model = MagicMock()
        model.__name__ = 'db_TestModel'
        # Simulate a SQLAlchemy InstrumentedAttribute (has .property)
        col_attr = MagicMock()
        col_attr.property = MagicMock()
        setattr(model, col_name, col_attr)

        # Make hasattr return False for any other attribute name
        original_hasattr = hasattr
        def _controlled_hasattr(obj, name):
            if obj is model:
                return name == col_name
            return original_hasattr(obj, name)

        self._hasattr_patcher = patch('builtins.hasattr', side_effect=_controlled_hasattr)
        self._hasattr_patcher.start()
        self.addCleanup(self._hasattr_patcher.stop)
        return model

    def test_valid_sort_column_accepted(self):
        """A valid column name is passed through to ORDER BY."""
        from grapinator.schema import MyConnectionField
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.order_by = MagicMock(return_value=mock_query)

        # Use actual imported model and a known-good column
        from grapinator.model import db_Employees
        info = self._make_info()
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            MyConnectionField.get_query(db_Employees, info, sort_by='employee_id')
        mock_query.order_by.assert_called_once()

    def test_nonexistent_column_ignored(self):
        """A column name that doesn't exist on the model is silently ignored."""
        from grapinator.schema import MyConnectionField
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.order_by = MagicMock(return_value=mock_query)

        from grapinator.model import db_Employees
        info = self._make_info()
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            # Should not raise AttributeError
            MyConnectionField.get_query(db_Employees, info, sort_by='nonexistent_column_xyz')
        mock_query.order_by.assert_not_called()

    def test_private_attribute_rejected(self):
        """Attribute names starting with '_' are rejected."""
        from grapinator.schema import MyConnectionField
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.order_by = MagicMock(return_value=mock_query)

        from grapinator.model import db_Employees
        info = self._make_info()
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            MyConnectionField.get_query(db_Employees, info, sort_by='__class__')
        mock_query.order_by.assert_not_called()

    def test_dunder_rejected(self):
        """Double-underscore dunder names are rejected."""
        from grapinator.schema import MyConnectionField
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.order_by = MagicMock(return_value=mock_query)

        from grapinator.model import db_Employees
        info = self._make_info()
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            MyConnectionField.get_query(db_Employees, info, sort_by='__init__')
        mock_query.order_by.assert_not_called()


# ---------------------------------------------------------------------------
# Fix 3: Regex pattern length cap (ReDoS prevention)
# ---------------------------------------------------------------------------

class TestRegexLengthCap(unittest.TestCase):
    """
    Regression tests for MEDIUM: client-supplied regex patterns longer than
    200 characters must be rejected with ValueError (not passed to the DB).
    """

    def _run_get_query_with_regex(self, pattern):
        from grapinator.schema import MyConnectionField
        from grapinator.model import db_Employees
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.order_by = MagicMock(return_value=mock_query)
        info = MagicMock()
        info.context = {'user_roles': [], 'authenticated': False}
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query), \
            patch('grapinator.schema.settings.GQL_ALLOW_REGEX', True):
            MyConnectionField.get_query(
                db_Employees, info,
                matches='regex',
                _allow_regex=True,
                first_name=pattern,
            )
        return mock_query

    def test_regex_remains_enabled_by_default(self):
        from grapinator.schema import MyConnectionField
        from grapinator.model import db_Employees
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        info = MagicMock()
        info.context = {'user_roles': []}
        with patch.object(
            MyConnectionField.__bases__[0], 'get_query', return_value=mock_query
        ):
            MyConnectionField.get_query(
                db_Employees, info, matches='regex', first_name='.*'
            )
        mock_query.filter.assert_called_once()

    def test_short_regex_accepted(self):
        """A regex pattern under 200 chars is passed through to the query."""
        mock_query = self._run_get_query_with_regex('Smith|Jones')
        mock_query.filter.assert_called_once()

    def test_exactly_200_chars_accepted(self):
        """A pattern exactly 200 characters long is accepted."""
        pattern = 'a' * 200
        mock_query = self._run_get_query_with_regex(pattern)
        mock_query.filter.assert_called_once()

    def test_201_chars_rejected(self):
        """A pattern 201 characters long raises ValueError."""
        pattern = 'a' * 201
        from grapinator.schema import MyConnectionField
        from grapinator.model import db_Employees
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        info = MagicMock()
        info.context = {'user_roles': [], 'authenticated': False}
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            with self.assertRaises(ValueError) as ctx:
                MyConnectionField.get_query(
                    db_Employees, info,
                    matches='regex',
                    _allow_regex=True,
                    first_name=pattern,
                )
        self.assertIn('200', str(ctx.exception))

    def test_catastrophic_backtrack_pattern_rejected(self):
        """A classic ReDoS pattern longer than 200 chars is rejected."""
        pattern = '(' + 'a+' * 101 + ')$'  # well over 200 chars
        from grapinator.schema import MyConnectionField
        from grapinator.model import db_Employees
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        info = MagicMock()
        info.context = {'user_roles': [], 'authenticated': False}
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            with self.assertRaises(ValueError):
                MyConnectionField.get_query(
                    db_Employees, info,
                    matches='regex',
                    _allow_regex=True,
                    first_name=pattern,
                )

    def test_re_alias_also_capped(self):
        """The 're' alias for regex is subject to the same length cap."""
        pattern = 'x' * 201
        from grapinator.schema import MyConnectionField
        from grapinator.model import db_Employees
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        info = MagicMock()
        info.context = {'user_roles': [], 'authenticated': False}
        with patch.object(MyConnectionField.__bases__[0], 'get_query', return_value=mock_query):
            with self.assertRaises(ValueError):
                MyConnectionField.get_query(
                    db_Employees, info,
                    matches='re',
                    _allow_regex=True,
                    first_name=pattern,
                )


# ---------------------------------------------------------------------------
# Fix 4: AUTH_DEV_SECRET default value startup guard (LOW)
# ---------------------------------------------------------------------------

import tempfile

# Minimal ini content for testing the AUTH_DEV_SECRET startup guard.
# Enough sections/keys for Settings to load without erroring on unrelated
# missing options.
_BASE_INI = """\
[GRAPHENE]
GQL_SCHEMA = {schema_path}

[AUTH]
AUTH_MODE = {auth_mode}
AUTH_DEV_SECRET = {dev_secret}

[WSGI]
WSGI_SOCKET_HOST = 127.0.0.1
WSGI_SOCKET_PORT = 8443

[CORS]
CORS_ENABLE = False
CORS_EXPOSE_ORIGINS = *
CORS_ALLOW_METHODS = GET, POST
CORS_HEADER_MAX_AGE = 1800
CORS_ALLOW_HEADERS = Origin, X-Requested-With, Content-Type, Accept
CORS_EXPOSE_HEADERS = Location
CORS_SEND_WILDCARD = True
CORS_SUPPORTS_CREDENTIALS = False

[HTTP_HEADERS]
HTTP_HEADERS_XFRAME = sameorigin
HTTP_HEADERS_XSS_PROTECTION = 1; mode=block
HTTP_HEADER_CACHE_CONTROL = no-cache
HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS = nosniff
HTTP_HEADERS_REFERRER_POLICY = strict-origin-when-cross-origin
HTTP_HEADERS_CONTENT_SECURITY_POLICY = default-src 'self'

[FLASK]
FLASK_SERVER_NAME = localhost:8443
FLASK_API_ENDPOINT = /gql
FLASK_DEBUG = False

[SQLALCHEMY]
DB_TYPE = sqlite+pysqlite
DB_CONNECT = /db/northwind.db
SQLALCHEMY_TRACK_MODIFICATIONS = False
"""

_DEFAULT_SECRET = 'change-me-local-dev-only'
_REAL_SCHEMA = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'grapinator', 'resources', 'schema.dct')
)
# Settings prepends its own module directory to config_file, so temp ini files
# must be written inside grapinator/resources/ and referenced as /resources/<name>.
_RESOURCES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'grapinator', 'resources')
)


def _write_ini(auth_mode, dev_secret):
    """Write a temporary ini file inside grapinator/resources/ and return its
    relative path (starting with /resources/) for use with Settings()."""
    content = _BASE_INI.format(
        schema_path=_REAL_SCHEMA,
        auth_mode=auth_mode,
        dev_secret=dev_secret,
    )
    f = tempfile.NamedTemporaryFile(
        mode='w', suffix='.ini', dir=_RESOURCES_DIR, delete=False
    )
    f.write(content)
    f.close()
    return '/resources/' + os.path.basename(f.name), f.name


class TestAuthDevSecretGuard(unittest.TestCase):
    """
    Regression tests for LOW: Settings raises RuntimeError when AUTH_DEV_SECRET
    equals the known default ('change-me-local-dev-only') and auth is active
    (AUTH_MODE != 'off' and no AUTH_JWKS_URI).
    """

    def _make_settings(self, auth_mode, dev_secret):
        from grapinator.settings import Settings
        rel_path, abs_path = _write_ini(auth_mode, dev_secret)
        try:
            return Settings(config_file=rel_path)
        finally:
            os.unlink(abs_path)

    def test_default_secret_with_required_mode_raises(self):
        """Default AUTH_DEV_SECRET + AUTH_MODE=required must raise RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            self._make_settings('required', _DEFAULT_SECRET)
        self.assertIn('AUTH_DEV_SECRET', str(ctx.exception))

    def test_default_secret_with_mixed_mode_raises(self):
        """Default AUTH_DEV_SECRET + AUTH_MODE=mixed must raise RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            self._make_settings('mixed', _DEFAULT_SECRET)
        self.assertIn('AUTH_DEV_SECRET', str(ctx.exception))

    def test_default_secret_with_auth_off_allowed(self):
        """Default AUTH_DEV_SECRET is allowed when AUTH_MODE=off (no-op config)."""
        # Should not raise — AUTH_MODE=off means auth is disabled
        settings = self._make_settings('off', _DEFAULT_SECRET)
        self.assertEqual(settings.AUTH_DEV_SECRET, _DEFAULT_SECRET)

    def test_changed_secret_with_required_mode_allowed(self):
        """A non-default AUTH_DEV_SECRET is accepted even with AUTH_MODE=required."""
        settings = self._make_settings('required', 'my-real-strong-secret-not-default')
        self.assertEqual(settings.AUTH_MODE, 'required')

    def test_changed_secret_with_mixed_mode_allowed(self):
        """A non-default AUTH_DEV_SECRET is accepted with AUTH_MODE=mixed."""
        settings = self._make_settings('mixed', 'another-real-secret-not-default')
        self.assertEqual(settings.AUTH_MODE, 'mixed')

    def test_error_message_mentions_default_remedy(self):
        """RuntimeError message includes guidance about changing the default."""
        with self.assertRaises(RuntimeError) as ctx:
            self._make_settings('required', _DEFAULT_SECRET)
        msg = str(ctx.exception)
        self.assertIn('AUTH_DEV_SECRET', msg)
        self.assertIn('default', msg)


# ---------------------------------------------------------------------------
# Fix 5: FLASK_DEBUG=True with auth enabled warning (LOW)
# ---------------------------------------------------------------------------

_BASE_INI_DEBUG = """\
[GRAPHENE]
GQL_SCHEMA = {schema_path}

[AUTH]
AUTH_MODE = {auth_mode}

[WSGI]
WSGI_SOCKET_HOST = 127.0.0.1
WSGI_SOCKET_PORT = 8443

[CORS]
CORS_ENABLE = False
CORS_EXPOSE_ORIGINS = *
CORS_ALLOW_METHODS = GET, POST
CORS_HEADER_MAX_AGE = 1800
CORS_ALLOW_HEADERS = Origin, X-Requested-With, Content-Type, Accept
CORS_EXPOSE_HEADERS = Location
CORS_SEND_WILDCARD = True
CORS_SUPPORTS_CREDENTIALS = False

[HTTP_HEADERS]
HTTP_HEADERS_XFRAME = sameorigin
HTTP_HEADERS_XSS_PROTECTION = 1; mode=block
HTTP_HEADER_CACHE_CONTROL = no-cache
HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS = nosniff
HTTP_HEADERS_REFERRER_POLICY = strict-origin-when-cross-origin
HTTP_HEADERS_CONTENT_SECURITY_POLICY = default-src 'self'

[FLASK]
FLASK_SERVER_NAME = localhost:8443
FLASK_API_ENDPOINT = /gql
FLASK_DEBUG = {flask_debug}

[SQLALCHEMY]
DB_TYPE = sqlite+pysqlite
DB_CONNECT = /db/northwind.db
SQLALCHEMY_TRACK_MODIFICATIONS = False
"""


def _write_ini_debug(auth_mode, flask_debug):
    """Write a temp ini file for FLASK_DEBUG tests; returns (rel_path, abs_path)."""
    content = _BASE_INI_DEBUG.format(
        schema_path=_REAL_SCHEMA,
        auth_mode=auth_mode,
        flask_debug=flask_debug,
    )
    f = tempfile.NamedTemporaryFile(
        mode='w', suffix='.ini', dir=_RESOURCES_DIR, delete=False
    )
    f.write(content)
    f.close()
    return '/resources/' + os.path.basename(f.name), f.name


class TestFlaskDebugWithAuthGuard(unittest.TestCase):
    """
    Regression tests for LOW: Settings must log a WARNING when FLASK_DEBUG=True
    is combined with AUTH_MODE != 'off'.
    """

    def _make_settings_debug(self, auth_mode, flask_debug):
        from grapinator.settings import Settings
        rel_path, abs_path = _write_ini_debug(auth_mode, flask_debug)
        try:
            return Settings(config_file=rel_path)
        finally:
            os.unlink(abs_path)

    def test_flask_debug_true_with_required_logs_warning(self):
        """FLASK_DEBUG=True + AUTH_MODE=required must produce a WARNING."""
        with self.assertLogs('grapinator.settings', level='WARNING') as cm:
            self._make_settings_debug('required', 'True')
        self.assertTrue(
            any('FLASK_DEBUG' in msg for msg in cm.output),
            'Expected FLASK_DEBUG warning in log output',
        )

    def test_flask_debug_true_with_mixed_logs_warning(self):
        """FLASK_DEBUG=True + AUTH_MODE=mixed must produce a WARNING."""
        with self.assertLogs('grapinator.settings', level='WARNING') as cm:
            self._make_settings_debug('mixed', 'True')
        self.assertTrue(
            any('FLASK_DEBUG' in msg for msg in cm.output),
        )

    def test_flask_debug_true_with_auth_off_no_warning(self):
        """FLASK_DEBUG=True with AUTH_MODE=off must NOT produce the FLASK_DEBUG warning."""
        import logging
        with self.assertLogs('grapinator.settings', level='DEBUG') as cm:
            # Emit a dummy log so assertLogs doesn't fail when nothing is logged
            logging.getLogger('grapinator.settings').debug('_sentinel_')
            self._make_settings_debug('off', 'True')
        flask_debug_warnings = [
            msg for msg in cm.output if 'FLASK_DEBUG' in msg and 'WARNING' in msg
        ]
        self.assertEqual(flask_debug_warnings, [],
                         'No FLASK_DEBUG warning expected when AUTH_MODE=off')

    def test_flask_debug_false_with_required_no_warning(self):
        """FLASK_DEBUG=False must never produce the FLASK_DEBUG warning."""
        import logging
        with self.assertLogs('grapinator.settings', level='DEBUG') as cm:
            logging.getLogger('grapinator.settings').debug('_sentinel_')
            self._make_settings_debug('required', 'False')
        flask_debug_warnings = [
            msg for msg in cm.output if 'FLASK_DEBUG' in msg and 'WARNING' in msg
        ]
        self.assertEqual(flask_debug_warnings, [])

    def test_warning_message_mentions_auth_mode(self):
        """The warning message must include the active AUTH_MODE value."""
        with self.assertLogs('grapinator.settings', level='WARNING') as cm:
            self._make_settings_debug('required', 'True')
        warning_msgs = [msg for msg in cm.output if 'FLASK_DEBUG' in msg]
        self.assertTrue(
            any('required' in msg for msg in warning_msgs),
            'Warning should mention the active AUTH_MODE value',
        )


if __name__ == '__main__':
    unittest.main()
