import json
from flask import Flask, Request, Response, render_template_string
from flask_cors import CORS
from graphql_server.flask.views import GraphQLView
from graphql_server.http import GraphQLRequestData

from grapinator import settings, schema_settings, log
from grapinator.model import db_session
from grapinator.schema import gql_schema


class FixedGraphQLView(GraphQLView):
    """Fixes two bugs in graphql-server 3.0.0's render_graphql_ide:

    Bug 1 — None → "None": Python's None renders as the string "None" inside
    the Jinja2 template, which is a JS ReferenceError. json.dumps() correctly
    converts None to the JS literal null.

    Bug 2 — camelCase/snake_case mismatch: views.py calls
    render_template_string(..., operationName=...) but the graphiql.html
    template uses {{operation_name}} (snake_case), so operationName is always
    silently dropped, producing a JS SyntaxError (operationName: ,).
    """

    def render_graphql_ide(
        self, request: Request, request_data: GraphQLRequestData
    ) -> Response:
        return render_template_string(
            self.graphql_ide_html,
            query=json.dumps(request_data.query),
            variables=json.dumps(request_data.variables),
            # use snake_case to match {{operation_name}} in graphiql.html
            operation_name=json.dumps(request_data.operation_name),
        )


# setup Flask
app = Flask(__name__)

# add CORS support
CORS(app, resources={r"/*": {
    "origins": settings.CORS_EXPOSE_ORIGINS
    ,"send_wildcard": settings.CORS_SEND_WILDCARD
    ,"methods": settings.CORS_ALLOW_METHODS
    ,"max_age": settings.CORS_HEADER_MAX_AGE
    ,"allow_headers": settings.CORS_ALLOW_HEADERS
    ,"expose_headers": settings.CORS_EXPOSE_HEADERS
    ,"supports_credentials": settings.CORS_SUPPORTS_CREDENTIALS
    }})

# set server_name if running local, not docker or server
if settings.FLASK_SERVER_NAME != '':
    app.config['SERVER_NAME'] = settings.FLASK_SERVER_NAME
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = settings.SQLALCHEMY_TRACK_MODIFICATIONS

app.add_url_rule(
    settings.FLASK_API_ENDPOINT,
    view_func=FixedGraphQLView.as_view(
        'graphql',
        # graphql-server requires a graphql-core GraphQLSchema, not a graphene.Schema
        schema=gql_schema.graphql_schema,
        graphql_ide="graphiql"  # replaces deprecated graphiql=True
    )
)

# set default response headers per NREL spec.
@app.after_request
def apply_custom_response(response):
    # Existing spec headers from older version of Grapinator
    response.headers["X-Frame-Options"] = settings.HTTP_HEADERS_XFRAME
    response.headers["X-XSS-Protection"] = settings.HTTP_HEADERS_XSS_PROTECTION
    response.headers["Cache-Control"] = settings.HTTP_HEADER_CACHE_CONTROL
    response.headers["Access-Control-Allow-Headers"] = settings.CORS_ALLOW_HEADERS
    
    # Modern security headers (GraphiQL compatible)
    response.headers["X-Content-Type-Options"] = settings.HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS
    response.headers["Referrer-Policy"] = settings.HTTP_HEADERS_REFERRER_POLICY
    
    # Relaxed CSP for GraphiQL functionality
    response.headers["Content-Security-Policy"] = settings.HTTP_HEADERS_CONTENT_SECURITY_POLICY
    
    # Server information disclosure prevention
    response.headers.pop('Server', None)  # Remove server header if present
    
    return response

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

def main():
    log.info('>>>>> Starting development server at http://{}{} <<<<<'.format(app.config['SERVER_NAME'], settings.FLASK_API_ENDPOINT))
    # Note: can't use flask debug with vscode debugger.  default: False
    app.run(debug=settings.FLASK_DEBUG)

if __name__ == "__main__":
    main()
