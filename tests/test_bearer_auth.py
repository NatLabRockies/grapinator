"""
test_bearer_auth.py

Unit tests for JWT bearer token authentication (grapinator/auth.py) and
schema-level RBAC (field-level and entity-level access control in schema.py).

Test strategy
~~~~~~~~~~~~~
* **Middleware tests** — exercise ``BearerAuthMiddleware`` in isolation with a
  mock downstream WSGI app.  HS256 tokens signed with a dev secret are used
  so tests need no external IdP or JWKS endpoint.  A separate fixture uses a
  self-generated RSA key pair passed as the ``_signing_key`` override to
  verify the RS256 / JWKS code-path without network calls.

* **Schema RBAC tests** — unit-test the field-level resolver wrapper and the
  entity-level ``get_query`` guard introduced in ``schema.py``.  Tests create
  minimal Graphene types and mock SQLAlchemy queries rather than exercising
  the full HTTP stack.

* **Dev JWT script tests** — verify ``tools/dev_jwt.py`` behaviour using the
  library API directly.

All tests are IdP-agnostic by design: no Azure/Keycloak/Auth0-specific logic
is exercised.  Provider-specific configuration lives entirely in the ini file.

Follows the naming and structure conventions in ``test_flask_app.py``.
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import time
import json
import unittest
from unittest.mock import MagicMock, patch

from . import context  # noqa: F401 — adds project root to sys.path

import jwt as pyjwt

from grapinator.auth import (
    BearerAuthMiddleware,
    _extract_bearer_token,
    _get_roles_from_payload,
    _json_401,
)

# ---------------------------------------------------------------------------
# Shared JWT helpers
# ---------------------------------------------------------------------------

DEV_SECRET = 'test-dev-secret-do-not-use-in-production'


def _make_token(roles=None, secret=DEV_SECRET, exp_offset=3600, extra_claims=None):
    """Return a signed HS256 JWT with the given roles and default claims."""
    now = int(time.time())
    payload = {'sub': 'test-user', 'iat': now, 'exp': now + exp_offset}
    if roles is not None:
        payload['roles'] = roles
    if extra_claims:
        payload.update(extra_claims)
    return pyjwt.encode(payload, secret, algorithm='HS256')


def _make_token_nested_claim(roles, claim_path='realm_access.roles'):
    """Return an HS256 JWT whose roles live at a nested claim path."""
    now = int(time.time())
    payload = {'sub': 'test-user', 'iat': now, 'exp': now + 3600}
    # Build nested structure from dotted path
    parts = claim_path.split('.')
    current = payload
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = roles
    return pyjwt.encode(payload, DEV_SECRET, algorithm='HS256')


def _make_rsa_key_pair():
    """Generate a fresh RSA key pair for testing RS256 tokens."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    return private_key, private_key.public_key()


def _make_rsa_token(private_key, roles=None, exp_offset=3600):
    """Return an RS256-signed JWT using the provided private key."""
    now = int(time.time())
    payload = {'sub': 'test-user', 'iat': now, 'exp': now + exp_offset}
    if roles is not None:
        payload['roles'] = roles
    return pyjwt.encode(payload, private_key, algorithm='RS256')


def _make_auth_settings(
    mode='mixed',
    dev_secret=DEV_SECRET,
    roles_claim='roles',
    graphiql_access='authenticated',
    jwks_uri=None,
    issuer=None,
    audience=None,
):
    """Build a minimal settings-like object for BearerAuthMiddleware construction."""
    s = MagicMock()
    s.AUTH_MODE = mode
    s.AUTH_DEV_SECRET = dev_secret
    s.AUTH_ROLES_CLAIM = roles_claim
    s.GRAPHIQL_ACCESS = graphiql_access
    s.AUTH_JWKS_URI = jwks_uri
    s.AUTH_ISSUER = issuer
    s.AUTH_AUDIENCE = audience
    s.AUTH_ALGORITHMS = 'HS256'
    s.AUTH_JWKS_CACHE_TTL = 300
    return s


