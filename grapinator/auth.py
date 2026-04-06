"""
auth.py

IdP-agnostic JWT bearer token authentication middleware for Grapinator.

:class:`BearerAuthMiddleware` is a WSGI middleware that validates ``Authorization:
Bearer <token>`` headers against any OIDC-compatible identity provider
(Azure Entra ID, Keycloak, Auth0, …) by using standard RFC 7517 / RFC 7519
parameters configured in ``grapinator.ini``.  No provider-specific logic
lives in this module — all IdP specifics are externalized to configuration.

Three auth modes
~~~~~~~~~~~~~~~~
**off** (default)
    Middleware is a no-op; every request passes through untouched.
    Existing deployments are completely unaffected.

**mixed**
    Requests without a token are passed through as *unauthenticated*
    (``grapinator.user_roles`` is set to an empty list).  Requests with an
    invalid token always receive a 401 — a bad token never silently downgrades
    to unauthenticated.  Field- and entity-level RBAC checks in
    ``schema.py`` then return ``null`` / empty results for role-restricted
    data when the user lacks the required roles.

**required**
    Every request must carry a valid bearer token (except CORS preflight
    OPTIONS requests and, optionally, bare GraphiQL IDE GET requests — see
    ``GRAPHIQL_ACCESS`` below).

Token signing
~~~~~~~~~~~~~
**Production** — configure ``AUTH_JWKS_URI`` and optionally ``AUTH_ISSUER``
/ ``AUTH_AUDIENCE``.  ``PyJWKClient`` fetches and caches the public keys from
the JWKS endpoint; ``jwt.decode`` performs RFC 7519 validation.  Works with
any OIDC-compliant IdP.

**Local development** — set ``AUTH_DEV_SECRET`` (HS256).  No JWKS endpoint
is needed; tokens are signed/validated with a shared HMAC-SHA256 key.
**Never** use ``AUTH_DEV_SECRET`` in production — it offers no public-key
verification.  When ``AUTH_JWKS_URI`` is also set, the JWKS path takes
precedence and the dev secret is ignored.

Roles extraction
~~~~~~~~~~~~~~~~
The ``AUTH_ROLES_CLAIM`` setting supports dotted-path notation so that
nested claims such as ``realm_access.roles`` (Keycloak) are traversed
automatically.  Standard Entra ID / Auth0 flat ``roles`` claims work too.

GraphiQL access (``GRAPHIQL_ACCESS``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``authenticated`` (default)
    All requests — including bare GET requests that would normally serve the
    GraphiQL IDE HTML — require a valid bearer token.

``open``
    Bare GET requests with ``Accept: text/html`` and no ``?query=`` parameter
    are forwarded to the GraphiQL IDE without an auth check.  All other
    requests (including GET with ``?query=``) still require a token in
    ``mixed``/``required`` mode.

``off``
    The ``graphql_ide`` kwarg in ``app.py`` is set to ``None`` so Flask never
    serves the IDE HTML at all.  Middleware does nothing special for this
    value.
"""

import json
import logging

logger = logging.getLogger(__name__)


def _extract_bearer_token(environ):
    """Return the raw token string from ``Authorization: Bearer <token>``, or ``None``."""
    auth_header = environ.get('HTTP_AUTHORIZATION', '')
    if auth_header.lower().startswith('bearer '):
        return auth_header[7:].strip()
    return None


def _get_roles_from_payload(payload, roles_claim):
    """
    Walk a dotted-path *roles_claim* through *payload* and return the roles list.

    Supports flat claims (``roles``) and nested claims (``realm_access.roles``).
    Returns an empty list if the claim is absent or the path cannot be traversed.

    :param payload:      Decoded JWT payload dict.
    :param roles_claim:  Dotted-path string, e.g. ``"roles"`` or
                         ``"realm_access.roles"``.
    :returns:            List of role strings (may be empty).
    """
    parts = roles_claim.split('.')
    value = payload
    for part in parts:
        if not isinstance(value, dict):
            return []
        value = value.get(part)
        if value is None:
            return []
    if isinstance(value, list):
        return [str(r) for r in value]
    return []


def _json_401(message):
    """Build a WSGI-compatible 401 response with a GraphQL-format error body."""
    body = json.dumps({'errors': [{'message': message}]}).encode('utf-8')
    return (
        '401 Unauthorized',
        [('Content-Type', 'application/json'), ('Content-Length', str(len(body)))],
        [body],
    )


