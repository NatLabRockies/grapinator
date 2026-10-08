"""Unit tests for Flask app behaviour (grapinator/app.py).

Covers:
  - SecurityHeadersMiddleware : security response headers (middleware.py)
  - FixedGraphQLView          : bug-fixes for render_graphql_ide / graphql_ide_html
      Bug 1 — None rendered as JSON null (not Python 'None' string)
      Bug 2 — operation_name passed with snake_case key so the template
              {{operation_name}} is populated correctly
      Bug 5 — json.dumps values must not be HTML-escaped by Jinja2
              (would turn \" into &#34;, breaking JavaScript on page reload)
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import json
import html
import base64
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from . import context  # noqa: F401

from graphql_server.flask.views import GraphQLView
from graphql import ExecutionResult, GraphQLError, validate_schema
from grapinator.app import app, FixedGraphQLView
from grapinator.schema import ClientError
from grapinator.middleware import SecurityHeadersMiddleware, CorsMiddleware
from grapinator import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status=200, body='ok'):
    with app.test_request_context('/'):
        from flask import make_response
        return make_response(body, status)


class TestSecurityHeadersMiddleware(unittest.TestCase):
    """SecurityHeadersMiddleware must inject all required security headers
    and strip the Server header on every response."""

    def setUp(self):
        """Run a real request through the middleware and capture headers."""
        self.captured_headers = {}

        def fake_app(environ, start_response):
            start_response('200 OK', [('Content-Type', 'text/plain'),
                                      ('Server', 'Werkzeug/3.0')])
            return [b'ok']

        middleware = SecurityHeadersMiddleware(fake_app)

        def capturing_start_response(status, headers, exc_info=None):
            self.captured_headers = dict(headers)

        environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'}
        list(middleware(environ, capturing_start_response))

    def test_x_frame_options_header_present(self):
        self.assertIn('X-Frame-Options', self.captured_headers)

    def test_x_frame_options_value_matches_settings(self):
        self.assertEqual(
            self.captured_headers['X-Frame-Options'],
            settings.HTTP_HEADERS_XFRAME,
        )

    def test_xss_protection_header_present(self):
        self.assertIn('X-XSS-Protection', self.captured_headers)

    def test_xss_protection_value_matches_settings(self):
        self.assertEqual(
            self.captured_headers['X-XSS-Protection'],
            settings.HTTP_HEADERS_XSS_PROTECTION,
        )

    def test_cache_control_header_present(self):
        self.assertIn('Cache-Control', self.captured_headers)

    def test_cache_control_value_matches_settings(self):
        self.assertEqual(
            self.captured_headers['Cache-Control'],
            settings.HTTP_HEADER_CACHE_CONTROL,
        )

    def test_server_header_stripped(self):
        self.assertNotIn('Server', self.captured_headers)


# ---------------------------------------------------------------------------
# CorsMiddleware — helpers
# ---------------------------------------------------------------------------

def _cors_run(method='GET', path='/', fake_app=None, **setting_overrides):
    """Create CorsMiddleware and run one request, both inside any setting
    overrides so init-time and call-time settings are consistently patched."""
    if fake_app is None:
        def fake_app(environ, start_response):
            start_response('200 OK', [('Content-Type', 'text/plain')])
            return [b'ok']

    captured = {}

    def capturing_start_response(status, headers, exc_info=None):
        captured['status'] = status
        captured['headers'] = dict(headers)

    environ = {'REQUEST_METHOD': method, 'PATH_INFO': path}

    if setting_overrides:
        with patch.multiple(settings, **setting_overrides):
            middleware = CorsMiddleware(fake_app)
            captured['body'] = b''.join(middleware(environ, capturing_start_response))
    else:
        middleware = CorsMiddleware(fake_app)
        captured['body'] = b''.join(middleware(environ, capturing_start_response))

    return captured


# ---------------------------------------------------------------------------
# CorsMiddleware — normal (non-preflight) requests
# ---------------------------------------------------------------------------

class TestCorsMiddlewareNormalRequest(unittest.TestCase):
    """CORS headers must be present on every non-OPTIONS response."""

    @classmethod
    def setUpClass(cls):
        cls.result = _cors_run()
        cls.headers = cls.result['headers']

    def test_allow_origin_header_present(self):
        self.assertIn('Access-Control-Allow-Origin', self.headers)

    def test_allow_methods_header_present(self):
        self.assertIn('Access-Control-Allow-Methods', self.headers)

    def test_allow_methods_value_matches_settings(self):
        self.assertEqual(self.headers['Access-Control-Allow-Methods'],
                         settings.CORS_ALLOW_METHODS)

    def test_allow_headers_header_present(self):
        self.assertIn('Access-Control-Allow-Headers', self.headers)

    def test_allow_headers_value_matches_settings(self):
        self.assertEqual(self.headers['Access-Control-Allow-Headers'],
                         settings.CORS_ALLOW_HEADERS)

    def test_expose_headers_header_present(self):
        self.assertIn('Access-Control-Expose-Headers', self.headers)

    def test_expose_headers_value_matches_settings(self):
        self.assertEqual(self.headers['Access-Control-Expose-Headers'],
                         settings.CORS_EXPOSE_HEADERS)

    def test_max_age_header_present(self):
        self.assertIn('Access-Control-Max-Age', self.headers)

    def test_max_age_value_matches_settings(self):
        self.assertEqual(self.headers['Access-Control-Max-Age'],
                         str(settings.CORS_HEADER_MAX_AGE))

    def test_response_body_is_preserved(self):
        self.assertEqual(self.result['body'], b'ok')

    def test_response_status_is_preserved(self):
        self.assertEqual(self.result['status'], '200 OK')


# ---------------------------------------------------------------------------
# CorsMiddleware — wildcard vs specific origin
# ---------------------------------------------------------------------------

class TestCorsMiddlewareOrigin(unittest.TestCase):
    """Access-Control-Allow-Origin must reflect CORS_SEND_WILDCARD."""

    def test_wildcard_when_send_wildcard_true(self):
        headers = _cors_run(CORS_SEND_WILDCARD=True,
                            CORS_EXPOSE_ORIGINS='https://example.com')['headers']
        self.assertEqual(headers['Access-Control-Allow-Origin'], '*')

    def test_specific_origin_when_send_wildcard_false(self):
        headers = _cors_run(CORS_SEND_WILDCARD=False,
                            CORS_EXPOSE_ORIGINS='https://example.com')['headers']
        self.assertEqual(headers['Access-Control-Allow-Origin'],
                         'https://example.com')


# ---------------------------------------------------------------------------
# CorsMiddleware — credentials
# ---------------------------------------------------------------------------

class TestCorsMiddlewareCredentials(unittest.TestCase):
    """Access-Control-Allow-Credentials must only appear when enabled."""

    def test_credentials_header_present_when_enabled(self):
        headers = _cors_run(CORS_SUPPORTS_CREDENTIALS=True)['headers']
        self.assertIn('Access-Control-Allow-Credentials', headers)
        self.assertEqual(headers['Access-Control-Allow-Credentials'], 'true')

    def test_credentials_header_absent_when_disabled(self):
        headers = _cors_run(CORS_SUPPORTS_CREDENTIALS=False)['headers']
        self.assertNotIn('Access-Control-Allow-Credentials', headers)


# ---------------------------------------------------------------------------
# CorsMiddleware — CORS_ENABLE = False
# ---------------------------------------------------------------------------

class TestCorsMiddlewareDisabled(unittest.TestCase):
    """When CORS_ENABLE is False the middleware must be transparent."""

    @classmethod
    def setUpClass(cls):
        cls.headers = _cors_run(CORS_ENABLE=False)['headers']

    def test_allow_origin_absent(self):
        self.assertNotIn('Access-Control-Allow-Origin', self.headers)

    def test_allow_methods_absent(self):
        self.assertNotIn('Access-Control-Allow-Methods', self.headers)

    def test_allow_headers_absent(self):
        self.assertNotIn('Access-Control-Allow-Headers', self.headers)

    def test_underlying_content_type_still_present(self):
        self.assertIn('Content-Type', self.headers)


# ---------------------------------------------------------------------------
# CorsMiddleware — OPTIONS preflight
# ---------------------------------------------------------------------------

class TestCorsMiddlewarePreflight(unittest.TestCase):
    """OPTIONS preflight must return 200 with CORS headers and an empty body."""

    @classmethod
    def setUpClass(cls):
        cls.result = _cors_run(method='OPTIONS')
        cls.headers = cls.result['headers']

    def test_status_is_200(self):
        self.assertEqual(self.result['status'], '200 OK')

    def test_body_is_empty(self):
        self.assertEqual(self.result['body'], b'')

    def test_allow_origin_present(self):
        self.assertIn('Access-Control-Allow-Origin', self.headers)

    def test_allow_methods_present(self):
        self.assertIn('Access-Control-Allow-Methods', self.headers)

    def test_allow_headers_present(self):
        self.assertIn('Access-Control-Allow-Headers', self.headers)

    def test_max_age_present(self):
        self.assertIn('Access-Control-Max-Age', self.headers)

    def test_allow_methods_value(self):
        self.assertEqual(self.headers['Access-Control-Allow-Methods'],
                         settings.CORS_ALLOW_METHODS)

    def test_allow_headers_value(self):
        self.assertEqual(self.headers['Access-Control-Allow-Headers'],
                         settings.CORS_ALLOW_HEADERS)

    def test_preflight_disabled_when_cors_off(self):
        """With CORS_ENABLE=False, OPTIONS must pass through to the app."""
        app_called = []

        def fake_app(environ, start_response):
            app_called.append(True)
            start_response('405 Method Not Allowed', [])
            return [b'']

        result = _cors_run(method='OPTIONS', fake_app=fake_app, CORS_ENABLE=False)
        self.assertTrue(app_called,
                        'Underlying app should be called when CORS is disabled')
        self.assertEqual(result['status'], '405 Method Not Allowed')


# ---------------------------------------------------------------------------
# FixedGraphQLView — Bug 1: None → JSON null (not Python 'None')
# ---------------------------------------------------------------------------

class TestFixedGraphQLViewNullRendering(unittest.TestCase):
    """Bug 1 fix: Python None in request_data must be serialised via
    json.dumps() so the Jinja template receives the JS literal null,
    not the Python string 'None'.
    """

    def _render(self, query=None, variables=None, operation_name=None,
                template='{{ query }}|{{ variables }}|{{ operation_name }}'):
        request_data = MagicMock()
        request_data.query          = query
        request_data.variables      = variables
        request_data.operation_name = operation_name

        with patch.object(GraphQLView, 'graphql_ide_html',
                          new_callable=PropertyMock, return_value=template):
            view = object.__new__(FixedGraphQLView)
            with app.test_request_context('/'):
                result = view.render_graphql_ide(MagicMock(), request_data)
        # render_template_string returns a str (not a Response)
        return result if isinstance(result, str) else result.get_data(as_text=True)

    def test_none_query_renders_as_json_null(self):
        content = self._render(query=None)
        # json.dumps(None) == 'null'
        self.assertIn('null', content)
        self.assertNotIn('None', content)

    def test_none_variables_renders_as_json_null(self):
        content = self._render(variables=None)
        self.assertIn('null', content)
        self.assertNotIn('None', content)

    def test_none_operation_name_renders_as_json_null(self):
        content = self._render(operation_name=None)
        self.assertIn('null', content)
        self.assertNotIn('None', content)

    def test_all_none_renders_three_nulls(self):
        content = self._render()
        self.assertEqual(content, 'null|null|null')

    def test_string_query_is_json_encoded(self):
        content = self._render(query='{ employees { name } }',
                               template='{{ query }}')
        # Markup prevents auto-escaping, so content has raw quotes
        self.assertEqual(content, json.dumps('{ employees { name } }'))

    def test_dict_variables_is_json_encoded(self):
        variables = {'first': 10}
        content = self._render(variables=variables, template='{{ variables }}')
        self.assertEqual(json.loads(content), variables)


# ---------------------------------------------------------------------------
# FixedGraphQLView — Bug 2: snake_case key for operation_name
# ---------------------------------------------------------------------------

class TestFixedGraphQLViewOperationNameKey(unittest.TestCase):
    """Bug 2 fix: the template uses {{ operation_name }} (snake_case).
    FixedGraphQLView must pass the kwarg as operation_name=, not operationName=.
    """

    def _render_op_name(self, operation_name):
        request_data = MagicMock()
        request_data.query          = None
        request_data.variables      = None
        request_data.operation_name = operation_name

        with patch.object(GraphQLView, 'graphql_ide_html',
                          new_callable=PropertyMock,
                          return_value='{{ operation_name }}'):
            view = object.__new__(FixedGraphQLView)
            with app.test_request_context('/'):
                result = view.render_graphql_ide(MagicMock(), request_data)
        return result if isinstance(result, str) else result.get_data(as_text=True)

    def test_operation_name_template_var_is_populated(self):
        """The snake_case template variable must not be empty."""
        content = self._render_op_name('MyQuery')
        self.assertIn('MyQuery', content)

    def test_none_operation_name_renders_null_not_empty(self):
        content = self._render_op_name(None)
        self.assertEqual(content, 'null')

    def test_operation_name_not_silently_dropped(self):
        """If the wrong key (operationName) were used, the template would
        render an empty string, not the JSON-encoded op name."""
        content = self._render_op_name('GetEmployees')
        self.assertNotEqual(content, '')
        self.assertNotEqual(content, 'null')


# ---------------------------------------------------------------------------
# FixedGraphQLView — Bug 5: no HTML-escaping of JSON template values
# ---------------------------------------------------------------------------

class TestFixedGraphQLViewNoHtmlEscaping(unittest.TestCase):
    """Bug 5 fix: json.dumps values must reach the template as raw JavaScript
    literals, not HTML-entity-encoded strings.

    Flask's render_template_string enables Jinja2 auto-escaping.  Without
    markupsafe.Markup the double-quote characters in json.dumps output are
    turned into ``&#34;`` (or ``&quot;``), which is invalid JavaScript and
    leaves the React root stuck on "Loading..." when the page is reloaded
    with a ``?query=...`` URL parameter.
    """

    def _render_raw(self, query=None, variables=None, operation_name=None,
                    template='{{query}}|{{variables}}|{{operation_name}}'):
        request_data = MagicMock()
        request_data.query          = query
        request_data.variables      = variables
        request_data.operation_name = operation_name

        with patch.object(GraphQLView, 'graphql_ide_html',
                          new_callable=PropertyMock, return_value=template):
            view = object.__new__(FixedGraphQLView)
            with app.test_request_context('/'):
                result = view.render_graphql_ide(MagicMock(), request_data)
        return result if isinstance(result, str) else result.get_data(as_text=True)

    def test_string_query_contains_raw_quotes_not_entities(self):
        """A string query must appear with raw " characters, not &#34;."""
        content = self._render_raw(query='{ employees { name } }',
                                   template='{{ query }}')
        self.assertNotIn('&#34;', content)
        self.assertNotIn('&quot;', content)
        self.assertIn('"', content)

    def test_dict_variables_contains_raw_quotes_not_entities(self):
        content = self._render_raw(variables={'limit': 5},
                                   template='{{ variables }}')
        self.assertNotIn('&#34;', content)
        self.assertNotIn('&quot;', content)

    def test_string_operation_name_contains_raw_quotes_not_entities(self):
        content = self._render_raw(operation_name='GetEmployees',
                                   template='{{ operation_name }}')
        self.assertNotIn('&#34;', content)
        self.assertNotIn('&quot;', content)
        self.assertIn('"', content)

    def test_rendered_query_is_valid_json(self):
        """The rendered query value must be parseable as JSON (valid JS literal)."""
        query = '{ employees { firstName lastName } }'
        content = self._render_raw(query=query, template='{{ query }}')
        self.assertEqual(json.loads(content), query)

    def test_rendered_variables_is_valid_json(self):
        variables = {'city': 'Seattle', 'limit': 10}
        content = self._render_raw(variables=variables,
                                   template='{{ variables }}')
        self.assertEqual(json.loads(content), variables)


