"""Regression test: CherryPy must be fully removed from the grapinator package.

After 2.1.12 the WSGI server is Gunicorn, and CherryPy must not leak back
into the codebase via stray imports.  This test walks every ``.py`` file
under ``grapinator/`` and asserts ``cherrypy`` does not appear in any
``import`` statement.
"""

import os
import re
import unittest
from pathlib import Path

from . import context  # noqa: F401  -- adds project root to sys.path

_PKG_ROOT = Path(__file__).resolve().parent.parent / 'grapinator'

# Match ``import cherrypy`` and ``from cherrypy.something import ...``.
# Allow whitespace and submodule paths after the bareword.
_CHERRYPY_RE = re.compile(
    r'^\s*(?:import\s+cherrypy(?:\s|\.|$)|from\s+cherrypy(?:\.|\s))',
    re.MULTILINE,
)


class TestNoCherryPyImports(unittest.TestCase):
    """No grapinator source file may import the cherrypy package."""

    def test_no_cherrypy_imports_in_package(self):
        offenders = []
        for root, _, files in os.walk(_PKG_ROOT):
            for name in files:
                if not name.endswith('.py'):
                    continue
                path = Path(root) / name
                text = path.read_text(encoding='utf-8')
                if _CHERRYPY_RE.search(text):
                    offenders.append(str(path.relative_to(_PKG_ROOT.parent)))
        self.assertEqual(
            offenders, [],
            f'CherryPy imports must be removed; found in: {offenders}',
        )

    def test_no_svc_cherrypy_module(self):
        """The CherryPy entrypoint module must no longer exist."""
        self.assertFalse(
            (_PKG_ROOT / 'svc_cherrypy.py').exists(),
            'grapinator/svc_cherrypy.py was removed in 2.1.12 but is back',
        )


if __name__ == '__main__':
    unittest.main()