class BearerAuthMiddleware:
    """
    WSGI middleware that validates JWT bearer tokens and injects auth state
    into the WSGI environ for downstream Flask request handlers.

    Downstream code reads auth state from two environ keys:

    ``grapinator.user_roles``
        A list of role strings extracted from the validated JWT (may be empty
        for unauthenticated requests in *mixed* mode).

    ``grapinator.authenticated``
        ``True`` when a valid token was presented; ``False`` otherwise.

    :param wsgi_app:     The next WSGI application in the stack.
    :param auth_settings: A :class:`~grapinator.settings.Settings` instance
                          from which ``AUTH_*`` and ``GRAPHIQL_ACCESS``
                          attributes are read.
    :param _signing_key: **Test-only** override.  When provided, token
                         validation uses this key directly instead of a
                         JWKS endpoint or dev secret.  Pass a
                         ``jwt.algorithms.RSAAlgorithm``-compatible key
                         object or a plain secret string.
    """

    def __init__(self, wsgi_app, auth_settings, _signing_key=None):
        self.app = wsgi_app
        self.mode = getattr(auth_settings, 'AUTH_MODE', 'off').lower()
        self.graphiql_access = getattr(auth_settings, 'GRAPHIQL_ACCESS', 'authenticated').lower()
        self.roles_claim = getattr(auth_settings, 'AUTH_ROLES_CLAIM', 'roles')
        self.issuer = getattr(auth_settings, 'AUTH_ISSUER', None)
        self.audience = getattr(auth_settings, 'AUTH_AUDIENCE', None)
        raw_algs = getattr(auth_settings, 'AUTH_ALGORITHMS', 'RS256')
        self.algorithms = [a.strip() for a in raw_algs.split(',')]
        self.dev_secret = getattr(auth_settings, 'AUTH_DEV_SECRET', None)
        self._jwks_client = None
        self._signing_key = _signing_key  # test override

        # Initialise the JWKS client only when a URI is configured and no
        # test key override is present.
        jwks_uri = getattr(auth_settings, 'AUTH_JWKS_URI', None)
        cache_ttl = getattr(auth_settings, 'AUTH_JWKS_CACHE_TTL', 300)
        if jwks_uri and _signing_key is None:
            try:
                import jwt as _jwt
                self._jwks_client = _jwt.PyJWKClient(
                    jwks_uri,
                    cache_jwk_set=True,
                    lifespan=cache_ttl,
                )
            except Exception as exc:
                logger.warning('BearerAuthMiddleware: could not initialise PyJWKClient: %s', exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _decode_token(self, token):
        """
        Validate *token* and return the decoded payload dict.

        Validation order:
        1. If a test signing-key override was provided, use it directly.
        2. Else if a JWKS client is configured, use JWKS lookup (production).
        3. Else if a dev secret is configured, decode with HS256 (local dev).

        :raises Exception: Any ``jwt`` exception on validation failure.
        :returns: Decoded JWT payload dict.
        """
        import jwt as _jwt

        decode_kwargs = {}
        if self.issuer:
            decode_kwargs['issuer'] = self.issuer
        if self.audience:
            decode_kwargs['audience'] = self.audience

        if self._signing_key is not None:
            # Test override path — key provided directly
            return _jwt.decode(
                token, self._signing_key, algorithms=self.algorithms, **decode_kwargs
            )

        if self._jwks_client is not None:
            # Production path — resolve signing key from JWKS
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            return _jwt.decode(
                token, signing_key.key, algorithms=self.algorithms, **decode_kwargs
            )

        if self.dev_secret:
            # Local development path — HS256 with shared secret
            return _jwt.decode(
                token, self.dev_secret, algorithms=['HS256'], **decode_kwargs
            )

        raise ValueError('No signing key or JWKS URI configured for token validation.')

    def _is_graphiql_ide_request(self, environ):
        """
        Return ``True`` when the request looks like a bare GraphiQL IDE page load:
        a GET with ``Accept: text/html`` and no ``query`` query-string parameter.
        """
        if environ.get('REQUEST_METHOD') != 'GET':
            return False
        accept = environ.get('HTTP_ACCEPT', '')
        if 'text/html' not in accept:
            return False
        query_string = environ.get('QUERY_STRING', '')
        return 'query' not in query_string

    def __call__(self, environ, start_response):
        """
        Process a WSGI request, validating the bearer token when required.

        Sets ``grapinator.user_roles`` and ``grapinator.authenticated`` in
        *environ* for downstream use, or returns a 401 response when auth
        fails.

        :param environ:        PEP 3333 WSGI environment dict.
        :param start_response: WSGI ``start_response`` callable.
        :returns: Iterable of response body byte chunks.
        """
        # Auth is disabled — pass through immediately without touching environ.
        if self.mode == 'off':
            environ.setdefault('grapinator.user_roles', [])
            environ.setdefault('grapinator.authenticated', False)
            return self.app(environ, start_response)

        # Always pass CORS preflight OPTIONS requests through without auth.
        if environ.get('REQUEST_METHOD') == 'OPTIONS':
            environ.setdefault('grapinator.user_roles', [])
            environ.setdefault('grapinator.authenticated', False)
            return self.app(environ, start_response)

        # GraphiQL IDE bypass: bare GET with text/html and no ?query= parameter.
        if self._is_graphiql_ide_request(environ) and self.graphiql_access == 'open':
            environ['grapinator.user_roles'] = []
            environ['grapinator.authenticated'] = False
            return self.app(environ, start_response)

        token = _extract_bearer_token(environ)

        if token is None:
            if self.mode == 'mixed':
                # No token in mixed mode → unauthenticated passthrough.
                environ['grapinator.user_roles'] = []
                environ['grapinator.authenticated'] = False
                return self.app(environ, start_response)
            else:
                # required mode → no token means 401.
                status, headers, body = _json_401('Authentication required.')
                start_response(status, headers)
                return body

        # Token is present — validate it regardless of mode; an invalid
        # token never silently downgrades to unauthenticated.
        try:
            payload = self._decode_token(token)
        except Exception as exc:
            logger.debug('BearerAuthMiddleware: token validation failed: %s', exc)
            exc_name = type(exc).__name__
            if 'Expired' in exc_name:
                msg = 'Token has expired.'
            elif 'Audience' in exc_name:
                msg = 'Invalid token audience.'
            elif 'Issuer' in exc_name:
                msg = 'Invalid token issuer.'
            else:
                msg = 'Invalid token.'
            status, headers, body = _json_401(msg)
            start_response(status, headers)
            return body

        roles = _get_roles_from_payload(payload, self.roles_claim)
        environ['grapinator.user_roles'] = roles
        environ['grapinator.authenticated'] = True
        return self.app(environ, start_response)
