"""
schema.py

Dynamically constructs the full Graphene / GraphQL schema from the table and
column definitions stored in ``schema_settings``.  At import time this module:

  1. Calls :func:`gql_class_constructor` for every entity defined in the schema
     dictionary, creating a ``SQLAlchemyObjectType`` subclass for each one and
     registering it in the module namespace.
  2. Builds the root :class:`Query` type by attaching a
     :class:`MyConnectionField` for every queryable entity.
  3. Compiles the final :data:`gql_schema` (``graphene.Schema``) that is served
     by the Flask application.

Filtering, sorting, and result paging are handled centrally in
:class:`MyConnectionField` so that every generated entity benefits from the
same query capabilities without any per-entity boilerplate.
"""

from sqlalchemy import and_, or_, desc, asc
import graphene
from graphene import relay
from graphene_sqlalchemy import SQLAlchemyObjectType, SQLAlchemyConnectionField
import datetime
from grapinator import log, schema_settings
from grapinator.model import *

def gql_class_constructor(clazz_name, db_clazz_name, clazz_attrs, default_sort_col):
    """
    Dynamically create a Graphene ``SQLAlchemyObjectType`` subclass for a
    single database entity.

    The generated class exposes each column in *clazz_attrs* as a Graphene
    field, wires up any custom resolver functions, hides fields marked as
    hidden, and attaches standard query-modifier fields (``matches``,
    ``sort_by``, ``logic``, ``sort_dir``) used by :class:`MyConnectionField`.

    :param clazz_name:       Name for the generated Graphene type (string).
    :param db_clazz_name:    Name of the SQLAlchemy ORM class (from
                             ``grapinator.model``) that backs this type.
    :param clazz_attrs:      List of column descriptor dicts produced by
                             ``schema_settings``.  Each dict contains at
                             minimum: ``name``, ``type``, ``type_args``,
                             ``desc``, ``isresolver``, ``ishidden``.
    :param default_sort_col: Default value for the ``sort_by`` field when the
                             client does not specify one.
    :returns: Dynamically generated ``SQLAlchemyObjectType`` subclass.
    """
    include_fields = {}
    exclude_fields = ()
    for attr in clazz_attrs:
        if attr['isresolver']:
            # Resolver fields are backed by a custom function rather than a
            # direct column value.  Both the field declaration and its
            # paired resolve_<name> method are injected into the class.
            attr_name = attr['name']
            resolver_name = "resolve_{}".format(attr_name)
            include_fields[attr_name] = attr['type'](attr['type_args'], description=attr['desc'])
            include_fields[resolver_name] = attr['resolver_func']
        elif attr['ishidden']:
            # Hidden fields are excluded from the GraphQL type entirely so
            # they cannot be queried or introspected by clients.
            exclude_fields += (attr['name'],)
        else:
            include_fields[attr['name']] = attr['type'](attr['type_args'], description=attr['desc'])

    gql_attrs = {
        # Meta inner class binds this Graphene type to its SQLAlchemy model
        # and registers it with the Relay Node interface for global ID support.
        'Meta': type('Meta', (), {
            'model': globals()[db_clazz_name]
            ,'interfaces': (relay.Node, )
            ,'exclude_fields': exclude_fields
            })
        ,**include_fields
        # Standard query-modifier fields available on every generated type.
        ,'matches': graphene.String(description='contains, exact, regex, re, startswith, sw, endswith, ew, eq, gt, gte, lt, lte, ne', default_value='contains')
        ,'sort_by': graphene.String(description='Field to sort by.', default_value=default_sort_col)
        ,'logic': graphene.String(description='and, or', default_value='and')
        ,'sort_dir': graphene.String(description='asc, desc', default_value='asc')
    }
    return type(str(clazz_name), (SQLAlchemyObjectType,), gql_attrs)

def gql_connection_class_constructor(clazz_name, gql_clazz_name):
    """
    Dynamically create a Relay ``Connection`` subclass for *gql_clazz_name*.

    A Relay Connection wraps a list of nodes with pagination metadata
    (``pageInfo``, ``edges``, ``totalCount``).  This factory is kept separate
    from :func:`gql_class_constructor` so that connection and node types can
    be created independently and composed as needed.

    :param clazz_name:      Name for the generated Connection class (string).
    :param gql_clazz_name:  The ``SQLAlchemyObjectType`` subclass (node type)
                            that this Connection wraps.
    :returns: Dynamically generated ``relay.Connection`` subclass.
    """
    gql_attrs = {
        'Meta': type('Meta', (), {'node': gql_clazz_name})
        }
    return type(str(clazz_name), (relay.Connection,), gql_attrs)

