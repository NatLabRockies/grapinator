"""
app.py

Flask application factory and entry point for the Grapinator GraphQL API.

This module:

  1. Defines :class:`FixedGraphQLView`, a patched subclass of the upstream
     ``GraphQLView`` that corrects two rendering bugs present in
     graphql-server 3.0.0.
  2. Creates and configures the Flask ``app`` instance, attaching the GraphQL
     endpoint from ``settings.FLASK_API_ENDPOINT``.
  3. Registers a teardown hook that removes the SQLAlchemy scoped session at
     the end of every request to prevent connection leaks.
  4. Exposes ``main()`` for running the built-in Flask development server
     (not intended for production use).

Production deployments should use :mod:`grapinator.svc_cherrypy` instead of
calling ``main()`` directly.
"""

import json
from flask import Flask, Request, Response, g, render_template_string, request as flask_request
from graphql_server.flask.views import GraphQLView
from graphql_server.http import GraphQLRequestData

from grapinator import settings, schema_settings, log
from grapinator.model import db_session
from grapinator.schema import gql_schema


class FixedGraphQLView(GraphQLView):
    """
    Patched ``GraphQLView`` that corrects two rendering bugs present in
    graphql-server 3.0.0 and injects JWT auth state into the GraphQL
    execution context.

    **Bug 1 — ``None`` serialised as the string ``"None"``:**
    Python's ``None`` renders as the literal string ``"None"`` inside Jinja2
    templates.  In a JavaScript context this becomes a ``ReferenceError``
    because ``None`` is not a valid JS identifier.  Wrapping values with
    ``json.dumps()`` converts ``None`` to the JS ``null`` literal correctly.

    **Bug 2 — camelCase / snake_case mismatch:**
    The upstream ``views.py`` calls
    ``render_template_string(..., operationName=...)`` using camelCase, but
    the ``graphiql.html`` template references ``{{ operation_name }}``
    (snake_case).  The camelCase keyword is silently ignored by Jinja2,
    leaving the placeholder empty and producing a JS ``SyntaxError``
    (``operationName: ,``).  This override uses ``operation_name`` to match
    the template variable name.
    """

    def render_graphql_ide(
        self, request: Request, request_data: GraphQLRequestData
    ) -> Response:
        """
        Render the GraphiQL IDE HTML page with the current request's query,
        variables, and operation name pre-populated.

        Overrides the upstream implementation to:
        - Use ``json.dumps()`` for all template values so Python ``None``
          becomes JS ``null`` rather than the string ``"None"``.
        - Pass ``operation_name`` (snake_case) to match the ``{{ operation_name }}``
          placeholder in ``graphiql.html`` instead of the mismatched camelCase
          ``operationName`` keyword used by the upstream view.

        :param request:      The current Flask ``Request`` object.
        :param request_data: Parsed GraphQL request fields (query, variables,
                             operation_name).
        :returns: Flask ``Response`` containing the rendered GraphiQL HTML.
        """
        return render_template_string(
            self.graphql_ide_html,
            query=json.dumps(request_data.query),
            variables=json.dumps(request_data.variables),
            # snake_case matches {{ operation_name }} in graphiql.html
            operation_name=json.dumps(request_data.operation_name),
        )

    def get_context(self, request: Request, response: Response) -> dict:
        """
        Return the GraphQL execution context dict used by resolvers.

        Overrides the default implementation to expose ``user_roles`` and
        ``authenticated`` (populated by
        :class:`~grapinator.auth.BearerAuthMiddleware` via
        :func:`_load_auth_state`) so that field- and entity-level RBAC checks
        in ``schema.py`` can gate access without coupling to the WSGI environ.

        :param request:  The current Flask ``Request`` object.
        :param response: The current Flask ``Response`` object.
        :returns: Dict with keys ``request``, ``response``, ``user_roles``,
                  and ``authenticated``.
        """
        return {
            'request': request,
            'response': response,
            'user_roles': getattr(g, 'user_roles', []),
            'authenticated': getattr(g, 'authenticated', False),
        }


# ---------------------------------------------------------------------------
# Flask application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

# SERVER_NAME is only set for local development.  In Docker / production
# deployments this value is left empty and Flask binds to all interfaces.
if settings.FLASK_SERVER_NAME != '':
    app.config['SERVER_NAME'] = settings.FLASK_SERVER_NAME

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = settings.SQLALCHEMY_TRACK_MODIFICATIONS


@app.before_request
def _load_auth_state():
    """
    Copy JWT auth state placed by :class:`~grapinator.auth.BearerAuthMiddleware`
    in the WSGI environ into Flask's ``g`` object.

    ``g.user_roles``     — list of role strings from the validated token;
                           empty list for unauthenticated requests.
    ``g.authenticated``  — ``True`` when a valid bearer token was presented.

    These values are consumed by :meth:`FixedGraphQLView.get_context` and are
    available to any other Flask extension or view that needs auth information.
    """
    g.user_roles = flask_request.environ.get('grapinator.user_roles', [])
    g.authenticated = flask_request.environ.get('grapinator.authenticated', False)


# GraphiQL IDE is served only when GRAPHIQL_ACCESS is not 'off'.
# When 'off', graphql_ide=None tells graphql-server to return plain JSON
# for all GET requests instead of rendering the IDE HTML.
_graphql_ide = 'graphiql' if settings.GRAPHIQL_ACCESS != 'off' else None

# Register the GraphQL endpoint using the patched view class.
# graphql-server requires a graphql-core ``GraphQLSchema`` object, so we
# pass ``gql_schema.graphql_schema`` rather than the raw ``graphene.Schema``.
# Auth context (user_roles, authenticated) is injected per-request via the
# get_context() override on FixedGraphQLView, which reads from Flask's g.
app.add_url_rule(
    settings.FLASK_API_ENDPOINT,
    view_func=FixedGraphQLView.as_view(
        'graphql',
        schema=gql_schema.graphql_schema,
        graphql_ide=_graphql_ide,
    )
)

@app.teardown_appcontext
def shutdown_session(exception=None):
    """
    Remove the SQLAlchemy scoped session at the end of every request.

    Flask calls this hook after each request context is torn down, regardless
    of whether the request succeeded or raised an exception.  Calling
    ``db_session.remove()`` returns the underlying connection to the pool and
    ensures that no session state leaks between requests.

    :param exception: The unhandled exception that caused the context to tear
                      down, or ``None`` if the request completed normally.
    """
    db_session.remove()

def main():
    """
    Start the Flask built-in development server.

    This entry point is intended for local development only.  It reads the
    server address from ``app.config['SERVER_NAME']`` and the debug flag from
    ``settings.FLASK_DEBUG``.

    .. warning::
        The Flask development server is **not** suitable for production use.
        For production or Docker deployments use :mod:`grapinator.svc_cherrypy`.

    .. note::
        Flask's built-in reloader is incompatible with the VS Code debugger.
        ``FLASK_DEBUG`` should remain ``False`` during debugger sessions.
    """
    log.info('>>>>> Starting development server at http://{}{} <<<<<'.format(
        app.config['SERVER_NAME'], settings.FLASK_API_ENDPOINT
    ))
    app.run(debug=settings.FLASK_DEBUG)

if __name__ == "__main__":
    main()
