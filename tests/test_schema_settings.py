import os
import tempfile
import unittest
from . import context
from datetime import datetime
from grapinator import settings, log, schema_settings
from grapinator.settings import SchemaSettings


# Minimal schema with one deprecated and one non-deprecated column, so the
# deprecation_reason parsing branch runs (Northwind defines no deprecations).
_DEPRECATION_SCHEMA = """[
    {
        'GQL_CLASS_NAME': 'Widgets'
        ,'GQL_CONN_QUERY_NAME': 'widgets'
        ,'DB_CLASS_NAME': 'db_Widgets'
        ,'DB_TABLE_NAME': 'Widgets'
        ,'DB_TABLE_PK': 'WidgetID'
        ,'DB_DEFAULT_SORT_COL': 'WidgetID'
        ,'FIELDS': [
            {
                'gql_col_name': 'widget_id'
                ,'gql_type': graphene.Int
                ,'db_col_name': 'WidgetID'
                ,'db_type': Integer
            },
            {
                'gql_col_name': 'old_code'
                ,'gql_type': graphene.String
                ,'gql_deprecation_reason': 'Use widget_id instead.'
                ,'db_col_name': 'OldCode'
                ,'db_type': String
            },
            {
                'gql_col_name': 'blank_reason'
                ,'gql_type': graphene.String
                ,'gql_deprecation_reason': ''
                ,'db_col_name': 'BlankReason'
                ,'db_type': String
            },
        ]
        ,'RELATIONSHIPS': []
    }
]"""


class TestStringMethods(unittest.TestCase):

    sb = schema_settings

    def _raw_entities(self):
        """Schema dictionary entries keyed by DB class name, as parsed from the file."""
        return {row['DB_CLASS_NAME']: row for row in self.sb._schema_dict}

    def test_gqlschemabuilder(self):
        self.assertTrue(self.sb, "test_gqlschemabuilder: empty sb!")

    def test_get_db_classes(self):
        dict_list = self.sb.get_db_classes()
        for r in dict_list:
            self.assertTrue('db_class' in r, "test_get_db_classes: failed for db_class!")
            self.assertTrue('db_pk' in r, "test_get_db_classes: failed for db_pk!")
            self.assertTrue('db_table' in r, "test_get_db_classes: failed for db_table!")
            self.assertTrue('db_columns' in r, "test_get_db_classes: failed for db_columns!")
            self.assertTrue(len(r['db_columns']) > 0, "test_get_db_classes: failed for db_columns size!")
        raw = self._raw_entities()
        self.assertEqual([r['db_class'] for r in dict_list], list(raw))
        for r in dict_list:
            row = raw[r['db_class']]
            expected = [f['gql_col_name'] for f in row['FIELDS'] if f['db_col_name']]
            self.assertEqual([c['name'] for c in r['db_columns']], expected,
                f"test_get_db_classes: wrong db_columns for {r['db_class']}!")
            self.assertEqual(r['db_table'], row['DB_TABLE_NAME'])
            self.assertEqual(r['db_pk'], row['DB_TABLE_PK'])

    def test_get_gql_classes(self):
        dict_list = self.sb.get_gql_classes()
        for r in dict_list:
            self.assertTrue('gql_class' in r, "test_get_gql_classes: failed for gql_class!")
            self.assertTrue('gql_conn_query_name' in r, "test_get_gql_classes: failed for gql_conn_query_name!")
            self.assertTrue('gql_db_class' in r, "test_get_gql_classes: failed for gql_db_class!")
            self.assertTrue('gql_db_default_sort_col' in r, "test_get_gql_classes: failed for gql_db_default_sort_col!")
            self.assertTrue('gql_columns' in r, "test_get_gql_classes: failed for gql_columns!")
            self.assertTrue(len(r['gql_columns']) > 0, "test_get_gql_classes: failed for gql_columns size!")
        raw = self._raw_entities()
        self.assertEqual([r['gql_db_class'] for r in dict_list], list(raw))
        for r in dict_list:
            row = raw[r['gql_db_class']]
            self.assertEqual(r['gql_class'], row['GQL_CLASS_NAME'])
            self.assertEqual(r['gql_conn_query_name'], row['GQL_CONN_QUERY_NAME'])
            self.assertEqual(r['gql_db_default_sort_col'], row['DB_DEFAULT_SORT_COL'])
            self.assertEqual([c['name'] for c in r['gql_columns']],
                             [f['gql_col_name'] for f in row['FIELDS']],
                f"test_get_gql_classes: wrong gql_columns for {r['gql_class']}!")

    def test_deprecation_reason_parsed(self):
        """Columns with gql_deprecation_reason in the schema dict must have
        deprecation_reason set to a non-empty string in the parsed descriptor.
        Columns without it must have deprecation_reason as None."""
        for cls in self.sb.get_gql_classes():
            for col in cls['gql_columns']:
                self.assertIn('deprecation_reason', col,
                    f"{cls['gql_class']}.{col['name']}: deprecation_reason key missing from descriptor")
                if col['deprecation_reason'] is not None:
                    self.assertIsInstance(col['deprecation_reason'], str,
                        f"{cls['gql_class']}.{col['name']}: deprecation_reason must be a string")
                    self.assertTrue(len(col['deprecation_reason']) > 0,
                        f"{cls['gql_class']}.{col['name']}: deprecation_reason must not be empty")
        raw = self._raw_entities()
        for cls in self.sb.get_gql_classes():
            fields = {f['gql_col_name']: f for f in raw[cls['gql_db_class']]['FIELDS']}
            for col in cls['gql_columns']:
                expected = fields[col['name']].get('gql_deprecation_reason') or None
                self.assertEqual(col['deprecation_reason'], expected,
                    f"{cls['gql_class']}.{col['name']}: wrong deprecation_reason")

    def test_deprecation_reason_values_from_schema_file(self):
        """A set reason is copied verbatim; absent or blank reasons become None."""
        with tempfile.NamedTemporaryFile('w', suffix='.dct', delete=False) as f:
            f.write(_DEPRECATION_SCHEMA)
        self.addCleanup(os.remove, f.name)
        columns = {
            col['name']: col['deprecation_reason']
            for col in SchemaSettings(schema_file=f.name).get_gql_classes()[0]['gql_columns']
        }
        self.assertEqual(columns, {
            'widget_id': None,
            'old_code': 'Use widget_id instead.',
            'blank_reason': None,
        })
