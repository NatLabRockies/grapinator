# Grapinator JWT Authentication — Design Notes

## Overview

The existing pattern is ideal for this work. The middleware stack in `svc_cherrypy.py` already layers `CorsMiddleware` → `SecurityHeadersMiddleware` → `WSGILogger` on top of the Flask app. JWT auth belongs as a new WSGI middleware in that same stack, and its configuration follows the exact same pattern as the existing `[CORS]` and `[HTTP_HEADERS]` sections.

---

## 1. `grapinator.ini` — Add a `[JWT]` section

All major OIDC-compliant providers (Azure AD, Amazon Cognito, Google Identity, Okta, Auth0, etc.) publish a **JWKS URI** — a well-known endpoint serving their current public signing keys. This single URI is the only provider-specific value needed to validate tokens from any of them:

```ini
[JWT]
JWT_ENABLED = True
JWT_ALGORITHM = RS256
JWT_AUDIENCE = api://my-application-id
JWT_ISSUER = https://login.microsoftonline.com/{tenant-id}/v2.0
JWT_JWKS_URI = https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys
JWT_LEEWAY_SECONDS = 10
```

Provider-specific example values:

| Provider | `JWT_ISSUER` | `JWT_JWKS_URI` |
|---|---|---|
| Azure AD | `https://login.microsoftonline.com/{tenant}/v2.0` | `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys` |
| Google | `https://accounts.google.com` | `https://www.googleapis.com/oauth2/v3/certs` |
| Amazon Cognito | `https://cognito-idp.{region}.amazonaws.com/{pool-id}` | `https://cognito-idp.{region}.amazonaws.com/{pool-id}/.well-known/jwks.json` |
| Okta / Auth0 | `https://{domain}/` | `https://{domain}/.well-known/jwks.json` |

---

## 2. `settings.py` — Add `JWT_*` attributes and load them

Following the existing pattern exactly — class-level `None` defaults, then `has_option` guard for the optional ones.

In the `Settings` class body, with the other attribute groups:

```python
JWT_ENABLED = None
JWT_ALGORITHM = None
JWT_AUDIENCE = None
JWT_ISSUER = None
JWT_JWKS_URI = None
JWT_LEEWAY_SECONDS = None
```

In `Settings.__init__`, after the `[HTTP_HEADERS]` block:

```python
# load JWT section (optional; defaults to disabled if section absent)
if properties.has_section('JWT'):
    self.JWT_ENABLED = properties.getboolean('JWT', 'JWT_ENABLED')
    self.JWT_ALGORITHM = properties.get('JWT', 'JWT_ALGORITHM')
    self.JWT_AUDIENCE = properties.get('JWT', 'JWT_AUDIENCE')
    self.JWT_ISSUER = properties.get('JWT', 'JWT_ISSUER')
    self.JWT_JWKS_URI = properties.get('JWT', 'JWT_JWKS_URI')
    self.JWT_LEEWAY_SECONDS = properties.getint('JWT', 'JWT_LEEWAY_SECONDS')
else:
    self.JWT_ENABLED = False
```

Using `has_section` means deployments without the `[JWT]` section continue to work unchanged.

---

## 3. `svc_cherrypy.py` — Add `JWTAuthMiddleware`

This follows the exact same shape as `CorsMiddleware` and `SecurityHeadersMiddleware`. It intercepts requests before they reach Flask, validates the Bearer token, and returns `401 Unauthorized` if validation fails:

```python
import json
import time
import urllib.request
from jose import jwt, jwk, JWTError   # python-jose[cryptography]

class JWTAuthMiddleware:
    """
    WSGI middleware that validates a Bearer JWT on every request.

    Public keys are fetched from JWT_JWKS_URI once and cached. Works with
    any OIDC-compliant identity provider (Azure AD, Cognito, Google, etc.).
    """

    def __init__(self, wsgi_app):
        self.app = wsgi_app
        self._jwks_cache = None
        self._jwks_fetched_at = 0
        self._jwks_ttl = 3600  # re-fetch public keys every hour

    def _get_jwks(self):
        now = time.monotonic()
        if self._jwks_cache is None or (now - self._jwks_fetched_at) > self._jwks_ttl:
            with urllib.request.urlopen(settings.JWT_JWKS_URI, timeout=5) as resp:
                self._jwks_cache = json.loads(resp.read())
            self._jwks_fetched_at = now
        return self._jwks_cache

    def _unauthorized(self, start_response, reason='Unauthorized'):
        body = json.dumps({'errors': [{'message': reason}]}).encode()
        start_response('401 Unauthorized', [
            ('Content-Type', 'application/json'),
            ('Content-Length', str(len(body))),
            ('WWW-Authenticate', 'Bearer'),
        ])
        return [body]

    def __call__(self, environ, start_response):
        if not settings.JWT_ENABLED:
            return self.app(environ, start_response)

        auth_header = environ.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return self._unauthorized(start_response, 'Missing Bearer token')

        token = auth_header[len('Bearer '):]
        try:
            jwks = self._get_jwks()
            claims = jwt.decode(
                token,
                jwks,
                algorithms=[settings.JWT_ALGORITHM],
                audience=settings.JWT_AUDIENCE,
                issuer=settings.JWT_ISSUER,
                options={'leeway': settings.JWT_LEEWAY_SECONDS},
            )
        except JWTError as err:
            log.warning('JWT validation failed: %s', err)
            return self._unauthorized(start_response, 'Invalid or expired token')

        # Optionally forward claims to Flask via environ for downstream use
        environ['jwt.claims'] = claims
        return self.app(environ, start_response)
```

