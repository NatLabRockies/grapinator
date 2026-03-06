import unittest
from . import context
from datetime import datetime
from grapinator import settings, log, schema_settings

class TestStringMethods(unittest.TestCase):

    sb = schema_settings

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

    def test_get_gql_classes(self):
        dict_list = self.sb.get_gql_classes()
        for r in dict_list:
            self.assertTrue('gql_class' in r, "test_get_gql_classes: failed for gql_class!")
            self.assertTrue('gql_conn_query_name' in r, "test_get_gql_classes: failed for gql_conn_query_name!")
            self.assertTrue('gql_db_class' in r, "test_get_gql_classes: failed for gql_db_class!")
            self.assertTrue('gql_db_default_sort_col' in r, "test_get_gql_classes: failed for gql_db_default_sort_col!")
            self.assertTrue('gql_columns' in r, "test_get_gql_classes: failed for gql_columns!")
            self.assertTrue(len(r['gql_columns']) > 0, "test_get_gql_classes: failed for gql_columns size!")
