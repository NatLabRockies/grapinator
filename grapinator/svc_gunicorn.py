"""
svc_gunicorn.py

Gunicorn entrypoint for Grapinator.  Exposes a single module-level
``application`` callable that Gunicorn loads via the
``module:variable`` invocation::

    gunicorn --config /opt/grapinator/grapinator/resources/gunicorn.conf.py \\
             grapinator.svc_gunicorn:application

The Flask ``app`` is imported here and wrapped with the full middleware
stack (BearerAuth -> Cors -> SecurityHeaders -> WSGILogger) by
:func:`grapinator.middleware.build_wsgi_stack`.  Building the stack at
import time means every worker fork inherits an identical, fully-wired
application.
"""

import logging
import subprocess
import sys

from grapinator.app import app
from grapinator.middleware import build_wsgi_stack

logger = logging.getLogger(__name__)

# Module-level WSGI callable consumed by Gunicorn.
application = build_wsgi_stack(app)
logger.info('svc_gunicorn: WSGI stack assembled; application ready.')


_DEFAULT_CONFIG = '/opt/grapinator/grapinator/resources/gunicorn.conf.py'


def main(argv=None):
    """Smoke-check the bundled Gunicorn config without binding a socket.

    Spawns ``gunicorn --check-config <conf> grapinator.svc_gunicorn:application``
    and propagates its exit status.  Useful as a CI gate and as a
    container HEALTHCHECK during startup.
    """
    argv = list(argv) if argv is not None else sys.argv[1:]
    config = _DEFAULT_CONFIG
    if argv and argv[0] not in ('-h', '--help'):
        # Allow callers to override the config path positionally.
        config = argv[0]
    cmd = [
        'gunicorn',
        '--check-config',
        '--config', config,
        'grapinator.svc_gunicorn:application',
    ]
    return subprocess.call(cmd)


if __name__ == '__main__':
    sys.exit(main())
