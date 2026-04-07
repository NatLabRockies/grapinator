#!/bin/sh
# RBAC test — queries birth_date which is restricted to the 'hr' role in schema_rbac.dct.
#
# IMPORTANT: JWT auth (BearerAuthMiddleware) is only active when the service is
# running under the CherryPy WSGI server (svc_cherrypy.py).  Flask's built-in
# development server (app.py / `flask run`) does NOT insert the auth middleware
# and will return data for ALL fields regardless of role.
#
# Start the server with:
#   python grapinator/svc_cherrypy.py
#
# Expected result with role 'hr':  birth_date has a real value.
# Expected result with no token:   birth_date is null (mixed mode).

TOKEN=$(python tools/dev_jwt.py --roles hr --secret grapinator-rbac-dev-only-not-for-production)
curl -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ employees { edges { node { employee_id first_name birth_date} } } }"}' \
    http://localhost:8443/northwind/gql
