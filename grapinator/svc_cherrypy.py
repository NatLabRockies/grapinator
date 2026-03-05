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

def run_server():
    # Enable WSGI access logging 
    handlers = [StreamHandler(), ]
    app_logged = WSGILogger(app, handlers, ApacheFormatter())

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
