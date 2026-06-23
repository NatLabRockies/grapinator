"""
middleware.py

WSGI middleware classes used by the Grapinator application stack.

Both :class:`SecurityHeadersMiddleware` and :class:`CorsMiddleware` are plain
PEP 3333 WSGI middleware and are independent of the host server (CherryPy,
Gunicorn, Werkzeug development server, etc.). They were originally defined in
``grapinator/svc_cherrypy.py`` (removed in 2.1.12); they now live here so that
the new
``grapinator/svc_gunicorn.py`` entrypoint and the unit tests can import them
without dragging a server dependency along.

Stack order (outermost to innermost) is:

    WSGILogger
        SecurityHeadersMiddleware
            CorsMiddleware
                BearerAuthMiddleware (optional)
                    Flask app
"""

import logging

from grapinator import settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware:
    """
    WSGI middleware that injects HTTP security response headers and strips
    the ``Server`` disclosure header from every response.

    The headers injected are sourced from the ``[HTTP_HEADERS]`` section of
    the application configuration (via ``settings``) and typically include:

    - ``X-Frame-Options`` -- clickjacking protection.
    - ``X-XSS-Protection`` -- legacy XSS filter hint for older browsers.
    - ``Cache-Control`` -- caching directives for API responses.
    - ``X-Content-Type-Options`` -- MIME-type sniffing prevention.
    - ``Referrer-Policy`` -- controls the ``Referer`` header sent by clients.
    - ``Content-Security-Policy`` -- resource-loading restrictions.

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
            response_headers = [(k, v) for k, v in response_headers
                                if k.lower() != 'server']
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
    - When ``CORS_SEND_WILDCARD`` is ``True`` the
      ``Access-Control-Allow-Origin`` header is set to ``*``; otherwise the
      configured origin list is used.
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
        origin = '*' if settings.CORS_SEND_WILDCARD else settings.CORS_EXPOSE_ORIGINS
        self._cors_headers = [
            ('Access-Control-Allow-Origin',  origin),
            ('Access-Control-Allow-Methods', settings.CORS_ALLOW_METHODS),
            ('Access-Control-Allow-Headers', settings.CORS_ALLOW_HEADERS),
            ('Access-Control-Expose-Headers', settings.CORS_EXPOSE_HEADERS),
            ('Access-Control-Max-Age',       str(settings.CORS_HEADER_MAX_AGE)),
        ]
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
            return self.app(environ, start_response)

        if environ.get('REQUEST_METHOD') == 'OPTIONS':
            headers = [('Content-Type', 'text/plain'), ('Content-Length', '0')]
            headers.extend(self._cors_headers)
            start_response('200 OK', headers)
            return [b'']

        def cors_start_response(status, response_headers, exc_info=None):
            response_headers.extend(self._cors_headers)
            return start_response(status, response_headers, exc_info)

        return self.app(environ, cors_start_response)


def build_wsgi_stack(flask_app):
    """
    Assemble the standard Grapinator WSGI middleware stack around *flask_app*.

    The stack is built inside-out:

    1. ``BearerAuthMiddleware`` is wrapped around the Flask app when
       ``settings.AUTH_MODE != 'off'``.
    2. ``CorsMiddleware`` wraps the auth-decorated app (or the Flask app
       directly when auth is off).
    3. ``SecurityHeadersMiddleware`` wraps the CORS-decorated app.
    4. ``WSGILogger`` (Apache-format access log to stdout) wraps everything.

    The resulting callable is what the production WSGI server (Gunicorn) and
    the unit-test harness import and run.

    :param flask_app: The base Flask application to wrap.
    :returns: The fully wrapped WSGI callable.
    """
    from logging import StreamHandler
    from requestlogger import WSGILogger, ApacheFormatter
    from grapinator.auth import BearerAuthMiddleware

    inner = flask_app
    if settings.AUTH_MODE != 'off':
        inner = BearerAuthMiddleware(inner, settings)
        logger.debug('Middleware: BearerAuthMiddleware inserted (mode=%s)',
                     settings.AUTH_MODE)
    cors_wrapped = CorsMiddleware(inner)
    logger.debug('Middleware: CorsMiddleware (enabled=%s)', settings.CORS_ENABLE)
    headers_wrapped = SecurityHeadersMiddleware(cors_wrapped)
    logger.debug('Middleware: SecurityHeadersMiddleware')
    logged = WSGILogger(headers_wrapped, [StreamHandler()], ApacheFormatter())
    logger.debug('Middleware: WSGILogger (outermost)')
    return logged