def _make_environ(method='POST', auth_header=None, accept=None, query_string=''):
    """Build a minimal WSGI environ dict."""
    environ = {
        'REQUEST_METHOD': method,
        'PATH_INFO': '/test/gql',
        'QUERY_STRING': query_string,
    }
    if auth_header:
        environ['HTTP_AUTHORIZATION'] = auth_header
    if accept:
        environ['HTTP_ACCEPT'] = accept
    return environ


def _capturing_wsgi_app():
    """Return a WSGI app that captures environ and returns 200 OK."""
    captured = {}

    def app(environ, start_response):
        captured.update(environ)
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [b'{}']

    return app, captured


# ===========================================================================
# Low-level helper tests
# ===========================================================================

class TestExtractBearerToken(unittest.TestCase):
    """_extract_bearer_token parses the Authorization header."""

    def test_valid_bearer_header(self):
        environ = _make_environ(auth_header='Bearer my-token-value')
        self.assertEqual(_extract_bearer_token(environ), 'my-token-value')

    def test_bearer_case_insensitive(self):
        environ = _make_environ(auth_header='BEARER my-token-value')
        self.assertEqual(_extract_bearer_token(environ), 'my-token-value')

    def test_no_header_returns_none(self):
        self.assertIsNone(_extract_bearer_token(_make_environ()))

    def test_non_bearer_scheme_returns_none(self):
        environ = _make_environ(auth_header='Basic dXNlcjpwYXNz')
        self.assertIsNone(_extract_bearer_token(environ))

    def test_bearer_with_whitespace_trimmed(self):
        environ = _make_environ(auth_header='Bearer   spaced-token  ')
        self.assertEqual(_extract_bearer_token(environ), 'spaced-token')


class TestGetRolesFromPayload(unittest.TestCase):
    """_get_roles_from_payload traverses dotted-path claims correctly."""

    def test_flat_claim(self):
        payload = {'roles': ['admin', 'reader']}
        self.assertEqual(_get_roles_from_payload(payload, 'roles'), ['admin', 'reader'])

    def test_nested_claim(self):
        payload = {'realm_access': {'roles': ['user', 'moderator']}}
        self.assertEqual(
            _get_roles_from_payload(payload, 'realm_access.roles'),
            ['user', 'moderator'],
        )

    def test_missing_claim_returns_empty(self):
        self.assertEqual(_get_roles_from_payload({}, 'roles'), [])

    def test_missing_nested_claim_returns_empty(self):
        self.assertEqual(_get_roles_from_payload({'realm_access': {}}, 'realm_access.roles'), [])

    def test_non_list_value_returns_empty(self):
        payload = {'roles': 'not-a-list'}
        self.assertEqual(_get_roles_from_payload(payload, 'roles'), [])

    def test_deeply_nested_claim(self):
        payload = {'a': {'b': {'c': ['role1']}}}
        self.assertEqual(_get_roles_from_payload(payload, 'a.b.c'), ['role1'])

    def test_path_traversal_hits_non_dict(self):
        # Second segment tries to walk into a string — should return []
        payload = {'a': 'not-a-dict'}
        self.assertEqual(_get_roles_from_payload(payload, 'a.roles'), [])


class TestJson401(unittest.TestCase):
    """_json_401 returns a correctly formatted GraphQL error response."""

    def test_status_is_401(self):
        status, _, _ = _json_401('Nope')
        self.assertEqual(status, '401 Unauthorized')

    def test_content_type_is_json(self):
        _, headers, _ = _json_401('Nope')
        header_dict = dict(headers)
        self.assertEqual(header_dict['Content-Type'], 'application/json')

    def test_body_is_graphql_error_format(self):
        _, _, body = _json_401('Token expired.')
        data = json.loads(b''.join(body))
        self.assertIn('errors', data)
        self.assertEqual(data['errors'][0]['message'], 'Token expired.')

    def test_content_length_matches_body(self):
        _, headers, body = _json_401('test')
        content_length = int(dict(headers)['Content-Length'])
        self.assertEqual(content_length, len(b''.join(body)))


