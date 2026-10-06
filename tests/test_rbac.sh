#!/bin/sh
# RBAC test — birth_date is available only to roles listed in schema_rbac.dct.
#
# IMPORTANT: JWT auth (BearerAuthMiddleware) is only active when the service is
# running under the Gunicorn WSGI stack. Flask's built-in
# development server (app.py / `flask run`) does NOT insert the auth middleware
# and does not provide authenticated role-specific schemas.
#
# Start the server with:
#   GRAPINATOR_CONFIG=/resources/grapinator_rbac.ini gunicorn --config grapinator/resources/gunicorn.conf.py grapinator.svc_gunicorn:application
# Restart it after code updates; GraphQL schemas are compiled at startup.
#
# Expected result with role 'hr': birth_date is queryable and returned.
# Without a matching role, the same selection fails GraphQL validation.

TOKEN=$(python tools/dev_jwt.py --roles hr --secret grapinator-rbac-dev-only-not-for-production)
curl -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ employees(birth_date: \"1983-07-02\", matches: \"gt\", sort_by: \"birth_date\") { edges { node { employee_id first_name birth_date } } } }"}' \
    http://localhost:8443/northwind/gql
