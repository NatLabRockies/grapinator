#!/bin/sh
# Start local RBAC-enabled GraphiQL and print an HR token for its HTTP Headers panel.
set -eu

if [ -z "${GQLAPI_CRYPT_KEY:-}" ]; then
    echo "Set GQLAPI_CRYPT_KEY before running this script." >&2
    exit 2
fi

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
PORT=${GRAPINATOR_DEV_PORT:-8443}

DEV_SECRET=grapinator-rbac-dev-only-not-for-production
TOKEN=$(python tools/dev_jwt.py --roles hr --secret "$DEV_SECRET" --expiry 3600 2>/dev/null)

cat <<EOF
Local RBAC GraphiQL is starting.
Open: http://localhost:$PORT/northwind/gql

In GraphiQL's HTTP Headers panel, paste:
{"Authorization": "Bearer $TOKEN"}

After setting the header, use the toolbar's schema re-fetch action.
This development token expires in one hour. Do not use it in production.
EOF

exec env GRAPINATOR_CONFIG=/resources/grapinator_rbac.ini \
    gunicorn --config grapinator/resources/gunicorn.conf.py \
    --bind "127.0.0.1:$PORT" \
    grapinator.svc_gunicorn:application
