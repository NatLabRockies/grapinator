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

import re
from sqlalchemy import and_, or_, desc, asc, false as sql_false, select
from sqlalchemy import inspect as sqlalchemy_inspect
import graphene
from graphene import relay
from graphene.relay.node import NodeField
from graphene_sqlalchemy import SQLAlchemyObjectType, SQLAlchemyConnectionField
from graphene.types.definitions import (
    GrapheneInterfaceType,
    GrapheneObjectType,
    GrapheneUnionType,
)
from functools import lru_cache
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLUnionType,
)
import datetime
import logging
from grapinator import schema_settings
from grapinator.model import *
from grapinator.security import register_model_policy

logger = logging.getLogger(__name__)


class ClientError(Exception):
    """Error whose message is safe to return to any caller."""

# Module-level registry: maps SQLAlchemy class name (e.g. 'db_Employees') to
# the list of roles required to query that entity.  Populated at schema-build
# time; used by MyConnectionField.get_query() for entity-level RBAC.
_ENTITY_AUTH_ROLES = {}
_SORTABLE_FIELDS = {}
_FIELD_AUTH_ROLES = {}
_FILTER_FIELD_AUTH_ROLES = {}
_SORT_FIELD_AUTH_ROLES = {}
_QUERY_FILTER_AUTH_ROLES = {}


def _make_role_field_resolver(field_name, required_roles, resolver=None):
    def _resolve(root, info, **kwargs):
        context = info.context if info.context is not None else {}
        user_roles = context.get('user_roles', []) if isinstance(context, dict) else []
        if not set(user_roles) & set(required_roles):
            return None
        if resolver is not None:
            return resolver(root, info, **kwargs)
        return getattr(root, field_name, None)
    return _resolve


def get_schema_for_roles(user_roles):
    """Return a cached GraphQL schema exposing fields allowed to these roles."""
    role_key = tuple(sorted(set(user_roles or ())))
    return _schema_for_role_key(role_key)


@lru_cache(maxsize=128)
def _schema_for_role_key(role_key):
    roles = set(role_key)
    base_schema = gql_schema.graphql_schema
    cloned_types = {}

    def clone_type(type_):
        if type_ is None:
            return None
        if isinstance(type_, GraphQLNonNull):
            return GraphQLNonNull(clone_type(type_.of_type))
        if isinstance(type_, GraphQLList):
            return GraphQLList(clone_type(type_.of_type))
        if type_.name.startswith('__'):
            return type_
        if type_.name in cloned_types:
            return cloned_types[type_.name]

        if isinstance(type_, GraphQLObjectType):
            clone = GrapheneObjectType(
                type_.name,
                lambda: clone_fields(type_),
                interfaces=lambda: [clone_type(interface) for interface in type_.interfaces],
                graphene_type=type_.graphene_type,
                is_type_of=type_.is_type_of,
                extensions=type_.extensions,
                description=type_.description,
                ast_node=type_.ast_node,
                extension_ast_nodes=type_.extension_ast_nodes,
            )
        elif isinstance(type_, GraphQLInterfaceType):
            clone = GrapheneInterfaceType(
                type_.name,
                lambda: clone_fields(type_),
                interfaces=lambda: [clone_type(interface) for interface in type_.interfaces],
                graphene_type=type_.graphene_type,
                resolve_type=type_.resolve_type,
                extensions=type_.extensions,
                description=type_.description,
                ast_node=type_.ast_node,
                extension_ast_nodes=type_.extension_ast_nodes,
            )
        elif isinstance(type_, GraphQLUnionType):
            clone = GrapheneUnionType(
                type_.name,
                types=lambda: [clone_type(member) for member in type_.types],
                graphene_type=type_.graphene_type,
                resolve_type=type_.resolve_type,
                extensions=type_.extensions,
                description=type_.description,
                ast_node=type_.ast_node,
                extension_ast_nodes=type_.extension_ast_nodes,
            )
        elif isinstance(type_, GraphQLInputObjectType):
            clone = GraphQLInputObjectType(
                type_.name,
                lambda: {
                    name: GraphQLInputField(
                        clone_type(field.type),
                        default_value=field.default_value,
                        description=field.description,
                        deprecation_reason=field.deprecation_reason,
                        out_name=field.out_name,
                        extensions=field.extensions,
                        ast_node=field.ast_node,
                    )
                    for name, field in type_.fields.items()
                },
                out_type=type_.out_type,
                extensions=type_.extensions,
                description=type_.description,
                ast_node=type_.ast_node,
                extension_ast_nodes=type_.extension_ast_nodes,
                is_one_of=type_.is_one_of,
            )
        else:
            return type_

        cloned_types[type_.name] = clone
        return clone

    def clone_fields(type_):
        protected_fields = _FIELD_AUTH_ROLES.get(type_.name, {})
        fields = {}
        for name, field in type_.fields.items():
            field_roles = protected_fields.get(name)
            if field_roles and not roles.intersection(field_roles):
                continue

            filter_roles = _QUERY_FILTER_AUTH_ROLES.get(name, {})
            args = {
                arg_name: GraphQLArgument(
                    clone_type(arg.type),
                    default_value=arg.default_value,
                    description=arg.description,
                    deprecation_reason=arg.deprecation_reason,
                    out_name=arg.out_name,
                    extensions=arg.extensions,
                    ast_node=arg.ast_node,
                )
                for arg_name, arg in field.args.items()
                if not filter_roles.get(arg_name)
                or roles.intersection(filter_roles[arg_name])
            }
            fields[name] = GraphQLField(
                clone_type(field.type),
                args=args,
                resolve=field.resolve,
                subscribe=field.subscribe,
                description=field.description,
                deprecation_reason=field.deprecation_reason,
                extensions=field.extensions,
                ast_node=field.ast_node,
            )
        return fields

    return GraphQLSchema(
        query=clone_type(base_schema.query_type),
        mutation=clone_type(base_schema.mutation_type),
        subscription=clone_type(base_schema.subscription_type),
        types=[
            clone_type(type_)
            for name, type_ in base_schema.type_map.items()
            if not name.startswith('__')
        ],
        directives=base_schema.directives,
        description=base_schema.description,
        extensions=base_schema.extensions,
    )


