#!/bin/sh

TOKEN=$(curl -s -X POST \
    http://localhost:8080/realms/grapinator-dev/protocol/openid-connect/token \
    -d "client_id=grapinator-api" \
    -d "client_secret=grapinator-api-secret" \
    -d "username=hruser" \
    -d "password=hruser" \
    -d "grant_type=password" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token') or d)")

curl -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ employees { edges { node { employee_id first_name birth_date} } } }"}' \
    http://localhost:8443/northwind/gql
