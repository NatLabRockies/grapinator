"""Unit tests for Flask app behaviour (grapinator/app.py).

Covers:
  - apply_custom_response  : security response headers
  - FixedGraphQLView       : the two bug-fixes for render_graphql_ide
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
from grapinator.app import app, apply_custom_response, FixedGraphQLView
from grapinator import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status=200, body='ok'):
    with app.test_request_context('/'):
        from flask import make_response
        return make_response(body, status)


class TestApplyCustomResponse(unittest.TestCase):
    """apply_custom_response must set all required security headers."""

    def setUp(self):
        self.response = _make_response()
        with app.test_request_context('/'):
            self.response = apply_custom_response(self.response)

    def test_x_frame_options_header_present(self):
        self.assertIn('X-Frame-Options', self.response.headers)

    def test_x_frame_options_value_matches_settings(self):
        self.assertEqual(
            self.response.headers['X-Frame-Options'],
            settings.HTTP_HEADERS_XFRAME,
        )

    def test_xss_protection_header_present(self):
        self.assertIn('X-XSS-Protection', self.response.headers)

    def test_xss_protection_value_matches_settings(self):
        self.assertEqual(
            self.response.headers['X-XSS-Protection'],
            settings.HTTP_HEADERS_XSS_PROTECTION,
        )

    def test_cache_control_header_present(self):
        self.assertIn('Cache-Control', self.response.headers)

    def test_cache_control_value_matches_settings(self):
        self.assertEqual(
            self.response.headers['Cache-Control'],
            settings.HTTP_HEADER_CACHE_CONTROL,
        )

    def test_access_control_allow_headers_present(self):
        self.assertIn('Access-Control-Allow-Headers', self.response.headers)

    def test_access_control_allow_headers_value_matches_settings(self):
        self.assertEqual(
            self.response.headers['Access-Control-Allow-Headers'],
            settings.CORS_ALLOW_HEADERS,
        )

    def test_original_response_body_preserved(self):
        self.assertEqual(self.response.get_data(as_text=True), 'ok')


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
