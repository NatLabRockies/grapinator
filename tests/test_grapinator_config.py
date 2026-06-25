"""Unit tests for the GRAPINATOR_CONFIG environment variable.

Verifies that grapinator/__init__.py correctly:
- Derives the resources directory from the directory containing GRAPINATOR_CONFIG.
- Loads logging.conf from that same directory.
- Falls back to the bundled package resources/ directory when GRAPINATOR_CONFIG
  is not set.
- Resolves a relative GQL_SCHEMA path against the resources directory.

Because grapinator/__init__.py executes at import time, each test reloads the
module under a patched environment to observe the resulting path values.
"""

import importlib
import os
import sys
import unittest
from os import path
from unittest.mock import patch, MagicMock

# Must be set before any grapinator import so __init__.py can bootstrap.
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

from . import context  # noqa: F401 – adds project root to sys.path


def _reload_init(env_overrides, gql_schema_value='schema.dct'):
    """Import (or reload) grapinator/__init__.py with a patched environment.

    *env_overrides* is merged into (not replacing) the real environment so that
    GQLAPI_CRYPT_KEY and other required keys remain present.

    *gql_schema_value* is the value returned for settings.GQL_SCHEMA before
    the relative-path resolution step runs.

    Both the import and the reload happen inside the patch context so that the
    module-level bootstrap code always runs with mocked Settings / SchemaSettings
    regardless of whether grapinator was previously imported.

    Returns the reloaded module.
    """
    mock_settings = MagicMock()
    mock_settings.FLASK_API_ENDPOINT = '/gql'
    mock_settings.DB_TYPE = 'sqlite+pysqlite'
    mock_settings.AUTH_MODE = 'off'
    mock_settings.GQL_SCHEMA = gql_schema_value

    mock_schema_settings = MagicMock()
    mock_schema_settings.get_gql_classes.return_value = []

    with patch.dict(os.environ, env_overrides, clear=False), \
         patch('logging.config.fileConfig'), \
         patch('grapinator.settings.Settings', return_value=mock_settings), \
         patch('grapinator.settings.SchemaSettings', return_value=mock_schema_settings):
        import grapinator  # noqa: PLC0415 — intentional: import inside patch context
        importlib.reload(grapinator)

    return sys.modules['grapinator']


class TestGrapinatorConfigDefault(unittest.TestCase):
    """GRAPINATOR_CONFIG not set — default to the bundled package ini file."""

    def setUp(self):
        self._saved = os.environ.pop('GRAPINATOR_CONFIG', None)

    def tearDown(self):
        if self._saved is not None:
            os.environ['GRAPINATOR_CONFIG'] = self._saved
        else:
            os.environ.pop('GRAPINATOR_CONFIG', None)
        # Reload grapinator with real settings to prevent mock pollution of
        # grapinator.schema_settings for tests that run after this class.
        import grapinator
        importlib.reload(grapinator)

    def test_default_config_file_is_bundled_ini(self):
        mod = _reload_init({})
        import grapinator as grap_module
        expected = path.join(
            path.abspath(path.dirname(grap_module.__file__)), 'resources', 'grapinator.ini'
        )
        self.assertEqual(mod._config_file, expected)

    def test_default_resources_dir_is_bundled_resources(self):
        mod = _reload_init({})
        import grapinator as grap_module
        expected_dir = path.join(
            path.abspath(path.dirname(grap_module.__file__)), 'resources'
        )
        self.assertEqual(mod._resources_dir, expected_dir)

    def test_default_logging_conf_in_same_dir_as_ini(self):
        mod = _reload_init({})
        self.assertEqual(mod._logging_conf_path,
                         path.join(mod._resources_dir, 'logging.conf'))


class TestGrapinatorConfigOverride(unittest.TestCase):
    """GRAPINATOR_CONFIG set to an absolute path — resources dir derived from it."""

    def setUp(self):
        self._saved = os.environ.pop('GRAPINATOR_CONFIG', None)

    def tearDown(self):
        if self._saved is not None:
            os.environ['GRAPINATOR_CONFIG'] = self._saved
        else:
            os.environ.pop('GRAPINATOR_CONFIG', None)
        # Reload grapinator with real settings to prevent mock pollution.
        import grapinator
        importlib.reload(grapinator)

    def test_resources_dir_is_dirname_of_config_file(self):
        mod = _reload_init({'GRAPINATOR_CONFIG': '/custom/resources/grapinator.ini'})
        self.assertEqual(mod._resources_dir, '/custom/resources')

    def test_config_file_matches_env_var(self):
        mod = _reload_init({'GRAPINATOR_CONFIG': '/custom/resources/grapinator.ini'})
        self.assertEqual(mod._config_file, '/custom/resources/grapinator.ini')

    def test_logging_conf_loaded_from_same_dir_as_ini(self):
        mod = _reload_init({'GRAPINATOR_CONFIG': '/custom/resources/grapinator.ini'})
        self.assertEqual(mod._logging_conf_path, '/custom/resources/logging.conf')

    def test_absolute_gql_schema_unchanged(self):
        mod = _reload_init(
            {'GRAPINATOR_CONFIG': '/custom/resources/grapinator.ini'},
            gql_schema_value='/custom/resources/schema.dct',
        )
        self.assertEqual(mod.settings.GQL_SCHEMA, '/custom/resources/schema.dct')

    def test_relative_gql_schema_resolved_against_resources_dir(self):
        mod = _reload_init(
            {'GRAPINATOR_CONFIG': '/custom/resources/grapinator.ini'},
            gql_schema_value='schema.dct',
        )
        self.assertEqual(mod.settings.GQL_SCHEMA, '/custom/resources/schema.dct')


if __name__ == '__main__':
    unittest.main()