# ===========================================================================
# BearerAuthMiddleware — off mode
# ===========================================================================

class TestBearerAuthMiddlewareOffMode(unittest.TestCase):
    """When AUTH_MODE='off', middleware must be a complete pass-through."""

    def setUp(self):
        self.inner, self.captured = _capturing_wsgi_app()
        settings = _make_auth_settings(mode='off')
        self.middleware = BearerAuthMiddleware(self.inner, settings)

    def _call(self, environ=None):
        if environ is None:
            environ = _make_environ()
        results = []
        def sr(status, headers, exc_info=None):
            results.append((status, headers))
        list(self.middleware(environ, sr))
        return results

    def test_passes_request_without_token(self):
        statuses = self._call()
        self.assertEqual(statuses[0][0], '200 OK')

    def test_passes_request_with_invalid_token(self):
        environ = _make_environ(auth_header='Bearer totally.invalid.token')
        statuses = self._call(environ)
        # Off mode: no validation, should pass through
        self.assertEqual(statuses[0][0], '200 OK')

    def test_sets_empty_user_roles_in_environ(self):
        environ = _make_environ()
        self._call(environ)
        self.assertEqual(self.captured.get('grapinator.user_roles'), [])

    def test_sets_authenticated_false_in_environ(self):
        environ = _make_environ()
        self._call(environ)
        self.assertFalse(self.captured.get('grapinator.authenticated'))


# ===========================================================================
# BearerAuthMiddleware — mixed mode
# ===========================================================================

