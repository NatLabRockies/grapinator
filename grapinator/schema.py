from sqlalchemy import and_, or_, desc, asc
import graphene
from graphene import relay
from graphene_sqlalchemy import SQLAlchemyObjectType, SQLAlchemyConnectionField
import datetime
from grapinator import log, schema_settings
from grapinator.model import *

def gql_class_constructor(clazz_name, db_clazz_name, clazz_attrs, default_sort_col):
    include_fields = {}
    exclude_fields = ()
    for attr in clazz_attrs:
        if attr['isresolver']:
            attr_name = attr['name']
            resolver_name = "resolve_{}".format(attr_name)
            include_fields[attr_name] = attr['type'](attr['type_args'], description=attr['desc'])
            include_fields[resolver_name] = attr['resolver_func']
        elif attr['ishidden']:
            exclude_fields += (attr['name'],)
        else:
            include_fields[attr['name']] = attr['type'](attr['type_args'], description=attr['desc'])

    gql_attrs = {
        'Meta': type('Meta', (), {
            'model': globals()[db_clazz_name]
            ,'interfaces': (relay.Node, )
            ,'exclude_fields': exclude_fields
            })
        ,**include_fields
        ,'matches': graphene.String(description='contains, exact, regex, re, startswith, sw, endswith, ew, eq, gt, gte, lt, lte, ne', default_value='contains')
        ,'sort_by': graphene.String(description='Field to sort by.', default_value=default_sort_col)
        ,'logic': graphene.String(description='and, or', default_value='and')
        ,'sort_dir': graphene.String(description='asc, desc', default_value='asc')
        
    }
    return type(str(clazz_name), (SQLAlchemyObjectType,), gql_attrs)

def gql_connection_class_constructor(clazz_name, gql_clazz_name):
    gql_attrs = {
        'Meta': type('Meta', (), {'node': gql_clazz_name})
        }
    return type(str(clazz_name), (relay.Connection,), gql_attrs)

class MyConnectionField(SQLAlchemyConnectionField):
    RELAY_ARGS = ['first', 'last', 'before', 'after']

    @classmethod
    def get_query(cls, model, info, sort=None, filter=None, **args):
        # In graphene 3.x, unset fields are passed as None rather than being
        # absent from args. Pop our custom args first (treating None as unset).
        matches  = args.pop('matches', None)
        operator = args.pop('logic', None)
        sort_by_name = args.pop('sort_by', None)
        sort_dir = args.pop('sort_dir', None)

        # Build ORDER BY only when a sort column is actually provided/non-None.
        sort_clause = None
        if sort_by_name:
            sort_col = getattr(model, sort_by_name)
            sort_clause = asc(sort_col) if sort_dir != 'desc' else desc(sort_col)

        # Let graphene-sqlalchemy 3.x handle its own sort/filter params.
        query = super(MyConnectionField, cls).get_query(
            model, info, sort=sort, filter=filter, **args
        )

        filter_conditions = []
        for field, value in args.items():
            # Skip relay pagination args and any field not supplied by the client
            # (graphene 3.x sends None for every declared-but-unset field).
            if field in cls.RELAY_ARGS or value is None:
                continue
            if matches in ('exact', 'eq'):
                filter_conditions.append(getattr(model, field) == value)
            elif matches in ('regex', 're'):
                filter_conditions.append(getattr(model, field).regexp_match(value))
            elif matches in ('startswith', 'sw'):
                filter_conditions.append(getattr(model, field).ilike(value + '%'))
            elif matches in ('endswith', 'ew'):
                filter_conditions.append(getattr(model, field).ilike('%' + value))
            elif matches == 'lt':
                filter_conditions.append(getattr(model, field) < value)
            elif matches == 'lte':
                filter_conditions.append(getattr(model, field) <= value)
            elif matches == 'gt':
                filter_conditions.append(getattr(model, field) > value)
            elif matches == 'gte':
                filter_conditions.append(getattr(model, field) >= value)
            elif matches == 'ne':
                filter_conditions.append(getattr(model, field) != value)
            elif isinstance(value, list):
                filter_conditions.append(getattr(model, field).in_(value))
            # Opinionated defaults: dates use >=, everything else uses ilike.
            elif isinstance(value, (datetime.date, datetime.datetime)):
                filter_conditions.append(getattr(model, field) >= value)
            else:
                filter_conditions.append(getattr(model, field).ilike('%' + value + '%'))

        if filter_conditions:
            if operator == 'or':
                query = query.filter(or_(*filter_conditions))
            else:
                query = query.filter(and_(*filter_conditions))

        if sort_clause is not None:
            query = query.order_by(sort_clause)

        return query

# loop and dynamicaly create all the graphene classes necessary for the Query class
for clazz in schema_settings.get_gql_classes():
    # create the Graphene classes
    globals()[clazz['gql_class']] = gql_class_constructor(
        clazz['gql_class']
        ,clazz['gql_db_class']
        ,clazz['gql_columns']
        ,clazz['gql_db_default_sort_col']
        )

def _make_gql_query_fields(cols):
    gql_attrs = {}
    for row in cols:
        # Only allow queryable types. 
        # set optional 'gql_isqueryable': False in schema.dct to skip
        if row['isqueryable'] and row['ishidden'] is False and row['isresolver'] is False:
            gql_attrs[row['name']] = row['type'](row['type_args'] if row['type_args'] else None)
            #gql_attrs[row['name']] = row['type']()
    gql_attrs.update({
        'matches': graphene.String()
        ,'sort_by': graphene.String()
        ,'logic': graphene.String()
        ,'sort_dir': graphene.String()
        })
    return gql_attrs
    
# create the Graphene Query class
class Query(graphene.ObjectType):
    node = relay.Node.Field()

    for clazz in schema_settings.get_gql_classes():
        locals()[clazz['gql_conn_query_name']] = MyConnectionField(
            globals()[clazz['gql_class']]
            ,_make_gql_query_fields(clazz['gql_columns'])
            )

# create the gql schema
gql_schema = graphene.Schema(query=Query, auto_camelcase=False)