class TestGraphQLSchemaIntrospection(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.endpoint = settings.FLASK_API_ENDPOINT

    def test_standard_introspection_query_fetches_schema(self):
        from graphql import get_introspection_query
        response = self.client.post(self.endpoint, json={
            'query': get_introspection_query(descriptions=True),
        })
        body = response.get_json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['__schema']['queryType']['name'], 'Query')

    def test_role_schemas_preserve_graphene_types_and_validate(self):
        import grapinator.schema as schema_module
        for roles in ((), ('hr',), ('sales',)):
            role_schema = schema_module.get_schema_for_roles(roles)
            self.assertEqual(validate_schema(role_schema), [])
            self.assertIsNotNone(role_schema.get_type('Employees').graphene_type)

    def test_invalid_relay_node_ids_return_null_without_errors(self):
        invalid_ids = (
            'garbage',
            base64.b64encode(b'UnknownType:1').decode('ascii'),
        )
        for global_id in invalid_ids:
            with self.subTest(global_id=global_id):
                response = self.client.post(self.endpoint, json={
                    'query': '{ node(id: "' + global_id + '") { id } }',
                })
                self.assertEqual(response.get_json(), {'data': {'node': None}})

    def test_rbac_introspection_and_selection_follow_request_roles(self):
        import grapinator.schema as schema_module
        field_registry = schema_module._FIELD_AUTH_ROLES
        filter_registry = schema_module._QUERY_FILTER_AUTH_ROLES
        original_fields = dict(field_registry)
        original_filters = dict(filter_registry)
        field_registry['Employees'] = {'birth_date': ['hr']}
        filter_registry['employees'] = {'birth_date': ['hr']}
        schema_module._schema_for_role_key.cache_clear()
        self.addCleanup(schema_module._schema_for_role_key.cache_clear)
        self.addCleanup(field_registry.update, original_fields)
        self.addCleanup(filter_registry.update, original_filters)
        self.addCleanup(field_registry.clear)
        self.addCleanup(filter_registry.clear)

        introspection_query = (
            '{ employeeType: __type(name: "Employees") { fields { name } } '
            'queryType: __type(name: "Query") { fields { name args { name } } } }'
        )
        hr_response = self.client.post(
            self.endpoint,
            json={'query': introspection_query},
            environ_overrides={
                'grapinator.user_roles': ['hr'],
                'grapinator.authenticated': True,
            },
        ).get_json()
        reader_response = self.client.post(
            self.endpoint,
            json={'query': introspection_query},
            environ_overrides={
                'grapinator.user_roles': ['reader'],
                'grapinator.authenticated': True,
            },
        ).get_json()

        hr_employee_fields = {
            field['name'] for field in hr_response['data']['employeeType']['fields']
        }
        hr_employee_args = {
            arg['name']
            for field in hr_response['data']['queryType']['fields']
            if field['name'] == 'employees'
            for arg in field['args']
        }
        reader_employee_fields = {
            field['name'] for field in reader_response['data']['employeeType']['fields']
        }
        reader_employee_args = {
            arg['name']
            for field in reader_response['data']['queryType']['fields']
            if field['name'] == 'employees'
            for arg in field['args']
        }
        self.assertIn('birth_date', hr_employee_fields)
        self.assertIn('birth_date', hr_employee_args)
        self.assertNotIn('birth_date', reader_employee_fields)
        self.assertNotIn('birth_date', reader_employee_args)

        hidden_field_response = self.client.post(
            self.endpoint,
            json={'query': '{ employees { edges { node { birth_date foo } } } }'},
            environ_overrides={
                'grapinator.user_roles': [],
                'grapinator.authenticated': False,
            },
        ).get_json()
        self.assertEqual(
            [error['message'] for error in hidden_field_response['errors']],
            [
                "Cannot query field 'birth_date' on type 'Employees'.",
                "Cannot query field 'foo' on type 'Employees'.",
            ],
        )

        for roles, authenticated in (([], False), (['reader'], True)):
            context_overrides = {
                'grapinator.user_roles': roles,
                'grapinator.authenticated': authenticated,
            }
            protected_argument = self.client.post(
                self.endpoint,
                json={'query': '{ employees(birth_date: "1980-01-01") '
                                '{ edges { node { employee_id } } } }'},
                environ_overrides=context_overrides,
            ).get_json()
            unknown_argument = self.client.post(
                self.endpoint,
                json={'query': '{ employees(absent_probe: "1980-01-01") '
                                '{ edges { node { employee_id } } } }'},
                environ_overrides=context_overrides,
            ).get_json()
            protected_messages = [
                error['message'] for error in protected_argument['errors']
            ]
            unknown_messages = [
                error['message'] for error in unknown_argument['errors']
            ]
            self.assertEqual(
                [message.replace('birth_date', 'probe') for message in protected_messages],
                [message.replace('absent_probe', 'probe') for message in unknown_messages],
            )
            self.assertFalse(any('Did you mean' in message for message in protected_messages))

        hr_unknown_argument = self.client.post(
            self.endpoint,
            json={'query': '{ employees(birth_dat: "1980-01-01") '
                            '{ edges { node { employee_id } } } }'},
            environ_overrides={
                'grapinator.user_roles': ['hr'],
                'grapinator.authenticated': True,
            },
        ).get_json()
        self.assertTrue(any(
            'Did you mean' in error['message']
            and 'birth_date' in error['message']
            for error in hr_unknown_argument['errors']
        ))


