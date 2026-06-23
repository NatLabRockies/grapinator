"""Unit tests for grapinator.svc_gunicorn.

The module is the Gunicorn entrypoint: it must expose a callable
``application`` at import time and a CLI smoke-check helper.
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import unittest
from unittest.mock import patch

from . import context  # noqa: F401  -- adds project root to sys.path


class TestApplicationCallable(unittest.TestCase):
    """svc_gunicorn.application must be a callable WSGI app at import time."""

    def test_application_attribute_exists(self):
        from grapinator import svc_gunicorn
        self.assertTrue(hasattr(svc_gunicorn, 'application'))

    def test_application_is_callable(self):
        from grapinator import svc_gunicorn
        self.assertTrue(callable(svc_gunicorn.application))


class TestMainSmokeCheck(unittest.TestCase):
    """svc_gunicorn.main() must invoke ``gunicorn --check-config``."""

    def test_main_invokes_check_config(self):
        from grapinator import svc_gunicorn
        with patch('grapinator.svc_gunicorn.subprocess.call', return_value=0) as call_mock:
            rc = svc_gunicorn.main(['/some/conf.py'])
        self.assertEqual(rc, 0)
        cmd = call_mock.call_args[0][0]
        self.assertEqual(cmd[0], 'gunicorn')
        self.assertIn('--check-config', cmd)
        self.assertIn('--config', cmd)
        self.assertIn('/some/conf.py', cmd)
        self.assertIn('grapinator.svc_gunicorn:application', cmd)

    def test_main_uses_default_config_when_no_argv(self):
        from grapinator import svc_gunicorn
        with patch('grapinator.svc_gunicorn.subprocess.call', return_value=0) as call_mock:
            svc_gunicorn.main([])
        cmd = call_mock.call_args[0][0]
        self.assertIn(svc_gunicorn._DEFAULT_CONFIG, cmd)

    def test_main_propagates_nonzero_exit_code(self):
        from grapinator import svc_gunicorn
        with patch('grapinator.svc_gunicorn.subprocess.call', return_value=3):
            self.assertEqual(svc_gunicorn.main([]), 3)


if __name__ == '__main__':
    unittest.main()
