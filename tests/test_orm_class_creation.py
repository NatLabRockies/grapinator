import unittest
from . import context
from datetime import datetime
from grapinator import log, schema_settings
from grapinator.model import *

class TestStringMethods(unittest.TestCase):

    orm_classes = schema_settings.get_db_classes()

    def test_orm(self):
        for clz in self.orm_classes:
            self.assertTrue(issubclass(globals()[clz['db_class']], Base), f"test_orm failed for class: {clz['db_class']}!")
            self.assertTrue(hasattr(globals()[clz['db_class']], "__tablename__"), "test_orm failed!")
            self.assertTrue(hasattr(globals()[clz['db_class']], "metadata"), "test_orm failed!")
            self.assertTrue(hasattr(globals()[clz['db_class']], "query"), "test_orm failed!")