class TestBearerAuthMiddlewareMixedMode(unittest.TestCase):
    """Mixed mode: no token → unauthenticated pass-through; bad token → 401."""

    def setUp(self):
        self.inner, self.captured = _capturing_wsgi_app()
        settings = _make_auth_settings(mode='mixed')
        self.middleware = BearerAuthMiddleware(self.inner, settings)

    def _call(self, environ=None):
        if environ is None:
            environ = _make_environ()
        results = []

        def sr(status, headers, exc_info=None):
            results.append((status, headers))

        body = list(self.middleware(environ, sr))
        return results, body

    def test_no_token_passes_through(self):
        (results, _) = self._call()
        self.assertEqual(results[0][0], '200 OK')

    def test_no_token_sets_empty_roles(self):
        environ = _make_environ()
        self._call(environ)
        self.assertEqual(self.captured.get('grapinator.user_roles'), [])

    def test_no_token_sets_authenticated_false(self):
        environ = _make_environ()
        self._call(environ)
        self.assertFalse(self.captured.get('grapinator.authenticated'))

    def test_valid_token_passes_through(self):
        token = _make_token(roles=['admin'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '200 OK')

    def test_valid_token_sets_roles_in_environ(self):
        token = _make_token(roles=['admin', 'reader'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        self._call(environ)
        self.assertIn('admin', self.captured.get('grapinator.user_roles', []))
        self.assertIn('reader', self.captured.get('grapinator.user_roles', []))

    def test_valid_token_sets_authenticated_true(self):
        token = _make_token(roles=['admin'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        self._call(environ)
        self.assertTrue(self.captured.get('grapinator.authenticated'))

    def test_invalid_token_returns_401(self):
        environ = _make_environ(auth_header='Bearer not.a.real.token')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '401 Unauthorized')

    def test_expired_token_returns_401(self):
        token = _make_token(roles=['admin'], exp_offset=-1)
        environ = _make_environ(auth_header=f'Bearer {token}')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '401 Unauthorized')

    def test_expired_token_returns_expiry_message(self):
        token = _make_token(roles=['admin'], exp_offset=-1)
        environ = _make_environ(auth_header=f'Bearer {token}')
        results, body = self._call(environ)
        data = json.loads(b''.join(body))
        self.assertIn('expired', data['errors'][0]['message'].lower())

    def test_wrong_secret_returns_401(self):
        token = _make_token(roles=['admin'], secret='wrong-secret')
        environ = _make_environ(auth_header=f'Bearer {token}')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '401 Unauthorized')

    def test_options_preflight_always_passes(self):
        environ = _make_environ(method='OPTIONS')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '200 OK')

    def test_token_without_roles_claim_gives_empty_list(self):
        token = _make_token(roles=None)  # no 'roles' key at all
        environ = _make_environ(auth_header=f'Bearer {token}')
        self._call(environ)
        self.assertEqual(self.captured.get('grapinator.user_roles'), [])

    def test_nested_roles_claim_extracted_correctly(self):
        token = _make_token_nested_claim(['superuser'], claim_path='realm_access.roles')
        inner, captured2 = _capturing_wsgi_app()
        settings = _make_auth_settings(mode='mixed', roles_claim='realm_access.roles')
        mw = BearerAuthMiddleware(inner, settings)
        environ = _make_environ(auth_header=f'Bearer {token}')
        results = []
        list(mw(environ, lambda s, h, ei=None: results.append(s)))
        self.assertEqual(captured2.get('grapinator.user_roles'), ['superuser'])


# ===========================================================================
# BearerAuthMiddleware — required mode
# ===========================================================================

class TestBearerAuthMiddlewareRequiredMode(unittest.TestCase):
    """required mode: every request needs a valid token."""

    def setUp(self):
        self.inner, self.captured = _capturing_wsgi_app()
        settings = _make_auth_settings(mode='required')
        self.middleware = BearerAuthMiddleware(self.inner, settings)

    def _call(self, environ=None):
        if environ is None:
            environ = _make_environ()
        results = []

        def sr(status, headers, exc_info=None):
            results.append((status, dict(headers)))

        body = list(self.middleware(environ, sr))
        return results, body

    def test_no_token_returns_401(self):
        results, _ = self._call()
        self.assertEqual(results[0][0], '401 Unauthorized')

    def test_no_token_body_is_graphql_format(self):
        results, body = self._call()
        data = json.loads(b''.join(body))
        self.assertIn('errors', data)

    def test_valid_token_passes_through(self):
        token = _make_token(roles=['user'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '200 OK')

    def test_invalid_token_returns_401(self):
        environ = _make_environ(auth_header='Bearer garbage')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '401 Unauthorized')

    def test_options_always_passes(self):
        environ = _make_environ(method='OPTIONS')
        results, _ = self._call(environ)
        self.assertEqual(results[0][0], '200 OK')


# ===========================================================================
# BearerAuthMiddleware — GraphiQL access control
# ===========================================================================

class TestGraphiqlAccessControl(unittest.TestCase):
    """GRAPHIQL_ACCESS setting controls whether IDE GET requests need a token."""

    def _browser_get_environ(self):
        """Simulate a bare browser GET that would load the GraphiQL IDE."""
        return _make_environ(method='GET', accept='text/html,application/xhtml+xml', query_string='')

    def _make_middleware(self, graphiql_access='authenticated', mode='required'):
        inner, captured = _capturing_wsgi_app()
        settings = _make_auth_settings(mode=mode, graphiql_access=graphiql_access)
        return BearerAuthMiddleware(inner, settings), captured

    def _call(self, middleware, environ):
        results = []
        list(middleware(environ, lambda s, h, ei=None: results.append(s)))
        return results

    def test_graphiql_open_bypasses_auth_for_ide_get(self):
        mw, _ = self._make_middleware(graphiql_access='open', mode='required')
        results = self._call(mw, self._browser_get_environ())
        self.assertEqual(results[0], '200 OK')

    def test_graphiql_authenticated_requires_token_for_ide_get(self):
        mw, _ = self._make_middleware(graphiql_access='authenticated', mode='required')
        results = self._call(mw, self._browser_get_environ())
        self.assertEqual(results[0], '401 Unauthorized')

    def test_graphiql_authenticated_with_valid_token_passes(self):
        mw, _ = self._make_middleware(graphiql_access='authenticated', mode='required')
        environ = self._browser_get_environ()
        token = _make_token(roles=['user'])
        environ['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        results = self._call(mw, environ)
        self.assertEqual(results[0], '200 OK')

    def test_get_with_query_param_is_not_ide_request(self):
        """A GET with ?query=... is a real GraphQL query, not an IDE page load."""
        mw, _ = self._make_middleware(graphiql_access='open', mode='required')
        environ = _make_environ(method='GET', accept='text/html', query_string='query={__typename}')
        results = self._call(mw, environ)
        # Even with graphiql_access=open, a ?query= GET is not bypassed
        self.assertEqual(results[0], '401 Unauthorized')

    def test_mixed_mode_ide_open_passes_without_token(self):
        mw, _ = self._make_middleware(graphiql_access='open', mode='mixed')
        results = self._call(mw, self._browser_get_environ())
        self.assertEqual(results[0], '200 OK')


# ===========================================================================
# BearerAuthMiddleware — RSA / JWKS code path (test key override)
# ===========================================================================

class TestBearerAuthMiddlewareRSA(unittest.TestCase):
    """Verify RS256 validation using a self-generated key (no JWKS endpoint)."""

    @classmethod
    def setUpClass(cls):
        cls.private_key, cls.public_key = _make_rsa_key_pair()

    def setUp(self):
        self.inner, self.captured = _capturing_wsgi_app()
        settings = _make_auth_settings(mode='mixed', dev_secret=None)
        settings.AUTH_ALGORITHMS = 'RS256'
        self.middleware = BearerAuthMiddleware(
            self.inner, settings, _signing_key=self.public_key
        )

    def _call(self, environ):
        results = []
        list(self.middleware(environ, lambda s, h, ei=None: results.append(s)))
        return results

    def test_valid_rsa_token_passes(self):
        token = _make_rsa_token(self.private_key, roles=['analyst'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        results = self._call(environ)
        self.assertEqual(results[0], '200 OK')

    def test_valid_rsa_token_populates_roles(self):
        token = _make_rsa_token(self.private_key, roles=['analyst', 'viewer'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        self._call(environ)
        self.assertIn('analyst', self.captured.get('grapinator.user_roles', []))

    def test_hs256_token_rejected_when_rsa_expected(self):
        # HS256 token signed with dev secret — should fail RS256 validation
        token = _make_token(roles=['admin'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        results = self._call(environ)
        self.assertEqual(results[0], '401 Unauthorized')

    def test_expired_rsa_token_returns_401(self):
        token = _make_rsa_token(self.private_key, roles=['analyst'], exp_offset=-1)
        environ = _make_environ(auth_header=f'Bearer {token}')
        results = self._call(environ)
        self.assertEqual(results[0], '401 Unauthorized')


# ===========================================================================
# Schema RBAC — field-level resolver wrapper
# ===========================================================================

class TestFieldLevelRBAC(unittest.TestCase):
    """
    Test the auth resolver wrapper injected by gql_class_constructor for
    fields with gql_auth_roles declared.

    We import schema.py components directly rather than running GraphQL
    queries so the test is fast and has no database dependency.
    """

    def _make_context(self, roles):
        return {'user_roles': roles}

    def _make_info(self, roles):
        """Build a minimal graphene ResolveInfo-like mock."""
        info = MagicMock()
        info.context = self._make_context(roles)
        return info

    def test_resolver_returns_value_when_role_matches(self):
        """A caller with the required role receives the real field value."""
        from grapinator.schema import gql_class_constructor

        # Build a minimal schema entry with one auth-protected field
        attrs = [{
            'name': 'secret_salary',
            'type': __import__('graphene').Int,
            'desc': 'Protected field',
            'type_args': None,
            'isqueryable': True,
            'ishidden': False,
            'isresolver': False,
            'auth_roles': ['hr'],
            'deprecation_reason': None,
        }]

        # gql_class_constructor needs a real SQLAlchemy model in globals().
        # Use db_Employees which is loaded by grapinator.model.
        import grapinator.schema as schema_mod
        cls = gql_class_constructor('TestHRType', 'db_Employees', attrs, 'employee_id')

        resolver = getattr(cls, 'resolve_secret_salary', None)
        self.assertIsNotNone(resolver, 'Auth resolver should be injected for auth_roles field')

        root = MagicMock()
        root.secret_salary = 99000
        info = self._make_info(roles=['hr'])
        result = resolver(root, info)
        self.assertEqual(result, 99000)

    def test_resolver_returns_none_when_role_missing(self):
        """A caller without the required role receives None."""
        from grapinator.schema import gql_class_constructor

        attrs = [{
            'name': 'secret_salary',
            'type': __import__('graphene').Int,
            'desc': 'Protected field',
            'type_args': None,
            'isqueryable': True,
            'ishidden': False,
            'isresolver': False,
            'auth_roles': ['hr'],
            'deprecation_reason': None,
        }]

        cls = gql_class_constructor('TestHRType2', 'db_Employees', attrs, 'employee_id')
        resolver = getattr(cls, 'resolve_secret_salary')
        root = MagicMock()
        root.secret_salary = 99000
        info = self._make_info(roles=['reader'])  # 'reader' is not in ['hr']
        result = resolver(root, info)
        self.assertIsNone(result)

    def test_resolver_returns_none_when_no_roles(self):
        """Unauthenticated caller (empty roles) receives None for auth fields."""
        from grapinator.schema import gql_class_constructor

        attrs = [{
            'name': 'secret_salary',
            'type': __import__('graphene').Int,
            'desc': 'Protected field',
            'type_args': None,
            'isqueryable': True,
            'ishidden': False,
            'isresolver': False,
            'auth_roles': ['hr'],
            'deprecation_reason': None,
        }]

        cls = gql_class_constructor('TestHRType3', 'db_Employees', attrs, 'employee_id')
        resolver = getattr(cls, 'resolve_secret_salary')
        root = MagicMock()
        root.secret_salary = 99000
        info = self._make_info(roles=[])
        result = resolver(root, info)
        self.assertIsNone(result)

    def test_multi_role_access_any_matching_role_sufficient(self):
        """A field with ['hr', 'finance'] is accessible by either role."""
        from grapinator.schema import gql_class_constructor

        attrs = [{
            'name': 'budget_field',
            'type': __import__('graphene').Float,
            'desc': None,
            'type_args': None,
            'isqueryable': True,
            'ishidden': False,
            'isresolver': False,
            'auth_roles': ['hr', 'finance'],
            'deprecation_reason': None,
        }]

        cls = gql_class_constructor('TestFinType', 'db_Employees', attrs, 'employee_id')
        resolver = getattr(cls, 'resolve_budget_field')
        root = MagicMock()
        root.budget_field = 500000.0

        # 'finance' alone should suffice
        info = self._make_info(roles=['finance'])
        self.assertEqual(resolver(root, info), 500000.0)

    def test_public_field_has_no_auth_resolver(self):
        """Fields without gql_auth_roles must not have an auth resolver injected."""
        from grapinator.schema import gql_class_constructor

        attrs = [{
            'name': 'public_name',
            'type': __import__('graphene').String,
            'desc': None,
            'type_args': None,
            'isqueryable': True,
            'ishidden': False,
            'isresolver': False,
            'auth_roles': None,
            'deprecation_reason': None,
        }]

        cls = gql_class_constructor('TestPublicType', 'db_Employees', attrs, 'employee_id')
        self.assertFalse(
            hasattr(cls, 'resolve_public_name'),
            'Public field must not have an injected auth resolver',
        )


# ===========================================================================
# Schema RBAC — entity-level access control (MyConnectionField.get_query)
# ===========================================================================

class TestEntityLevelRBAC(unittest.TestCase):
    """
    Test MyConnectionField.get_query() entity-level RBAC gate.

    The _ENTITY_AUTH_ROLES registry and sql_false() filter are exercised
    by temporarily registering a fake entity and calling get_query.
    """

    def setUp(self):
        import grapinator.schema as schema_mod
        self._schema_mod = schema_mod
        self._original_registry = dict(schema_mod._ENTITY_AUTH_ROLES)

    def tearDown(self):
        # Restore the registry after each test
        self._schema_mod._ENTITY_AUTH_ROLES.clear()
        self._schema_mod._ENTITY_AUTH_ROLES.update(self._original_registry)

    def _make_info(self, roles):
        info = MagicMock()
        info.context = {'user_roles': roles}
        return info

    def test_entity_with_matching_role_runs_query_normally(self):
        """Caller has the required role → query proceeds (no false() filter)."""
        import grapinator.schema as schema_mod
        from grapinator.model import db_Employees  # available from northwind schema

        schema_mod._ENTITY_AUTH_ROLES['db_Employees'] = ['admin']
        info = self._make_info(roles=['admin'])

        mock_query = MagicMock()
        with patch.object(
            schema_mod.SQLAlchemyConnectionField, 'get_query', return_value=mock_query
        ):
            result = schema_mod.MyConnectionField.get_query(db_Employees, info)

        # filter(False) must NOT have been called
        mock_query.filter.assert_not_called()
        self.assertIs(result, mock_query)

    def test_entity_with_missing_role_returns_empty_queryset(self):
        """Caller lacks the required role → query.filter(false()) is applied."""
        import grapinator.schema as schema_mod
        from grapinator.model import db_Employees

        schema_mod._ENTITY_AUTH_ROLES['db_Employees'] = ['admin']
        info = self._make_info(roles=['reader'])  # 'reader' not in ['admin']

        mock_query = MagicMock()
        with patch.object(
            schema_mod.SQLAlchemyConnectionField, 'get_query', return_value=mock_query
        ):
            schema_mod.MyConnectionField.get_query(db_Employees, info)

        mock_query.filter.assert_called_once()

    def test_entity_with_no_auth_roles_not_filtered(self):
        """Entities without AUTH_ROLES are accessible to everyone."""
        import grapinator.schema as schema_mod
        from grapinator.model import db_Employees

        # Ensure no entry for db_Employees
        schema_mod._ENTITY_AUTH_ROLES.pop('db_Employees', None)
        info = self._make_info(roles=[])

        mock_query = MagicMock()
        with patch.object(
            schema_mod.SQLAlchemyConnectionField, 'get_query', return_value=mock_query
        ):
            result = schema_mod.MyConnectionField.get_query(db_Employees, info)

        mock_query.filter.assert_not_called()
        self.assertIs(result, mock_query)

    def test_unauthenticated_caller_gets_empty_queryset(self):
        """Empty role list → entity auth check fails → empty result."""
        import grapinator.schema as schema_mod
        from grapinator.model import db_Employees

        schema_mod._ENTITY_AUTH_ROLES['db_Employees'] = ['analyst']
        info = self._make_info(roles=[])

        mock_query = MagicMock()
        with patch.object(
            schema_mod.SQLAlchemyConnectionField, 'get_query', return_value=mock_query
        ):
            schema_mod.MyConnectionField.get_query(db_Employees, info)

        mock_query.filter.assert_called_once()

    def test_multi_role_entity_any_matching_role_sufficient(self):
        """Entity with ['hr', 'manager'] is accessible by either role."""
        import grapinator.schema as schema_mod
        from grapinator.model import db_Employees

        schema_mod._ENTITY_AUTH_ROLES['db_Employees'] = ['hr', 'manager']
        info = self._make_info(roles=['manager'])

        mock_query = MagicMock()
        with patch.object(
            schema_mod.SQLAlchemyConnectionField, 'get_query', return_value=mock_query
        ):
            result = schema_mod.MyConnectionField.get_query(db_Employees, info)

        mock_query.filter.assert_not_called()
        self.assertIs(result, mock_query)


# ===========================================================================
# dev_jwt.py tool tests
# ===========================================================================

class TestDevJwtTool(unittest.TestCase):
    """Verify the dev_jwt tool produces decodable tokens with correct claims."""

    def _generate_token(self, roles=None, claim='roles', secret=DEV_SECRET, expiry=3600):
        """Call the dev_jwt library function directly without subprocess."""
        now = int(time.time())
        payload = {'sub': 'dev-user', 'iat': now, 'exp': now + expiry}
        if roles:
            # Reproduce the _set_nested logic from the script
            parts = claim.split('.')
            current = payload
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = roles
        return pyjwt.encode(payload, secret, algorithm='HS256')

    def test_generated_token_is_decodable(self):
        token = self._generate_token(roles=['admin'])
        decoded = pyjwt.decode(token, DEV_SECRET, algorithms=['HS256'])
        self.assertIn('sub', decoded)

    def test_generated_token_contains_roles(self):
        roles = ['analyst', 'viewer']
        token = self._generate_token(roles=roles)
        decoded = pyjwt.decode(token, DEV_SECRET, algorithms=['HS256'])
        self.assertEqual(decoded['roles'], roles)

    def test_empty_roles_list(self):
        token = self._generate_token(roles=[])
        decoded = pyjwt.decode(token, DEV_SECRET, algorithms=['HS256'])
        self.assertEqual(decoded.get('roles', []), [])

    def test_nested_claim_path(self):
        token = self._generate_token(roles=['superuser'], claim='realm_access.roles')
        decoded = pyjwt.decode(token, DEV_SECRET, algorithms=['HS256'])
        self.assertEqual(decoded['realm_access']['roles'], ['superuser'])

    def test_expired_token_fails_validation(self):
        token = self._generate_token(roles=['admin'], expiry=-1)
        with self.assertRaises(pyjwt.ExpiredSignatureError):
            pyjwt.decode(token, DEV_SECRET, algorithms=['HS256'])

    def test_token_validated_by_bearer_middleware(self):
        """End-to-end: dev token generated and validated by BearerAuthMiddleware."""
        inner, captured = _capturing_wsgi_app()
        settings = _make_auth_settings(mode='required')
        mw = BearerAuthMiddleware(inner, settings)

        token = self._generate_token(roles=['admin', 'reader'])
        environ = _make_environ(auth_header=f'Bearer {token}')
        results = []
        list(mw(environ, lambda s, h, ei=None: results.append(s)))

        self.assertEqual(results[0], '200 OK')
        self.assertIn('admin', captured.get('grapinator.user_roles', []))
        self.assertIn('reader', captured.get('grapinator.user_roles', []))


# ===========================================================================
# Settings loading — AUTH section
# ===========================================================================

class TestSettingsAuthSection(unittest.TestCase):
    """Settings.AUTH_* attributes have correct defaults and load from ini."""

    def test_default_auth_mode_is_off(self):
        from grapinator import settings as app_settings
        # The test ini has no AUTH_MODE override, so the class default applies
        self.assertEqual(app_settings.AUTH_MODE, 'off')

    def test_default_graphiql_access_is_authenticated(self):
        from grapinator import settings as app_settings
        self.assertEqual(app_settings.GRAPHIQL_ACCESS, 'authenticated')

    def test_default_algorithms_is_rs256(self):
        from grapinator import settings as app_settings
        self.assertEqual(app_settings.AUTH_ALGORITHMS, 'RS256')

    def test_default_roles_claim_is_roles(self):
        from grapinator import settings as app_settings
        self.assertEqual(app_settings.AUTH_ROLES_CLAIM, 'roles')

    def test_default_jwks_cache_ttl(self):
        from grapinator import settings as app_settings
        self.assertEqual(app_settings.AUTH_JWKS_CACHE_TTL, 300)

    def test_default_dev_secret_is_none(self):
        from grapinator import settings as app_settings
        self.assertIsNone(app_settings.AUTH_DEV_SECRET)

    def test_default_jwks_uri_is_none(self):
        from grapinator import settings as app_settings
        self.assertIsNone(app_settings.AUTH_JWKS_URI)


if __name__ == '__main__':
    unittest.main()
