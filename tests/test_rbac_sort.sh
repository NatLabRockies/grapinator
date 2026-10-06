#!/bin/sh
# RBAC schema visibility test — birth_date is marked sensitive in schema_rbac.dct.
#
# IMPORTANT: JWT auth (BearerAuthMiddleware) is inserted by the Gunicorn WSGI
# stack. Flask's built-in development server (app.py / `flask run`) does NOT
# insert the auth middleware and will return data for ALL fields regardless of role.
#
# Start the server with:
#   GRAPINATOR_CONFIG=/resources/grapinator_rbac.ini gunicorn --config grapinator/resources/gunicorn.conf.py grapinator.svc_gunicorn:application
#
# Expected result: the Employees fields list does not contain birth_date, even for HR.

TOKEN=$(python tools/dev_jwt.py --roles hr --secret grapinator-rbac-dev-only-not-for-production)
curl -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ __type(name: \"Employees\") { fields { name } } }"}' \
    http://localhost:8443/northwind/gql
