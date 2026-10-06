#!/bin/sh
# RBAC sort test — birth_date requires the 'hr' role in schema_rbac.dct.
#
# IMPORTANT: JWT auth (BearerAuthMiddleware) is inserted by the Gunicorn WSGI
# stack. Flask's built-in development server (app.py / `flask run`) does NOT
# insert the auth middleware and will return data for ALL fields regardless of role.
#
# Start the server with:
#   gunicorn --config grapinator/resources/gunicorn.conf.py grapinator.svc_gunicorn:application
#
# Expected result with role 'hr':  birth_date has a real value and can be used for sorting.
# Expected result with no token:   birth_date is null (mixed mode).

TOKEN=$(python tools/dev_jwt.py --roles hr --secret grapinator-rbac-dev-only-not-for-production)
curl -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ employees(birth_date: \"1972-02-19\" matches: \"gt\" sort_by: \"birth_date\") { edges { node { employee_id first_name birth_date} } } }"}' \
    http://localhost:8443/northwind/gql
