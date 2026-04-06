# Grapinator RBAC Design Discussion
*Date: April 2, 2026*

---

## Q: Is it possible to modify this code to use role based access for masking access to individual fields within the graphql schema?

Yes, it's possible, and the existing code has several natural hooks for it. Here are the two viable approaches:

---

### Approach 1: Runtime resolver masking (recommended)

This works **without** changing the schema structure. A role-aware resolver is injected per field, returning `None` for unauthorized callers. The schema stays the same for all roles; sensitive values are just blanked at query time.

**Where to hook in:**

In `gql_class_constructor` (`schema.py`), each field already has its resolver injected via `include_fields[resolver_name]`. You'd add a wrapper that checks the caller's role before returning the real value:

```python
def make_role_aware_resolver(field_name, allowed_roles):
    def resolver(root, info):
        user_roles = get_roles_from_request(info.context)  # see below
        if not user_roles.intersection(allowed_roles):
            return None  # or raise graphql.GraphQLError("Forbidden")
        return getattr(root, field_name)
    return resolver
```

`info.context` in Graphene is the Flask `request` object, so `info.context.headers` gives you whatever auth token/header your identity provider supplies.

**Schema file addition** — each field in `schema.dct` would get an optional `gql_roles` key:

```python
{
    'gql_col_name': 'birth_date',
    'gql_type': graphene.DateTime,
    'gql_description': 'Employee birth date.',
    'gql_roles': ['hr_admin', 'manager'],   # <-- new
    ...
}
```

`SchemaSettings` (in `settings.py`) already parses each field dict; it would just pass `gql_roles` through alongside `ishidden`.

---

### Approach 2: Schema-per-role (static, full hiding)

A more aggressive option: build **separate** `graphene.Schema` instances at startup — one per role group — where restricted fields are excluded entirely (like `ishidden` does today). The Flask route in `app.py` would select the right schema based on the request's role before dispatching.

This is stronger (fields don't even appear in introspection for restricted users) but significantly more complex at startup and cache-unfriendly.

---

### Key integration points

| Concern | Location | Notes |
|---|---|---|
| Role extraction | `app.py` or a middleware | Read JWT/header, attach roles to Flask `g` or pass via `context` |
| `gql_roles` parsing | `settings.py` `SchemaSettings` | Add `gql_roles` to the field descriptor dict |
| Field guard | `schema.py` `gql_class_constructor` | Wrap resolver when `gql_roles` is present |
| `FixedGraphQLView` | `app.py` | Override `get_context()` to inject roles into `info.context` |

---

### `FixedGraphQLView` context injection

`graphql-server`'s `GraphQLView` accepts a `get_context` callable. You'd override it so roles are available to every resolver:

```python
class FixedGraphQLView(GraphQLView):
    ...
    def get_context(self):
        ctx = super().get_context()
        ctx['user_roles'] = extract_roles(request)  # your auth logic
        return ctx
```

Then in resolvers: `roles = info.context.get('user_roles', set())`.

---

### Summary

Approach 1 (runtime resolver masking) is the least invasive path: it touches `schema.dct` (add `gql_roles`), `settings.py` (pass it through), `schema.py` (wrap resolver), and `app.py` (inject context). No new abstractions are needed and the change is localized to the existing field-processing pipeline that already handles `ishidden` and `isresolver`.

---

## Q: Using option 1, how would the RBAC be invoked as the user calling the service?

### Current state: no authentication

Looking at `grapinator.ini`, `app.py`, and `svc_cherrypy.py`, there is currently **no authentication layer** — the service is open to anyone who can reach it. Before RBAC can work, you need a way for a caller to assert their identity. There are two practical choices:

---

### Option A: API Key / Bearer Token in a request header (simplest)

The caller passes a token with every request:

```
POST /northwind/gql
Authorization: Bearer <token>
Content-Type: application/json

{ "query": "{ employees { edges { node { first_name birth_date } } } }" }
```

Or with curl:
```bash
curl -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"query":"{ employees { edges { node { first_name } } } }"}' \
     https://localhost:8443/northwind/gql
```

The `FixedGraphQLView` in `app.py` would override `get_context()` to decode the token and extract roles:

```python
class FixedGraphQLView(GraphQLView):
    ...
    def get_context(self):
        ctx = super().get_context()
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        ctx['user_roles'] = decode_token_roles(token)   # your token validation
        return ctx
```

---

### Option B: HTTP Basic Auth (if using a directory/LDAP backend)

```bash
curl -u username:password \
     -H "Content-Type: application/json" \
     -d '{"query":"..."}' \
     https://localhost:8443/northwind/gql
```

Same hook — read `request.authorization` instead of `request.headers`.

---

### Where your token validation logic lives

The `decode_token_roles()` function would do one of:

| Scenario | Implementation |
|---|---|
| **JWT** (e.g. Azure AD, Keycloak) | Verify signature with `PyJWT`, extract `roles` claim from payload |
| **Opaque API key** | Look up key in a `roles` table in the same database already used by the app |
| **LDAP/AD group membership** | Call `ldap3` or similar to resolve group → role mapping |
| **Static dev config** | A dict in the INI file mapping key → roles (for development only) |

---

### What the caller experiences with field masking

Given a schema where `birth_date` requires role `hr_admin`:

**Caller WITH the `hr_admin` role:**
```graphql
{ employees { edges { node { first_name birth_date } } } }
# → birth_date: "1968-12-08"
```

**Caller WITHOUT the role:**
```graphql
{ employees { edges { node { first_name birth_date } } } }
# → birth_date: null
```

The field is still present in the schema (callers can ask for it), but the resolver silently returns `null`. If you'd prefer the caller gets an explicit error instead, the resolver can raise a `GraphQLError("Access denied")` — this is a design choice.

---

### Existing infrastructure to be aware of

- **CORS** in `svc_cherrypy.py` already allows some headers — you'd need to add `Authorization` to `CORS_ALLOW_HEADERS` in `grapinator.ini` (currently only `Content-Type, Accept` etc. are listed).
- The `CORS_SUPPORTS_CREDENTIALS = False` / `CORS_SEND_WILDCARD = True` combination in `grapinator.ini` is fine for API key headers, but if you switch to cookie-based auth you'd need to flip those two settings.
- TLS (`WSGI_SSL_CERT`/`WSGI_SSL_PRIVKEY`) is optional in the current config — **it should be enabled in any deployment that passes credentials**, since bearer tokens over plain HTTP are trivially stolen.
