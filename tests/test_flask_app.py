"""Unit tests for Flask app behaviour (grapinator/app.py).

Covers:
  - SecurityHeadersMiddleware : security response headers (svc_cherrypy.py)
  - FixedGraphQLView          : the two bug-fixes for render_graphql_ide
      Bug 1 — None rendered as JSON null (not Python 'None' string)
      Bug 2 — operation_name passed with snake_case key so the template
              {{operation_name}} is populated correctly
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import json
import html
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from . import context  # noqa: F401

from graphql_server.flask.views import GraphQLView
from grapinator.app import app, FixedGraphQLView
from grapinator.svc_cherrypy import SecurityHeadersMiddleware, CorsMiddleware
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
        # json.dumps wraps the string in double-quotes; Jinja2 HTML-escapes them
        self.assertEqual(html.unescape(content),
                         json.dumps('{ employees { name } }'))

    def test_dict_variables_is_json_encoded(self):
        variables = {'first': 10}
        content = self._render(variables=variables, template='{{ variables }}')
        self.assertEqual(json.loads(html.unescape(content)), variables)


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
        # json.dumps('MyQuery') == '"MyQuery"'; Jinja2 HTML-escapes quotes
        self.assertIn('MyQuery', html.unescape(content))

    def test_none_operation_name_renders_null_not_empty(self):
        content = self._render_op_name(None)
        self.assertEqual(content, 'null')

    def test_operation_name_not_silently_dropped(self):
        """If the wrong key (operationName) were used, the template would
        render an empty string, not the JSON-encoded op name."""
        content = self._render_op_name('GetEmployees')
        self.assertNotEqual(content, '')
        self.assertNotEqual(content, 'null')


if __name__ == '__main__':
    unittest.main()
