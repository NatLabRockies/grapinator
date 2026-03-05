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

# convert_unicode parameter was removed in SQLAlchemy 2.0
engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)
db_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
    )

# No reflection against db tables as we are hardcoding below.
Base = declarative_base()
# We will need this for querying
Base.query = db_session.query_property()

def orm_class_constructor(clazz_name, db_table, clazz_pk, clazz_attrs, clazz_relationships):
    """
    Create a ORM class dynamically. 
    See: http://sparrigan.github.io/sql/sqla/2016/01/03/dynamic-tables.html
        :param clazz_name: class name
        :param db_table: name of database table to map class
        :param clazz_pk: primary key for ORM object.  Required!
        :param clazz_attrs: dict of {column_name: SQLAlchemy type}
    Returns dynamically created ORM class
    """
    orm_attrs = {'__tablename__': db_table}
    for col in clazz_attrs:
        if col['db_type'] == 'synonym':
            orm_attrs[col['name']] = synonym(col['db_col_name'])
        else:
            if col['db_col_name'] in clazz_pk:
                orm_attrs[col['name']] = Column(col['db_col_name'], col['db_type'], primary_key=True)
            else:
                orm_attrs[col['name']] = Column(col['db_col_name'], col['db_type'])

    # this sets relationships for table joins in sqlalchemy
    for col in clazz_relationships:
        orm_attrs[col['name']] = relationship(
            col['class_name']
            ,**col['arguments']
            )

    return type(str(clazz_name), (Base,), orm_attrs)

for db_class in schema_settings.get_db_classes():
    globals()[db_class['db_class']] = orm_class_constructor(
        db_class['db_class']
        ,db_class['db_table']
        ,db_class['db_pk']
        ,db_class['db_columns']
        ,db_class['db_relationships']
        )