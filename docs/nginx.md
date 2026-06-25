# Nginx reverse-proxy guide

In the 2.1.12 topology Nginx sits in front of Grapinator and is responsible
for **all** of the cross-cutting concerns that used to be embedded in the
CherryPy server:

* TLS termination (was `WSGI_SSL_CERT` / `WSGI_SSL_PRIVKEY`).
* Request body size enforcement (was `WSGI_MAX_REQUEST_BODY_SIZE`).
* Per-IP rate limiting (no previous Grapinator equivalent -- a gap closed
  by this release).
* Static error pages and a uniform 502/504 experience.

Grapinator itself only speaks plain HTTP to Nginx, on the
`WSGI_SOCKET_HOST:WSGI_SOCKET_PORT` pair defined in the ini file.

For the Gunicorn-side tunables (timeouts, keepalive, worker sizing) read
[`docs/gunicorn.md`](gunicorn.md).

---

## 1. Topology

```
+--------------+      HTTPS       +---------+   plain HTTP   +-------------------+
| Client (web) | ---------------> |  Nginx  | -------------> | Grapinator        |
+--------------+   TLS 1.2+ /     | (host A)|   keepalive    | (Docker, host B)  |
                   HTTP/2         +---------+                | Gunicorn :8443    |
                                                             +-------------------+
```

* Host A and host B may be the same machine, or separated by a private
  network segment / VPC.  The plain-HTTP leg is **never** internet-routable.
* Nginx and Grapinator communicate over a long-lived keepalive pool so
  per-request TCP handshakes are not paid for inside the trust boundary.

---

## 2. Recommended `nginx.conf` snippet

The block below is a tested starting point.  Substitute the certificate
paths, upstream host, and rate-limit values for your environment.

```nginx
# /etc/nginx/conf.d/grapinator.conf

# --- upstream pool: long-lived keepalive to Gunicorn -----------------------
upstream grapinator_upstream {
    # Replace 10.0.0.42 with the private IP of the Grapinator host.
    server 10.0.0.42:8443;

    # Keep up to 32 idle connections open per worker process.  Match this
    # to your peak concurrent in-flight requests divided by Nginx worker
    # count.
    keepalive 32;
}

# --- per-IP rate limit zone (60 req/min, 200 req burst) --------------------
limit_req_zone $binary_remote_addr zone=grapinator_per_ip:10m rate=60r/m;

server {
    listen 443 ssl http2;
    server_name grapinator.example.org;

    # --- TLS ----------------------------------------------------------------
    ssl_certificate     /etc/letsencrypt/live/grapinator.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/grapinator.example.org/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    # --- safety knobs -------------------------------------------------------
    client_max_body_size 1m;           # caps POSTed GraphQL queries; replaces WSGI_MAX_REQUEST_BODY_SIZE
    keepalive_timeout    75s;          # match GUNICORN_KEEPALIVE
    proxy_read_timeout   35s;          # MUST exceed GUNICORN_TIMEOUT (default 30 s)
    proxy_connect_timeout 5s;
    proxy_send_timeout   35s;

    # --- /sds/gql ----------------------------------------------------------
    location /sds/gql {
        limit_req zone=grapinator_per_ip burst=200 nodelay;

        proxy_pass         http://grapinator_upstream;

        # Required so Gunicorn / Flask see HTTPS metadata even though the
        # last hop is plain HTTP.
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_set_header   X-Forwarded-Host  $host;
    }

    # Optional health check shortcut.
    location = /healthz {
        proxy_pass http://grapinator_upstream/healthz;
        access_log off;
    }
}

# Force HTTPS for any caller that still hits port 80.
server {
    listen 80;
    server_name grapinator.example.org;
    return 301 https://$host$request_uri;
}
```

### Timeout interlock

The two `proxy_*_timeout` values **must** exceed
`GUNICORN_TIMEOUT`.  When a slow query trips the Gunicorn timeout the
worker is killed and the client receives a clean 502/504 with a useful
message; if Nginx times out first the client sees Nginx's generic
gateway-timeout page instead.

### `client_max_body_size`

Replaces `WSGI_MAX_REQUEST_BODY_SIZE` from earlier releases.  GraphQL
queries rarely exceed a few KB, so the 1 MB recommendation here is a
generous ceiling that still blocks accidental file uploads.

### Per-IP rate limiting

`limit_req_zone` lets you cap call volume without depending on
authentication.  Tune `rate=` and `burst=` against your observed traffic;
the values above (60 req/min sustained, 200-request burst) are a sensible
starting point for an internal-API workload.

---

## 3. Validating the change

1. **Syntax-check Nginx**: `nginx -t`
2. **Reload without dropping connections**: `nginx -s reload`
3. **Verify end-to-end**:
   ```sh
   curl -X POST https://grapinator.example.org/sds/gql \
        -H 'Content-Type: application/json' \
        -d '{"query":"{ __typename }"}'
   ```
   Expected response: `{"data":{"__typename":"Query"}}`
4. **Inspect log volume**.  Nginx's access log gives you per-IP traffic
   patterns and 4xx/5xx clusters that the Gunicorn-side logs cannot.

For the Gunicorn side of the same topology, continue to
[`docs/gunicorn.md`](gunicorn.md).
