#!/bin/sh
# Verify role-dependent visibility and use of the protected birth_date field.
set -eu

if [ -z "${GQLAPI_CRYPT_KEY:-}" ]; then
    echo "Set GQLAPI_CRYPT_KEY before running this test." >&2
    exit 2
fi

PORT=${GRAPINATOR_TEST_PORT:-18443}
URL="http://127.0.0.1:${PORT}/northwind/gql"
SERVER_LOG=$(mktemp)
SERVER_PID=

cleanup() {
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" >/dev/null 2>&1 || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    rm -f "$SERVER_LOG"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

post_graphql() {
    query_text=$1
    token=$2
    request_body=$(QUERY_TEXT="$query_text" python -c \
        'import json, os; print(json.dumps({"query": os.environ["QUERY_TEXT"]}))')
    if [ -n "$token" ]; then
        curl --silent --retry 20 --retry-connrefused \
            --retry-delay 1 --retry-max-time 20 \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d "$request_body" "$URL"
    else
        curl --silent --retry 20 --retry-connrefused \
            --retry-delay 1 --retry-max-time 20 \
            -H "Content-Type: application/json" \
            -d "$request_body" "$URL"
    fi
}

TOKEN=$(python tools/dev_jwt.py --roles hr --secret grapinator-rbac-dev-only-not-for-production)

GRAPINATOR_CONFIG=/resources/grapinator_rbac.ini \
    gunicorn --config grapinator/resources/gunicorn.conf.py \
    --bind "127.0.0.1:${PORT}" --workers 1 --threads 1 --log-level warning \
    grapinator.svc_gunicorn:application >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

INTROSPECTION_QUERY='{ employee: __type(name: "Employees") { fields { name } } root: __type(name: "Query") { fields { name args(includeDeprecated: true) { name } } } where: __type(name: "EmployeesFilter") { inputFields { name } } }'
HR_INTROSPECTION=$(post_graphql "$INTROSPECTION_QUERY" "$TOKEN") || {
    cat "$SERVER_LOG" >&2
    exit 1
}
printf '%s\n' "$HR_INTROSPECTION" | python -c '
import json
import sys
response = json.load(sys.stdin)
if response.get("errors"):
    print(response["errors"], file=sys.stderr)
    raise SystemExit(1)
fields = {field["name"] for field in response["data"]["employee"]["fields"]}
arguments = {
    arg["name"]
    for field in response["data"]["root"]["fields"]
    if field["name"] == "employees"
    for arg in field["args"]
}
where_fields = {field["name"] for field in response["data"]["where"]["inputFields"]}
if "birth_date" not in fields or "birth_date" not in arguments or "birth_date" not in where_fields:
    print("HR schema is missing the protected output field, filter argument, or where field", file=sys.stderr)
    raise SystemExit(1)
'

HR_QUERY='{ employees(first: 10, birth_date: "1972-02-19", matches: "gt", sort_by: "birth_date", sort_dir: "asc") { edges { node { employee_id first_name birth_date } } } }'
HR_RESULT=$(post_graphql "$HR_QUERY" "$TOKEN")
printf '%s\n' "$HR_RESULT" | python -c '
import json
import sys
response = json.load(sys.stdin)
if response.get("errors"):
    print(response["errors"], file=sys.stderr)
    raise SystemExit(1)
print("PASS: HR can filter, sort, and read birth_date; returned", len(response["data"]["employees"]["edges"]), "employees")
'

ANON_INTROSPECTION=$(post_graphql "$INTROSPECTION_QUERY" "")
printf '%s\n' "$ANON_INTROSPECTION" | python -c '
import json
import sys
response = json.load(sys.stdin)
if response.get("errors"):
    print(response["errors"], file=sys.stderr)
    raise SystemExit(1)
fields = {field["name"] for field in response["data"]["employee"]["fields"]}
arguments = {
    arg["name"]
    for field in response["data"]["root"]["fields"]
    if field["name"] == "employees"
    for arg in field["args"]
}
where_fields = {field["name"] for field in response["data"]["where"]["inputFields"]}
if "birth_date" in fields or "birth_date" in arguments or "birth_date" in where_fields:
    print("birth_date is unexpectedly visible without the HR role", file=sys.stderr)
    raise SystemExit(1)
'

ANON_QUERY=$(post_graphql "$HR_QUERY" "")
printf '%s\n' "$ANON_QUERY" | python -c '
import json
import sys
response = json.load(sys.stdin)
if not any("birth_date" in error["message"] for error in response.get("errors", [])):
    print("Expected the unauthenticated protected-field query to fail validation", file=sys.stderr)
    raise SystemExit(1)
print("PASS: unauthenticated schema hides birth_date and rejects its use")
'

WHERE_QUERY='{ employees(where: {birth_date: {gt: "1972-02-19T00:00:00"}}, sort_by: "birth_date") { edges { node { employee_id birth_date } } } }'
HR_WHERE=$(post_graphql "$WHERE_QUERY" "$TOKEN")
printf '%s\n' "$HR_WHERE" | python -c '
import json
import sys
response = json.load(sys.stdin)
if response.get("errors"):
    print(response["errors"], file=sys.stderr)
    raise SystemExit(1)
print("PASS: HR can filter by birth_date with where; returned", len(response["data"]["employees"]["edges"]), "employees")
'

ANON_WHERE=$(post_graphql '{ employees(where: {or: [{birth_date: {gt: "1972-02-19T00:00:00"}}]}) { edges { node { employee_id } } } }' "")
ANON_UNKNOWN=$(post_graphql '{ employees(where: {or: [{absent_probe: {gt: "1972-02-19T00:00:00"}}]}) { edges { node { employee_id } } } }' "")
PROTECTED="$ANON_WHERE" UNKNOWN="$ANON_UNKNOWN" python -c '
import json
import os
protected = [e["message"].replace("birth_date", "probe") for e in json.loads(os.environ["PROTECTED"]).get("errors", [])]
unknown = [e["message"].replace("absent_probe", "probe") for e in json.loads(os.environ["UNKNOWN"]).get("errors", [])]
if not protected or protected != unknown or any("Did you mean" in m for m in protected):
    print("Protected where field is distinguishable from an unknown field:", protected, unknown)
    raise SystemExit(1)
print("PASS: unauthenticated where on birth_date matches an unknown field error")
'
