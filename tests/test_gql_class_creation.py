import unittest
from . import context
from datetime import datetime
from grapinator import settings, log, schema_settings
from grapinator.schema import *

class TestStringMethods(unittest.TestCase):

    def test_gql(self):
        for c in schema_settings.get_gql_classes():
            self.assertTrue(
                issubclass(globals()[c['gql_class']], SQLAlchemyObjectType)
                ,"test_gql failed!"
                )

    def test_gql_has_relay_node_interface(self):
        """Each dynamically-created GQL class must expose the relay.Node interface."""
        for c in schema_settings.get_gql_classes():
            gql_cls = globals()[c['gql_class']]
            iface_names = [i.__name__ for i in gql_cls._meta.interfaces]
            self.assertIn('Node', iface_names, f"{c['gql_class']} missing relay.Node interface")

    def test_gql_deprecation_reason_on_fields(self):
        """Fields with a deprecation_reason in the schema descriptor must have
        that reason exposed on the mounted Graphene field of the generated type.
        Fields without one must have deprecation_reason as None."""
        for c in schema_settings.get_gql_classes():
            gql_cls = globals()[c['gql_class']]
            gql_fields = gql_cls._meta.fields
            for col in c['gql_columns']:
                if col['ishidden'] or col['isresolver']:
                    continue
                field_name = col['name']
                self.assertIn(field_name, gql_fields,
                    f"{c['gql_class']}.{field_name}: field missing from generated type")
                actual = gql_fields[field_name].deprecation_reason
                expected = col['deprecation_reason']
                self.assertEqual(actual, expected,
                    f"{c['gql_class']}.{field_name}: expected deprecation_reason={expected!r}, got {actual!r}")
