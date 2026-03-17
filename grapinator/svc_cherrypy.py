"""
svc_cherrypy.py

Production WSGI server for the Grapinator GraphQL API, hosted by CherryPy.

CherryPy was chosen for its strong multi-threaded performance characteristics
under typical API workloads.  See the benchmark that informed this decision:
https://blog.appdynamics.com/engineering/a-performance-analysis-of-python-wsgi-servers-part-2/

Architecture
~~~~~~~~~~~~
The Flask ``app`` from :mod:`grapinator.app` is wrapped in a WSGI middleware
stack before being grafted into the CherryPy server tree::

    CherryPy (transport)
        └── WSGILogger          (Apache-format access logging)
            └── SecurityHeadersMiddleware  (security response headers)
                └── CorsMiddleware        (CORS preflight + headers)
                    └── Flask app         (GraphQL endpoint)

The middleware layer order ensures that CORS headers are added first, then
security headers are appended on top, and every request/response pair is
logged last.

References
~~~~~~~~~~
- CherryPy WSGI deployment:
  http://docs.cherrypy.org/en/latest/deploy.html#wsgi-servers
- Hosting a foreign WSGI app in CherryPy:
  http://docs.cherrypy.org/en/latest/advanced.html#host-a-foreign-wsgi-application-in-cherrypy
"""

import cherrypy
from requestlogger import WSGILogger, ApacheFormatter
from logging import StreamHandler
from flask import Flask

from grapinator import settings, log
from grapinator.app import app
from grapinator.model import db_session


class SecurityHeadersMiddleware:
    """
    WSGI middleware that injects HTTP security response headers and strips
    the ``Server`` disclosure header from every response.

    The headers injected are sourced from the ``[HTTP_HEADERS]`` section of
    the application configuration (via ``settings``) and typically include:

    - ``X-Frame-Options`` — clickjacking protection.
    - ``X-XSS-Protection`` — legacy XSS filter hint for older browsers.
    - ``Cache-Control`` — caching directives for API responses.
    - ``X-Content-Type-Options`` — MIME-type sniffing prevention.
    - ``Referrer-Policy`` — controls the ``Referer`` header sent by clients.
    - ``Content-Security-Policy`` — resource-loading restrictions.

    Removing the ``Server`` header prevents the web server name and version
    from being disclosed to clients, reducing information leakage.
    """

    def __init__(self, wsgi_app):
        """
        Initialise the middleware and pre-build the security header list.

        Headers are built once at construction time rather than per-request
        to avoid repeated attribute lookups on the hot path.

        :param wsgi_app: The next WSGI application in the middleware stack.
        """
        self.app = wsgi_app
        self._headers = [
            ('X-Frame-Options',           settings.HTTP_HEADERS_XFRAME),
            ('X-XSS-Protection',          settings.HTTP_HEADERS_XSS_PROTECTION),
            ('Cache-Control',             settings.HTTP_HEADER_CACHE_CONTROL),
            ('X-Content-Type-Options',    settings.HTTP_HEADERS_X_CONTENT_TYPE_OPTIONS),
            ('Referrer-Policy',           settings.HTTP_HEADERS_REFERRER_POLICY),
            ('Content-Security-Policy',   settings.HTTP_HEADERS_CONTENT_SECURITY_POLICY),
        ]

    def __call__(self, environ, start_response):
        """
        Intercept ``start_response`` to modify headers before they are sent.

        :param environ:        PEP 3333 WSGI environment dict.
        :param start_response: WSGI ``start_response`` callable.
        :returns: Iterable of response body byte chunks from the wrapped app.
        """
        def custom_start_response(status, response_headers, exc_info=None):
            # Remove the Server header to avoid disclosing server software info.
            response_headers = [(k, v) for k, v in response_headers
                                if k.lower() != 'server']
            # Append all configured security headers to the response.
            response_headers.extend(self._headers)
            return start_response(status, response_headers, exc_info)

        return self.app(environ, custom_start_response)


