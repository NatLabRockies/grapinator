"""Unit tests for grapinator.settings.Settings and SchemaSettings.

These tests import directly from grapinator.settings (and transitively from the
grapinator package), so GQLAPI_CRYPT_KEY must be present in the environment.  A
dummy value is set via os.environ.setdefault before any grapinator import so the
module-level initialisation in grapinator/__init__.py succeeds.
"""

import os
# Must be set before any grapinator import so __init__.py can bootstrap.
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import unittest
from unittest.mock import patch, MagicMock
from . import context  # noqa: F401 – adds project root to sys.path

import graphene
from sqlalchemy import Integer, String

from grapinator.settings import Settings, SchemaSettings


# ---------------------------------------------------------------------------
# A minimal schema dict used by SchemaSettings tests without touching the
# real schema.dct file on disk.
# ---------------------------------------------------------------------------
_MINIMAL_SCHEMA = [
    {
        'GQL_CLASS_NAME': 'TestItems',
        'GQL_CONN_QUERY_NAME': 'test_items',
        'DB_CLASS_NAME': 'db_TestItems',
        'DB_TABLE_NAME': 'TestItems',
        'DB_TABLE_PK': 'ItemID',
        'DB_DEFAULT_SORT_COL': 'ItemID',
        'FIELDS': [
            {
                'gql_col_name': 'item_id',
                'gql_type': graphene.Int,
                'gql_description': 'Item ID (PK).',
                'db_col_name': 'ItemID',
                'db_type': Integer,
            },
            {
                # intentionally omits all optional keys (gql_of_type,
                # gql_isqueryable, gql_ishidden, gql_isresolver,
                # gql_resolver_func) to exercise their default values.
                'gql_col_name': 'name',
                'gql_type': graphene.String,
                'gql_description': 'Item name.',
                'db_col_name': 'Name',
                'db_type': String,
            },
        ],
        'RELATIONSHIPS': [],
    }
]


# ---------------------------------------------------------------------------
# Settings error cases
# ---------------------------------------------------------------------------

class TestSettingsErrors(unittest.TestCase):

    def test_missing_config_file_raises_runtime_error(self):
        """Settings() without config_file must raise RuntimeError."""
        with self.assertRaises(RuntimeError):
            Settings()

    def test_missing_env_key_raises_runtime_error(self):
        """Settings raises RuntimeError when GQLAPI_CRYPT_KEY is absent."""
        env_without_key = {k: v for k, v in os.environ.items()
                           if k != 'GQLAPI_CRYPT_KEY'}
        with patch.dict('os.environ', env_without_key, clear=True):
            with self.assertRaises(RuntimeError):
                Settings(config_file='/resources/grapinator.ini')


# ---------------------------------------------------------------------------
# Settings — loaded values (uses the real grapinator.ini + dummy key)
# ---------------------------------------------------------------------------

class TestSettingsLoadedValues(unittest.TestCase):
    """Verify that the Settings object produced by __init__.py has sensible
    field types and that the SQLAlchemy URI is properly assembled.
    """

    @classmethod
    def setUpClass(cls):
        # Re-use the already-loaded settings singleton from the package init.
        from grapinator import settings
        cls.settings = settings

    def test_app_version_is_string(self):
        self.assertIsInstance(self.settings.APP_VERSION, str)
        self.assertTrue(len(self.settings.APP_VERSION) > 0)

    def test_flask_api_endpoint_starts_with_slash(self):
        self.assertTrue(self.settings.FLASK_API_ENDPOINT.startswith('/'))

    def test_sqlalchemy_uri_is_string(self):
        self.assertIsInstance(self.settings.SQLALCHEMY_DATABASE_URI, str)
        self.assertTrue(len(self.settings.SQLALCHEMY_DATABASE_URI) > 0)

    def test_sqlite_uri_has_no_credentials(self):
        """For SQLite the URI must not contain user:password@ credentials."""
        uri = self.settings.SQLALCHEMY_DATABASE_URI
        if 'sqlite' in uri:
            self.assertNotIn('@', uri)

    def test_sqlalchemy_track_modifications_is_bool(self):
        self.assertIsInstance(self.settings.SQLALCHEMY_TRACK_MODIFICATIONS, bool)

    def test_cors_settings_are_populated(self):
        self.assertIsNotNone(self.settings.CORS_EXPOSE_ORIGINS)
        self.assertIsNotNone(self.settings.CORS_ALLOW_METHODS)

    def test_http_security_headers_populated(self):
        self.assertIsNotNone(self.settings.HTTP_HEADERS_XFRAME)
        self.assertIsNotNone(self.settings.HTTP_HEADERS_XSS_PROTECTION)
        self.assertIsNotNone(self.settings.HTTP_HEADER_CACHE_CONTROL)


# ---------------------------------------------------------------------------
# SchemaSettings error cases
# ---------------------------------------------------------------------------

