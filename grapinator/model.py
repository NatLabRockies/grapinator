"""
model.py

Dynamically builds SQLAlchemy ORM classes from the schema configuration
defined in schema_settings.  At import time this module:

  1. Creates the SQLAlchemy engine and a scoped session bound to it.
  2. Establishes a declarative ``Base`` that all generated ORM classes inherit from.
  3. Calls :func:`orm_class_constructor` for every table defined in the schema
     dictionary and injects each resulting class into this module's global
     namespace so they can be imported via ``from grapinator.model import *``.

No direct database reflection is performed; the schema dictionary is the sole
source of table/column metadata.
"""

from sqlalchemy import (Column, DateTime, Integer, Numeric, String,
                        create_engine)
# declarative_base moved from sqlalchemy.ext.declarative to sqlalchemy.orm in SQLAlchemy 2.0
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import (
    scoped_session
    ,sessionmaker
    ,relationship
    ,synonym
)

from grapinator import settings, schema_settings
import logging

logger = logging.getLogger(__name__)

# convert_unicode parameter was removed in SQLAlchemy 2.0.
# pool_pre_ping=True ensures stale connections are recycled before use.
engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)
logger.info('Database engine created: %s', settings.DB_TYPE)

# Scoped session ties a single Session instance to the current thread/request
# context.  autocommit=False means callers must explicitly commit transactions.
db_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
    )

# No reflection against db tables — schema is defined entirely via the schema
# dictionary, keeping the app decoupled from live database introspection.
Base = declarative_base()
# Attach the scoped session's query property so ORM classes support
# Model.query shorthand (e.g. MyModel.query.filter_by(...)).
Base.query = db_session.query_property()

def orm_class_constructor(clazz_name, db_table, clazz_pk, clazz_attrs, clazz_relationships):
    """
    Dynamically create a SQLAlchemy ORM class mapped to *db_table*.

    Each entry in *clazz_attrs* becomes a ``Column`` on the mapped class,
    or a ``synonym`` when ``db_type == 'synonym'``.  Entries in
    *clazz_relationships* become SQLAlchemy ``relationship`` descriptors
    that wire up cross-table navigation.

    Reference: http://sparrigan.github.io/sql/sqla/2016/01/03/dynamic-tables.html

    :param clazz_name:           Name of the ORM class to create (string).
    :param db_table:             Database table name to map the class to.
    :param clazz_pk:             List of column names that form the primary key.
                                 At least one entry is required by SQLAlchemy.
    :param clazz_attrs:          List of column descriptor dicts, each with keys:
                                   ``name``        – attribute name on the class,
                                   ``db_col_name`` – physical column name in the DB,
                                   ``db_type``     – SQLAlchemy column type (or
                                                     ``'synonym'`` for aliases).
    :param clazz_relationships:  List of relationship descriptor dicts, each with
                                   ``name``       – attribute name on the class,
                                   ``class_name`` – target ORM class name (string),
                                   ``arguments``  – dict of kwargs forwarded to
                                                    ``relationship()``.
    :returns: Dynamically generated ORM class inheriting from ``Base``.
    """
    # Start with the mandatory SQLAlchemy table-name attribute.
    orm_attrs = {'__tablename__': db_table}

    # Map each column descriptor to a SQLAlchemy Column (or synonym alias).
    for col in clazz_attrs:
        if col['db_type'] == 'synonym':
            # synonym() creates an alias so a column can be accessed under
            # an alternative attribute name without duplicating the column.
            orm_attrs[col['name']] = synonym(col['db_col_name'])
        else:
            if col['db_col_name'] in clazz_pk:
                orm_attrs[col['name']] = Column(col['db_col_name'], col['db_type'], primary_key=True)
            else:
                orm_attrs[col['name']] = Column(col['db_col_name'], col['db_type'])

    # Add relationship descriptors that enable cross-table navigation via
    # SQLAlchemy's ORM join machinery.
    for col in clazz_relationships:
        orm_attrs[col['name']] = relationship(
            col['class_name']
            ,**col['arguments']
            )

    # type() with three arguments dynamically creates a new class whose name
    # is clazz_name, inherits from Base, and has the attributes we built above.
    return type(str(clazz_name), (Base,), orm_attrs)


# Iterate over every table defined in the schema dictionary and register the
# corresponding ORM class in this module's global namespace.  This makes them
# importable via ``from grapinator.model import *`` without listing each class
# explicitly, and keeps the code in sync with the schema automatically.
_orm_class_count = 0
for db_class in schema_settings.get_db_classes():
    globals()[db_class['db_class']] = orm_class_constructor(
        db_class['db_class']
        ,db_class['db_table']
        ,db_class['db_pk']
        ,db_class['db_columns']
        ,db_class['db_relationships']
        )
    logger.debug('ORM class registered: %s -> table %s', db_class['db_class'], db_class['db_table'])
    _orm_class_count += 1
logger.info('ORM registration complete: %d classes', _orm_class_count)