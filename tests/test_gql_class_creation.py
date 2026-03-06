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