def _policy_safe_get_node(cls, info, id):
    model = cls._meta.model
    primary_keys = sqlalchemy_inspect(model).primary_key
    if len(primary_keys) != 1:
        return None
    return db_session.execute(
        select(model).where(primary_keys[0] == id)
    ).scalars().first()


class _PolicySafeNodeField(NodeField):
    def wrap_resolve(self, parent_resolver):
        resolve = super().wrap_resolve(parent_resolver)

        def resolve_node(*args, **kwargs):
            try:
                return resolve(*args, **kwargs)
            except Exception:
                logger.debug('Relay node lookup failed')
                return None

        return resolve_node

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
    _FIELD_AUTH_ROLES[clazz_name] = {
        attr['name']: attr['auth_roles']
        for attr in clazz_attrs
        if attr.get('auth_roles')
    }
    for attr in clazz_attrs:
        if attr['ishidden']:
            exclude_fields += (attr['name'],)
        elif attr['isresolver']:
            # Resolver fields are backed by a custom function rather than a
            # direct column value.  Both the field declaration and its
            # paired resolve_<name> method are injected into the class.
            attr_name = attr['name']
            resolver_name = "resolve_{}".format(attr_name)
            include_fields[attr_name] = attr['type'](attr['type_args'], description=attr['desc'])
            if attr.get('auth_roles'):
                include_fields[resolver_name] = _make_role_field_resolver(
                    attr_name, attr['auth_roles'], attr['resolver_func']
                )
            else:
                include_fields[resolver_name] = attr['resolver_func']
        else:
            field_kwargs = {'description': attr['desc']}
            if attr.get('deprecation_reason'):
                field_kwargs['deprecation_reason'] = attr['deprecation_reason']
            include_fields[attr['name']] = attr['type'](attr['type_args'], **field_kwargs)
            if attr.get('auth_roles'):
                include_fields['resolve_{}'.format(attr['name'])] = (
                    _make_role_field_resolver(attr['name'], attr['auth_roles'])
                )

    gql_attrs = {
        # Meta inner class binds this Graphene type to its SQLAlchemy model
        # and registers it with the Relay Node interface for global ID support.
        'Meta': type('Meta', (), {
            'model': globals()[db_clazz_name]
            ,'interfaces': (relay.Node, )
            ,'exclude_fields': exclude_fields
            })
        ,'get_node': classmethod(_policy_safe_get_node)
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

        context = info.context if info.context is not None else {}
        user_roles = context.get('user_roles', []) if isinstance(context, dict) else []
        filter_roles = _FILTER_FIELD_AUTH_ROLES.get(model.__name__, {})
        for field_name, value in args.items():
            required_roles = filter_roles.get(field_name)
            if value is not None and required_roles and not set(user_roles) & set(required_roles):
                raise ClientError('Invalid filter argument.')

        # Build ORDER BY only when a sort column is actually provided/non-None.
        # Only explicitly sortable fields available to the caller may affect
        # ordering; every other value behaves like an unknown sort name.
        sort_clause = None
        if sort_by_name:
            sort_roles = _SORT_FIELD_AUTH_ROLES.get(model.__name__, {})
            allowed_sort_fields = {
                name for name in _SORTABLE_FIELDS.get(model.__name__, ())
                if not sort_roles.get(name)
                or set(user_roles) & set(sort_roles[name])
            }
            if sort_by_name in allowed_sort_fields:
                sort_col = getattr(model, sort_by_name)
                sort_clause = asc(sort_col) if sort_dir != 'desc' else desc(sort_col)
            else:
                logger.debug(
                    'get_query: sort_by %r ignored on %s',
                    sort_by_name, model.__name__,
                )

        # Let graphene-sqlalchemy 3.x handle its own sort/filter params.
        query = super(MyConnectionField, cls).get_query(
            model, info, sort=sort, filter=filter, **args
        )

        # Entity-level RBAC: if this entity declares AUTH_ROLES and the
        # caller's roles do not intersect, return an empty result set rather
        # than a permission error — this leaks no information about the data.
        entity_auth_roles = _ENTITY_AUTH_ROLES.get(model.__name__)
        if entity_auth_roles:
            ctx = info.context if info.context is not None else {}
            user_roles = ctx.get('user_roles', []) if isinstance(ctx, dict) else []
            if not set(user_roles) & set(entity_auth_roles):
                logger.debug(
                    'RBAC entity access denied: %s user_roles=%s required=%s',
                    model.__name__, user_roles, entity_auth_roles,
                )
                return query.filter(sql_false())
            logger.debug(
                'RBAC entity access granted: %s user_roles=%s',
                model.__name__, user_roles,
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
                # Cap regex length to prevent ReDoS via catastrophic backtracking
                # in the database engine from client-supplied patterns.
                if len(str(value)) > 200:
                    logger.warning(
                        'get_query: regex pattern too long (%d chars) — rejected',
                        len(str(value)),
                    )
                    raise ClientError('Regex pattern exceeds maximum allowed length (200 chars).')
                try:
                    re.compile(str(value))
                except re.error as error:
                    raise ClientError('Invalid regex pattern.') from error
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
_gql_class_count = 0
for clazz in schema_settings.get_gql_classes():
    globals()[clazz['gql_class']] = gql_class_constructor(
        clazz['gql_class']
        ,clazz['gql_db_class']
        ,clazz['gql_columns']
        ,clazz['gql_db_default_sort_col']
        )
    logger.debug('GQL type built: %s (db=%s)', clazz['gql_class'], clazz['gql_db_class'])
    # Register entity-level auth roles so MyConnectionField.get_query() can
    # enforce them using the SQLAlchemy model class name as the key.
    if clazz.get('gql_entity_auth_roles'):
        _ENTITY_AUTH_ROLES[clazz['gql_db_class']] = clazz['gql_entity_auth_roles']
        logger.debug(
            'Entity auth roles registered: %s -> %s',
            clazz['gql_db_class'], clazz['gql_entity_auth_roles'],
        )
    register_model_policy(
        globals()[clazz['gql_db_class']],
        roles=clazz.get('gql_entity_auth_roles'),
        row_auth_claims=clazz.get('gql_row_auth_claims'),
    )
    _SORTABLE_FIELDS[clazz['gql_db_class']] = {
        column['name'] for column in clazz['gql_columns']
        if column['isqueryable']
        and not column['ishidden']
        and not column['isresolver']
    }
    _FILTER_FIELD_AUTH_ROLES[clazz['gql_db_class']] = {
        column['name']: column['auth_roles']
        for column in clazz['gql_columns']
        if column.get('auth_roles')
        and column['isqueryable']
        and not column['ishidden']
        and not column['isresolver']
    }
    _SORT_FIELD_AUTH_ROLES[clazz['gql_db_class']] = {
        column['name']: column['auth_roles']
        for column in clazz['gql_columns']
        if column.get('auth_roles')
        and column['isqueryable']
        and not column['ishidden']
        and not column['isresolver']
    }
    _QUERY_FILTER_AUTH_ROLES[clazz['gql_conn_query_name']] = {
        column['name']: column['auth_roles']
        for column in clazz['gql_columns']
        if column.get('auth_roles')
        and column['isqueryable']
        and not column['ishidden']
        and not column['isresolver']
    }
    _gql_class_count += 1
logger.info('GraphQL types built: %d', _gql_class_count)

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
        if (
            row['isqueryable']
            and row['ishidden'] is False
            and row['isresolver'] is False
        ):
            extra_kwargs = {}
            if row.get('deprecation_reason'):
                extra_kwargs['deprecation_reason'] = row['deprecation_reason']
            gql_attrs[row['name']] = row['type'](row['type_args'] if row['type_args'] else None, **extra_kwargs)
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
    node = _PolicySafeNodeField(relay.Node)

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
logger.info('GraphQL schema compiled (auto_camelcase=False)')