---

## 4. Wire it into the middleware stack in `run_server()`

In `svc_cherrypy.py` `run_server()`, the current stack is built inside-out. JWT validation should be outermost so unauthenticated requests never reach CORS or Flask:

```python
# Current inner-to-outer wrapping order:
wsgi_app = CorsMiddleware(app)
wsgi_app = SecurityHeadersMiddleware(wsgi_app)
wsgi_app = JWTAuthMiddleware(wsgi_app)   # <-- add here, outermost auth gate
wsgi_app = WSGILogger(wsgi_app, [StreamHandler()], ApacheFormatter())
```

---

## 5. Local / Development Mode (HS256 + shared secret)

For testing against the sample Northwind database without a real identity provider, use HS256 (symmetric HMAC) with a locally-generated secret. No JWKS URI, no external service, no network calls — just a shared secret in the INI file that is encrypted at rest by `cryptoconfigparser` like `DB_PASSWORD`.

### INI configuration

```ini
[JWT]
JWT_ENABLED = True
JWT_ALGORITHM = HS256
JWT_AUDIENCE = grapinator-dev
JWT_ISSUER = grapinator-local
JWT_LOCAL_SECRET = some-long-random-dev-secret-change-me
JWT_LEEWAY_SECONDS = 60
```

`JWT_JWKS_URI` is omitted entirely — the middleware detects HS256 and uses the local secret instead.

### Middleware change — branch on algorithm

The `JWTAuthMiddleware._get_jwks()` method is replaced with a `_get_key()` helper that returns the right key material based on the configured algorithm:

```python
def _get_key(self):
    if settings.JWT_ALGORITHM.startswith('HS'):
        # Symmetric: use the local secret directly — no network call needed
        return settings.JWT_LOCAL_SECRET
    else:
        # Asymmetric (RS256, ES256, etc.): fetch public keys from JWKS URI
        return self._get_jwks()
```

And in `__call__`:

```python
claims = jwt.decode(
    token,
    self._get_key(),
    algorithms=[settings.JWT_ALGORITHM],
    audience=settings.JWT_AUDIENCE,
    issuer=settings.JWT_ISSUER,
    options={'leeway': settings.JWT_LEEWAY_SECONDS},
)
```

### Minting test tokens locally

Any standard JWT tool works. Using PyJWT from the command line:

```bash
pip install pyjwt
python -c "
import jwt, time
print(jwt.encode({
    'sub': 'dev-user',
    'aud': 'grapinator-dev',
    'iss': 'grapinator-local',
    'iat': int(time.time()),
    'exp': int(time.time()) + 3600,
}, 'some-long-random-dev-secret-change-me', algorithm='HS256'))
"
```

Or paste the secret into [jwt.io](https://jwt.io) and build a token interactively in the browser.

Pass the resulting token in requests:

```bash
curl -H "Authorization: Bearer <token>" https://localhost:8443/northwind/gql \
     -d '{"query": "{ employees { firstName lastName } }"}'
```

### Switching from dev to production

The only change is the INI file — no code changes:

| Setting | Local / Dev | Production (Azure, Cognito, Google…) |
|---|---|---|
| `JWT_ALGORITHM` | `HS256` | `RS256` |
| `JWT_LOCAL_SECRET` | shared secret | *(omit)* |
| `JWT_JWKS_URI` | *(omit)* | provider JWKS endpoint |
| `JWT_ISSUER` | `grapinator-local` | provider issuer URL |
| `JWT_AUDIENCE` | `grapinator-dev` | registered app/client ID |

> **Note:** Never use HS256 with a shared secret in production. It cannot be rotated independently per client and the secret must be kept on both sides of the wire.

---

## 6. Dependency

Add `python-jose[cryptography]` to `setup.cfg` / `pyproject.toml` alongside the existing dependencies. It handles RS256/RS384/RS512, key ID (`kid`) resolution from JWKS, and claim validation in a single `jwt.decode()` call — the same library works identically regardless of which provider issued the token.

---

## Key Design Points

- **`JWT_ENABLED = False`** means the entire section is optional; existing deployments need zero changes.
- **JWKS caching** avoids a remote call on every request while still rotating keys hourly — important because providers rotate keys on their own schedule.
- **`environ['jwt.claims']`** passes the validated claims into Flask for any downstream authorization logic without coupling Flask to the JWT library directly.
- Because JWKS URI + issuer + audience fully describe any OIDC-compliant provider, swapping from Azure AD to Cognito to Google is purely a config-file change — no code changes required.