class CorsMiddleware:
    """
    WSGI middleware that handles CORS preflight requests and injects
    Cross-Origin Resource Sharing headers on every response.

    Behaviour is controlled entirely by the ``[CORS]`` section of the
    application configuration (via ``settings``):

    - When ``CORS_ENABLE`` is ``False`` the middleware is a no-op and the
      wrapped application is called unchanged.
    - When ``CORS_SEND_WILDCARD`` is ``True`` the ``Access-Control-Allow-Origin``
      header is set to ``*``; otherwise the configured origin list is used.
    - ``OPTIONS`` preflight requests are short-circuited with a ``200 OK``
      response containing the CORS headers, so the underlying Flask app
      never needs to handle them.
    - When ``CORS_SUPPORTS_CREDENTIALS`` is ``True`` the
      ``Access-Control-Allow-Credentials: true`` header is included.
      Note that this requires a specific origin (not ``*``) per the CORS
      specification.
    """

    def __init__(self, wsgi_app):
        """
        Initialise the middleware and pre-build the CORS header list.

        CORS headers are assembled once at construction time so that the
        per-request ``__call__`` path performs no attribute lookups.

        :param wsgi_app: The next WSGI application in the middleware stack.
        """
        self.app = wsgi_app
        # Use wildcard origin '*' or the explicit configured origin list.
        origin = '*' if settings.CORS_SEND_WILDCARD else settings.CORS_EXPOSE_ORIGINS
        self._cors_headers = [
            ('Access-Control-Allow-Origin',  origin),
            ('Access-Control-Allow-Methods', settings.CORS_ALLOW_METHODS),
            ('Access-Control-Allow-Headers', settings.CORS_ALLOW_HEADERS),
            ('Access-Control-Expose-Headers', settings.CORS_EXPOSE_HEADERS),
            ('Access-Control-Max-Age',       str(settings.CORS_HEADER_MAX_AGE)),
        ]
        # Credentials support requires an explicit origin — only add this
        # header when the config explicitly enables it.
        if settings.CORS_SUPPORTS_CREDENTIALS:
            self._cors_headers.append(('Access-Control-Allow-Credentials', 'true'))

    def __call__(self, environ, start_response):
        """
        Process a WSGI request, adding CORS headers to the response.

        Short-circuits ``OPTIONS`` preflight requests with a ``200 OK`` so
        the wrapped application is only invoked for real requests.

        :param environ:        PEP 3333 WSGI environment dict.
        :param start_response: WSGI ``start_response`` callable.
        :returns: Iterable of response body byte chunks from the wrapped app,
                  or an empty body for preflight responses.
        """
        if not settings.CORS_ENABLE:
            # CORS is disabled — pass through to the next middleware unchanged.
            return self.app(environ, start_response)

        # Short-circuit OPTIONS preflight: return 200 with CORS headers only.
        if environ.get('REQUEST_METHOD') == 'OPTIONS':
            headers = [('Content-Type', 'text/plain'), ('Content-Length', '0')]
            headers.extend(self._cors_headers)
            start_response('200 OK', headers)
            return [b'']

        def cors_start_response(status, response_headers, exc_info=None):
            # Append CORS headers to every non-preflight response.
            response_headers.extend(self._cors_headers)
            return start_response(status, response_headers, exc_info)

        return self.app(environ, cors_start_response)


def run_server():
    """
    Configure and start the CherryPy production WSGI server.

    Assembles the WSGI middleware stack (CORS → security headers → access
    logging), grafts it onto the CherryPy tree at the root path, applies
    server configuration from ``settings``, then starts the engine and
    blocks until the process is stopped.

    The middleware stack is applied inside-out (innermost first):

    1. ``CorsMiddleware`` wraps the raw Flask ``app``.
    2. ``SecurityHeadersMiddleware`` wraps the CORS-decorated app.
    3. ``WSGILogger`` wraps the security-decorated app for Apache-format
       access logging to stdout via ``StreamHandler``.

    CherryPy's autoreload is disabled (``engine.autoreload.on: False``) since
    it is not appropriate for a production server.

    .. note::
        SSL is always configured from ``settings.WSGI_SSL_CERT`` /
        ``settings.WSGI_SSL_PRIVKEY``.  When these values are ``None``
        (i.e. the ``[WSGI]`` section omits the SSL options) CherryPy runs
        in plain HTTP mode.
    """
    # Build the middleware stack: CorsMiddleware → SecurityHeadersMiddleware
    # → WSGILogger (outermost, so every request is logged regardless of CORS
    # or security-header processing).
    handlers = [StreamHandler()]
    app_with_cors = CorsMiddleware(app)
    app_with_headers = SecurityHeadersMiddleware(app_with_cors)
    app_logged = WSGILogger(app_with_headers, handlers, ApacheFormatter())

    # Graft the decorated WSGI app into CherryPy's tree at the root path.
    cherrypy.tree.graft(app_logged, '/')
    cherrypy.config.update({
        'server.socket_host': settings.WSGI_SOCKET_HOST,
        'server.socket_port': settings.WSGI_SOCKET_PORT,
        'engine.autoreload.on': False,   # Not appropriate for production
        'log.screen': True,
        'server.ssl_module': 'builtin',
        'server.ssl_certificate': settings.WSGI_SSL_CERT,
        'server.ssl_private_key': settings.WSGI_SSL_PRIVKEY,
    })
    # Start the CherryPy WSGI engine and block until shutdown.
    cherrypy.engine.start()
    cherrypy.engine.block()

if __name__ == '__main__':
    run_server()