class TestGraphQLErrorMasking(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.endpoint = settings.FLASK_API_ENDPOINT

    def test_invalid_regex_has_safe_message_at_http_boundary(self):
        response = self.client.post(self.endpoint, json={
            'query': '{ employees(first_name: "[", matches: "regex") '
                     '{ edges { node { employee_id } } } }',
        })
        payload = response.get_json()
        self.assertEqual(payload['errors'][0]['message'], 'Invalid regex pattern.')
        for leaked_value in ('SELECT', 'BirthDate', 'HomePhone', 'parameters'):
            self.assertNotIn(leaked_value, json.dumps(payload))

    def test_database_errors_are_masked_at_http_boundary(self):
        from sqlalchemy.exc import OperationalError
        import grapinator.schema as schema_module

        secret = 'SELECT BirthDate FROM Employees WHERE id=:employee_id'
        original = OperationalError(secret, {'employee_id': 1}, RuntimeError('driver detail'))
        with patch.object(
            schema_module.MyConnectionField,
            'get_query',
            side_effect=original,
        ):
            with self.assertLogs('grapinator.app', level='ERROR') as captured:
                response = self.client.post(self.endpoint, json={
                    'query': '{ employees(first: 1) { edges { node { employee_id } } } }',
                })

        payload = response.get_json()
        error = payload['errors'][0]
        self.assertEqual(error['message'], 'Internal server error.')
        correlation_id = error['extensions']['correlation_id']
        self.assertIn(correlation_id, captured.output[0])
        self.assertIn(secret, '\n'.join(captured.output))
        self.assertNotIn(secret, json.dumps(payload))

    def test_unexpected_errors_are_masked_and_logged_with_correlation_id(self):
        view = object.__new__(FixedGraphQLView)
        secret = 'SELECT BirthDate, HomePhone FROM Employees WHERE id=:parameters'
        original = RuntimeError(secret)
        result = ExecutionResult(errors=[GraphQLError(secret, original_error=original)])

        with self.assertLogs('grapinator.app', level='ERROR') as captured:
            response = view.process_result(None, result)

        error = response['errors'][0]
        self.assertEqual(error['message'], 'Internal server error.')
        correlation_id = error['extensions']['correlation_id']
        self.assertTrue(correlation_id)
        self.assertIn(correlation_id, captured.output[0])
        self.assertIn(secret, '\n'.join(captured.output))
        response_text = json.dumps(response)
        for leaked_value in ('SELECT', 'BirthDate', 'HomePhone', 'parameters'):
            self.assertNotIn(leaked_value, response_text)

    def test_client_errors_keep_their_safe_message(self):
        view = object.__new__(FixedGraphQLView)
        error = GraphQLError(
            'Invalid regex pattern.',
            original_error=ClientError('Invalid regex pattern.'),
        )
        response = view.process_result(None, ExecutionResult(errors=[error]))
        self.assertEqual(response['errors'][0]['message'], 'Invalid regex pattern.')


if __name__ == '__main__':
    unittest.main()
