# Reason for choosing cherrypy
# https://blog.appdynamics.com/engineering/a-performance-analysis-of-python-wsgi-servers-part-2/
#
# Flask application based on Quickstart
# http://flask.pocoo.org/docs/0.12/quickstart/
#
# CherryPy documentation for this
# http://docs.cherrypy.org/en/latest/deploy.html#wsgi-servers
# http://docs.cherrypy.org/en/latest/advanced.html#host-a-foreign-wsgi-application-in-cherrypy
# Install: pip install cherrypy paste
#
# This code is mostly plagiarized from here: 
# http://fgimian.github.io/blog/2012/12/08/setting-up-a-rock-solid-python-development-web-server/

import cherrypy
from requestlogger import WSGILogger, ApacheFormatter
from logging import StreamHandler
from flask import Flask

from grapinator import settings, log
from grapinator.app import app
from grapinator.model import db_session


class SecurityHeadersMiddleware:
    """WSGI middleware that injects security response headers and removes
    the Server disclosure header on every response."""

    def __init__(self, wsgi_app):
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
        def custom_start_response(status, response_headers, exc_info=None):
            # Strip server disclosure header
            response_headers = [(k, v) for k, v in response_headers
                                if k.lower() != 'server']
            # Inject security headers
            response_headers.extend(self._headers)
            return start_response(status, response_headers, exc_info)

        return self.app(environ, custom_start_response)


class CorsMiddleware:
    """WSGI middleware that handles CORS preflight requests and injects
    CORS response headers on every response, based on [CORS] settings."""

    def __init__(self, wsgi_app):
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
        if not settings.CORS_ENABLE:
            return self.app(environ, start_response)

        # Handle CORS preflight
        if environ.get('REQUEST_METHOD') == 'OPTIONS':
            headers = [('Content-Type', 'text/plain'), ('Content-Length', '0')]
            headers.extend(self._cors_headers)
            start_response('200 OK', headers)
            return [b'']

        def cors_start_response(status, response_headers, exc_info=None):
            response_headers.extend(self._cors_headers)
            return start_response(status, response_headers, exc_info)

        return self.app(environ, cors_start_response)


def run_server():
    # Enable WSGI access logging 
    handlers = [StreamHandler(), ]
    app_with_cors = CorsMiddleware(app)
    app_with_headers = SecurityHeadersMiddleware(app_with_cors)
    app_logged = WSGILogger(app_with_headers, handlers, ApacheFormatter())

    cherrypy.tree.graft(app_logged, '/')
    cherrypy.config.update({
        'server.socket_host': settings.WSGI_SOCKET_HOST,
        'server.socket_port': settings.WSGI_SOCKET_PORT,
        'engine.autoreload.on': False,
        'log.screen': True,
        'server.ssl_module': 'builtin',
        'server.ssl_certificate': settings.WSGI_SSL_CERT,
        'server.ssl_private_key': settings.WSGI_SSL_PRIVKEY,
        })
    # Start the CherryPy WSGI web server
    cherrypy.engine.start()
    cherrypy.engine.block()

if __name__ == '__main__':
    run_server()
