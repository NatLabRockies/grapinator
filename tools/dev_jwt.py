#!/usr/bin/env python3
"""
dev_jwt.py — Local development JWT generator for Grapinator

Generates a short-lived HS256-signed JWT that can be used to authenticate
against a locally-running Grapinator instance configured with
``AUTH_DEV_SECRET``.

**This tool is for local development only.**  HS256 tokens rely on a shared
secret; they provide no public-key verification and are not suitable for
production deployments.  Production deployments use JWKS and RS256 tokens
issued by a real identity provider.

Setup
-----
1. In your local ``grapinator.ini`` add (or uncomment)::

       [AUTH]
       AUTH_MODE = mixed          # or required
       AUTH_DEV_SECRET = change-me-local-dev-only

2. Set the same secret in the environment for the tool (optional — can pass
   via ``--secret`` on the command line)::

       export GRAPINATOR_DEV_SECRET=change-me-local-dev-only

3. Generate a token::

       python tools/dev_jwt.py --roles admin,reader
       # or specifying the secret inline:
       python tools/dev_jwt.py --secret change-me-local-dev-only --roles admin

4. Pass the token in API requests::

       curl -H "Authorization: Bearer <token>" http://localhost:8443/northwind/gql ...

Usage
-----
run ``python tools/dev_jwt.py --help`` for full options.

Options
-------
--secret    HMAC-SHA256 signing secret (overrides GRAPINATOR_DEV_SECRET env var).
--roles     Comma-separated list of role names to embed in the token
            (default: empty — unauthenticated pass-through in mixed mode).
--sub       Subject claim (default: "dev-user").
--expiry    Token lifetime in seconds (default: 3600 / 1 hour).
--claim     Dotted-path claim name used for roles (must match AUTH_ROLES_CLAIM
            in grapinator.ini; default: "roles").
--print-header
            Print the ready-to-paste Authorization header instead of just the
            token.
"""

import argparse
import os
import sys
import time


def _parse_args():
    parser = argparse.ArgumentParser(
        description='Generate an HS256 JWT for local Grapinator development.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--secret',
        default=os.environ.get('GRAPINATOR_DEV_SECRET'),
        help='HS256 signing secret (or set GRAPINATOR_DEV_SECRET env var).',
    )
    parser.add_argument(
        '--roles',
        default='',
        help='Comma-separated role names to embed (e.g. admin,reader).',
    )
    parser.add_argument(
        '--sub',
        default='dev-user',
        help='JWT subject claim (default: dev-user).',
    )
    parser.add_argument(
        '--expiry',
        type=int,
        default=3600,
        help='Token lifetime in seconds (default: 3600).',
    )
    parser.add_argument(
        '--claim',
        default='roles',
        help='Dotted-path roles claim name (must match AUTH_ROLES_CLAIM; default: roles).',
    )
    parser.add_argument(
        '--print-header',
        action='store_true',
        help='Print the full Authorization header value instead of just the token.',
    )
    return parser.parse_args()


def _set_nested(payload, dotted_path, value):
    """Set *value* at the dotted key path inside *payload*, creating dicts as needed."""
    parts = dotted_path.split('.')
    current = payload
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def main():
    args = _parse_args()

    if not args.secret:
        print(
            'Error: no signing secret provided.  Pass --secret or set '
            'GRAPINATOR_DEV_SECRET.',
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import jwt
    except ImportError:
        print(
            'Error: PyJWT is not installed.  Run: pip install PyJWT',
            file=sys.stderr,
        )
        sys.exit(1)

    now = int(time.time())
    roles = [r.strip() for r in args.roles.split(',') if r.strip()]

    payload = {
        'sub': args.sub,
        'iat': now,
        'exp': now + args.expiry,
    }
    _set_nested(payload, args.claim, roles)

    token = jwt.encode(payload, args.secret, algorithm='HS256')

    if args.print_header:
        print(f'Authorization: Bearer {token}')
    else:
        print(token)

    # Print a summary to stderr so it doesn't interfere with stdout capture.
    print(
        f'\nToken expires in {args.expiry}s.  Roles: {roles if roles else "(none — unauthenticated)"}',
        file=sys.stderr,
    )


if __name__ == '__main__':
    main()