class TestSchemaSettingsErrors(unittest.TestCase):

    def test_missing_schema_file_kwarg_raises_type_error(self):
        """SchemaSettings() without schema_file must raise TypeError."""
        with self.assertRaises(TypeError):
            SchemaSettings()


# ---------------------------------------------------------------------------
# SchemaSettings — db_classes structure
# ---------------------------------------------------------------------------

class TestSchemaSettingsDbClasses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with patch.object(SchemaSettings, '_loadSchemaDict',
                          return_value=_MINIMAL_SCHEMA):
            cls.ss = SchemaSettings(schema_file='/fake/schema.dct')

    def test_db_classes_count_matches_schema(self):
        self.assertEqual(len(self.ss.get_db_classes()), len(_MINIMAL_SCHEMA))

    def test_db_class_required_keys_present(self):
        for cls_def in self.ss.get_db_classes():
            for key in ('db_class', 'db_table', 'db_pk', 'db_columns',
                        'db_relationships'):
                self.assertIn(key, cls_def,
                              f"key '{key}' missing from db_class dict")

    def test_db_class_name_mapped_correctly(self):
        cls_def = self.ss.get_db_classes()[0]
        self.assertEqual(cls_def['db_class'], 'db_TestItems')

    def test_db_table_name_mapped_correctly(self):
        cls_def = self.ss.get_db_classes()[0]
        self.assertEqual(cls_def['db_table'], 'TestItems')

    def test_db_pk_mapped_correctly(self):
        cls_def = self.ss.get_db_classes()[0]
        self.assertEqual(cls_def['db_pk'], 'ItemID')

    def test_db_columns_count_matches_fields(self):
        cls_def = self.ss.get_db_classes()[0]
        # db_columns includes only rows where db_col_name is truthy
        self.assertEqual(len(cls_def['db_columns']), 2)

    def test_db_column_has_name_and_db_col_name_and_db_type(self):
        col = self.ss.get_db_classes()[0]['db_columns'][0]
        self.assertIn('name', col)
        self.assertIn('db_col_name', col)
        self.assertIn('db_type', col)

    def test_db_relationships_empty_for_no_relationships(self):
        cls_def = self.ss.get_db_classes()[0]
        self.assertEqual(cls_def['db_relationships'], [])


# ---------------------------------------------------------------------------
# SchemaSettings — gql_classes structure
# ---------------------------------------------------------------------------

class TestSchemaSettingsGqlClasses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with patch.object(SchemaSettings, '_loadSchemaDict',
                          return_value=_MINIMAL_SCHEMA):
            cls.ss = SchemaSettings(schema_file='/fake/schema.dct')

    def test_gql_classes_count_matches_schema(self):
        self.assertEqual(len(self.ss.get_gql_classes()), len(_MINIMAL_SCHEMA))

    def test_gql_class_required_keys_present(self):
        for cls_def in self.ss.get_gql_classes():
            for key in ('gql_class', 'gql_conn_query_name', 'gql_db_class',
                        'gql_columns', 'gql_db_default_sort_col'):
                self.assertIn(key, cls_def,
                              f"key '{key}' missing from gql_class dict")

    def test_gql_class_name_mapped_correctly(self):
        cls_def = self.ss.get_gql_classes()[0]
        self.assertEqual(cls_def['gql_class'], 'TestItems')

    def test_gql_conn_query_name_mapped_correctly(self):
        cls_def = self.ss.get_gql_classes()[0]
        self.assertEqual(cls_def['gql_conn_query_name'], 'test_items')

    def test_gql_db_default_sort_col_mapped_correctly(self):
        cls_def = self.ss.get_gql_classes()[0]
        self.assertEqual(cls_def['gql_db_default_sort_col'], 'ItemID')

    def test_gql_column_optional_type_args_defaults_to_none(self):
        """gql_of_type absent → type_args defaults to None."""
        cols = self.ss.get_gql_classes()[0]['gql_columns']
        name_col = next(c for c in cols if c['name'] == 'name')
        self.assertIsNone(name_col['type_args'])

    def test_gql_column_optional_isqueryable_defaults_to_true(self):
        cols = self.ss.get_gql_classes()[0]['gql_columns']
        name_col = next(c for c in cols if c['name'] == 'name')
        self.assertTrue(name_col['isqueryable'])

    def test_gql_column_optional_ishidden_defaults_to_false(self):
        cols = self.ss.get_gql_classes()[0]['gql_columns']
        name_col = next(c for c in cols if c['name'] == 'name')
        self.assertFalse(name_col['ishidden'])

    def test_gql_column_optional_isresolver_defaults_to_false(self):
        cols = self.ss.get_gql_classes()[0]['gql_columns']
        name_col = next(c for c in cols if c['name'] == 'name')
        self.assertFalse(name_col['isresolver'])

    def test_gql_column_optional_resolver_func_defaults_to_none(self):
        cols = self.ss.get_gql_classes()[0]['gql_columns']
        name_col = next(c for c in cols if c['name'] == 'name')
        self.assertIsNone(name_col['resolver_func'])


if __name__ == '__main__':
    unittest.main()