class MyConnectionField(SQLAlchemyConnectionField):
    """
    Custom Relay connection field that adds server-side filtering and sorting
    on top of the standard ``SQLAlchemyConnectionField`` behaviour.

    Every generated entity query field in :class:`Query` uses this class so
    that all entities uniformly support the same ``matches``, ``logic``,
    ``sort_by``, and ``sort_dir`` arguments without any per-entity code.

    Supported ``matches`` values and their SQL equivalents:

    +--------------+-----------------------------------+
    | Client value | SQL behaviour                     |
    +==============+===================================+
    | contains     | ``ILIKE '%value%'`` (default)     |
    | exact / eq   | ``= value``                       |
    | regex / re   | ``REGEXP value``                  |
    | startswith/sw| ``ILIKE 'value%'``                |
    | endswith/ew  | ``ILIKE '%value'``                |
    | lt / lte     | ``< value`` / ``<= value``        |
    | gt / gte     | ``> value`` / ``>= value``        |
    | ne           | ``!= value``                      |
    +--------------+-----------------------------------+

    Date/datetime fields without an explicit ``matches`` value default to
    ``>=`` (i.e. "on or after").  List values use SQL ``IN``.
    """

    # Standard Relay pagination arguments that must not be treated as
    # column filters by the custom filtering logic below.
    RELAY_ARGS = ['first', 'last', 'before', 'after']

    @classmethod
    def get_query(cls, model, info, sort=None, filter=None, **args):
        """
        Build and return a SQLAlchemy ``Query`` with filtering and sorting
        applied from the client-supplied GraphQL arguments.

        Custom query-modifier arguments (``matches``, ``logic``, ``sort_by``,
        ``sort_dir``) are popped from *args* before the remaining args are
        forwarded to the parent implementation, which handles relay pagination
        and any graphene-sqlalchemy native filter/sort parameters.

        :param model:  The SQLAlchemy model class being queried.
        :param info:   Graphene ``ResolveInfo`` object (request context).
        :param sort:   Native graphene-sqlalchemy sort argument (passed through).
        :param filter: Native graphene-sqlalchemy filter argument (passed through).
        :param args:   Remaining keyword arguments — a mix of column filter
                       values and relay pagination args.
        :returns: Filtered and sorted SQLAlchemy ``Query``.
        """
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
                filter_conditions.append(getattr(model, field).ilike(str(value) + '%'))
            elif matches in ('endswith', 'ew'):
                filter_conditions.append(getattr(model, field).ilike('%' + str(value)))
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
                filter_conditions.append(getattr(model, field).ilike('%' + str(value) + '%'))

        if filter_conditions:
            if operator == 'or':
                query = query.filter(or_(*filter_conditions))
            else:
                query = query.filter(and_(*filter_conditions))

        if sort_clause is not None:
            query = query.order_by(sort_clause)

        return query

# Dynamically create all Graphene SQLAlchemyObjectType subclasses defined in
# the schema dictionary and inject each one into the module namespace.  This
# allows schema.py to grow with the schema file alone — no manual class
# definitions are needed here.
for clazz in schema_settings.get_gql_classes():
    globals()[clazz['gql_class']] = gql_class_constructor(
        clazz['gql_class']
        ,clazz['gql_db_class']
        ,clazz['gql_columns']
        ,clazz['gql_db_default_sort_col']
        )

def _make_gql_query_fields(cols):
    """
    Build the keyword-argument dict of Graphene field declarations used to
    construct a :class:`MyConnectionField` argument list for one entity.

    Only columns that are queryable (``isqueryable=True``), not hidden, and
    not resolver-backed are exposed as filterable arguments.  Relationship
    navigation fields (``gql_isqueryable: False`` in ``schema.dct``) are
    intentionally excluded because SQLAlchemy cannot filter on them directly.

    The four standard query-modifier fields (``matches``, ``sort_by``,
    ``logic``, ``sort_dir``) are always appended so every entity connection
    supports sorting and filter-mode selection.

    :param cols: List of column descriptor dicts from ``schema_settings``.
    :returns:    Dict mapping argument names to Graphene field instances,
                 ready to be unpacked into ``MyConnectionField(...)``.
    """
    gql_attrs = {}
    for row in cols:
        # Exclude hidden fields and resolver-backed fields; also skip columns
        # marked gql_isqueryable=False (e.g. relationship navigation fields)
        # because they cannot be used as SQL filter predicates.
        if row['isqueryable'] and row['ishidden'] is False and row['isresolver'] is False:
            gql_attrs[row['name']] = row['type'](row['type_args'] if row['type_args'] else None)
    # Append the standard modifier arguments supported by MyConnectionField.
    gql_attrs.update({
        'matches': graphene.String()
        ,'sort_by': graphene.String()
        ,'logic': graphene.String()
        ,'sort_dir': graphene.String()
        })
    return gql_attrs
    
class Query(graphene.ObjectType):
    """
    Root GraphQL query type.

    One :class:`MyConnectionField` is attached per entity defined in the
    schema dictionary.  Each field is a Relay connection that supports
    pagination (``first``, ``last``, ``before``, ``after``), filtering via
    column-value arguments, and the ``matches`` / ``sort_by`` / ``logic`` /
    ``sort_dir`` modifiers provided by :class:`MyConnectionField`.

    ``node`` is the standard Relay global-ID lookup field required by the
    Relay specification.
    """

    # Relay global object identification — allows any node to be fetched by
    # its opaque global ID (base64-encoded type + primary key).
    node = relay.Node.Field()

    # Dynamically attach a connection field for every entity in the schema.
    # Using locals() inside the class body writes directly into the class
    # namespace, which is the standard pattern for dynamic class attributes.
    for clazz in schema_settings.get_gql_classes():
        locals()[clazz['gql_conn_query_name']] = MyConnectionField(
            globals()[clazz['gql_class']]
            ,_make_gql_query_fields(clazz['gql_columns'])
            )

# Compile the final GraphQL schema from the Query root type.
# auto_camelcase=False preserves the snake_case field names defined in the
# schema dictionary, keeping GraphQL field names consistent with the database.
gql_schema = graphene.Schema(query=Query, auto_camelcase=False)
