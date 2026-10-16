"""Tests for the ``where`` filter argument and ``MAX_PAGE_SIZE`` (issue #43).

Most tests run GraphQL queries through the Flask app against the bundled
Northwind SQLite database.  Boolean operators are covered with a small
in-memory model because Northwind has no Boolean columns.
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import unittest
from unittest.mock import MagicMock, patch

from . import context  # noqa: F401

import graphene
from graphql import validate_schema
from sqlalchemy import Boolean, Column, Integer, create_engine, event
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from graphene_sqlalchemy import SQLAlchemyConnectionField

import grapinator.schema as schema_module
from grapinator import settings
from grapinator.app import app
from grapinator.model import engine
from grapinator.schema import (
    ClientError,
    MyConnectionField,
    _SORTABLE_FIELDS,
    _make_gql_query_fields,
    _make_where_filter_type,
    _scalar_filter_type,
)
from grapinator.security import _MODEL_POLICIES, register_model_policy


EMPLOYEES = (
    '{ employees(where: %s, sort_by: "employee_id") '
    '{ edges { node { employee_id } } } }'
)


class _GraphQLTestCase(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def post(self, query, variables=None, roles=None, authenticated=False, claims=None):
        environ = {
            'grapinator.user_roles': roles or [],
            'grapinator.authenticated': authenticated,
            'grapinator.user_claims': claims or {},
        }
        return self.client.post(
            settings.FLASK_API_ENDPOINT,
            json={'query': query, 'variables': variables},
            environ_overrides=environ,
        ).get_json()

    def employee_ids(self, where, **kwargs):
        body = self.post(EMPLOYEES % where, **kwargs)
        self.assertNotIn('errors', body, body)
        return [edge['node']['employee_id'] for edge in body['data']['employees']['edges']]

    def error_messages(self, query, **kwargs):
        body = self.post(query, **kwargs)
        self.assertIn('errors', body, body)
        return [error['message'] for error in body['errors']]

    def count_statements(self):
        statements = []

        def record(_conn, _cursor, statement, *_args):
            statements.append(statement)

        event.listen(engine, 'before_cursor_execute', record)
        self.addCleanup(event.remove, engine, 'before_cursor_execute', record)
        return statements


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class TestWhereOperators(_GraphQLTestCase):

    def test_string_operators(self):
        cases = {
            '{city: {eq: "London"}}': [5, 6, 7, 9],
            '{city: {ne: "London"}}': [1, 2, 3, 4, 8],
            '{city: {in: ["Tacoma", "Redmond"]}}': [2, 4],
            '{city: {notIn: ["London", "Seattle"]}}': [2, 3, 4],
            '{last_name: {contains: "LL"}}': [2, 8],
            '{last_name: {startsWith: "d"}}': [1, 9],
            '{last_name: {endsWith: "ING"}}': [3, 7],
        }
        for where, expected in cases.items():
            with self.subTest(where=where):
                self.assertEqual(self.employee_ids(where), expected)

    def test_eq_is_case_sensitive(self):
        self.assertEqual(self.employee_ids('{city: {eq: "london"}}'), [])

    def test_like_metacharacters_are_literal(self):
        self.assertEqual(self.employee_ids('{last_name: {contains: "%"}}'), [])
        self.assertEqual(self.employee_ids('{last_name: {startsWith: "_"}}'), [])

    def test_int_operators(self):
        cases = {
            '{employee_id: {eq: 3}}': [3],
            '{employee_id: {ne: 3}}': [1, 2, 4, 5, 6, 7, 8, 9],
            '{employee_id: {gt: 7}}': [8, 9],
            '{employee_id: {gte: 7}}': [7, 8, 9],
            '{employee_id: {lt: 3}}': [1, 2],
            '{employee_id: {lte: 3}}': [1, 2, 3],
            '{employee_id: {in: [1, 5]}}': [1, 5],
            '{employee_id: {notIn: [1, 5]}}': [2, 3, 4, 6, 7, 8, 9],
            '{employee_id: {gt: 2, lt: 5}}': [3, 4],
        }
        for where, expected in cases.items():
            with self.subTest(where=where):
                self.assertEqual(self.employee_ids(where), expected)

    def test_datetime_operators(self):
        cases = {
            '{hire_date: {gte: "2014-01-01T00:00:00"}}': [7, 8, 9],
            '{hire_date: {lt: "2012-06-01T00:00:00"}}': [1, 3],
        }
        for where, expected in cases.items():
            with self.subTest(where=where):
                self.assertEqual(self.employee_ids(where), expected)

    def test_float_operators(self):
        body = self.post(
            '{ products(where: {unit_price: {gt: 100}}) '
            '{ edges { node { product_id unit_price } } } }'
        )
        prices = [edge['node']['unit_price'] for edge in body['data']['products']['edges']]
        self.assertTrue(prices)
        self.assertTrue(all(price > 100 for price in prices))

    def test_is_null(self):
        self.assertEqual(self.employee_ids('{reports_to: {isNull: true}}'), [2])
        self.assertEqual(
            self.employee_ids('{reports_to: {isNull: false}}'),
            [1, 3, 4, 5, 6, 7, 8, 9],
        )
        # Primary keys are never null.
        self.assertEqual(self.employee_ids('{employee_id: {isNull: true}}'), [])
        self.assertEqual(len(self.employee_ids('{employee_id: {isNull: false}}')), 9)

    def test_ne_does_not_return_nulls(self):
        self.assertEqual(self.employee_ids('{reports_to: {ne: 2}}'), [6, 7, 9])
        self.assertEqual(
            self.employee_ids('{or: [{reports_to: {ne: 2}}, {reports_to: {isNull: true}}]}'),
            [2, 6, 7, 9],
        )


# ---------------------------------------------------------------------------
# Boolean logic
# ---------------------------------------------------------------------------

class TestWhereLogic(_GraphQLTestCase):

    def test_implicit_and(self):
        self.assertEqual(
            self.employee_ids('{city: {eq: "London"}, reports_to: {eq: 5}}'),
            [6, 7, 9],
        )

    def test_and_or_not(self):
        self.assertEqual(
            self.employee_ids('{and: [{city: {eq: "London"}}, {employee_id: {gt: 6}}]}'),
            [7, 9],
        )
        self.assertEqual(
            self.employee_ids('{or: [{city: {eq: "Tacoma"}}, {employee_id: {eq: 9}}]}'),
            [2, 9],
        )
        self.assertEqual(
            self.employee_ids('{not: {city: {eq: "London"}}}'),
            [1, 2, 3, 4, 8],
        )

    def test_nesting(self):
        self.assertEqual(
            self.employee_ids(
                '{city: {in: ["London", "Seattle"]}, '
                'or: [{not: {reports_to: {eq: 5}}}, {employee_id: {eq: 9}}]}'
            ),
            [1, 5, 8, 9],
        )

    def test_empty_forms(self):
        self.assertEqual(len(self.employee_ids('{}')), 9)
        self.assertEqual(len(self.employee_ids('null')), 9)
        self.assertEqual(len(self.employee_ids('{and: []}')), 9)
        self.assertEqual(self.employee_ids('{or: []}'), [])
        self.assertEqual(self.employee_ids('{employee_id: {in: []}}'), [])
        self.assertEqual(len(self.employee_ids('{employee_id: {notIn: []}}')), 9)

    def test_in_matches_equivalent_or(self):
        self.assertEqual(
            self.employee_ids('{employee_id: {in: [1, 5]}}'),
            self.employee_ids('{or: [{employee_id: {eq: 1}}, {employee_id: {eq: 5}}]}'),
        )

    def test_in_lists_with_one_and_duplicate_values(self):
        self.assertEqual(self.employee_ids('{employee_id: {in: [4]}}'), [4])
        self.assertEqual(self.employee_ids('{employee_id: {in: [4, 4, 4]}}'), [4])

    def test_where_via_variables(self):
        body = self.post(
            'query($w: EmployeesFilter) { employees(where: $w, sort_by: "employee_id") '
            '{ edges { node { employee_id } } } }',
            variables={'w': {'or': [{'city': {'eq': 'Tacoma'}}, {'employee_id': {'in': [1]}}]}},
        )
        self.assertNotIn('errors', body)
        self.assertEqual(
            [edge['node']['employee_id'] for edge in body['data']['employees']['edges']],
            [1, 2],
        )


# ---------------------------------------------------------------------------
# Null handling, list caps, and guardrails
# ---------------------------------------------------------------------------

class TestWhereRejections(_GraphQLTestCase):

    def test_explicit_null_operand_is_rejected_with_guidance(self):
        statements = self.count_statements()
        messages = self.error_messages(EMPLOYEES % '{region: {eq: null}}')
        self.assertEqual(
            messages,
            ["Null is not allowed for 'eq'; use isNull to match null values."],
        )
        self.assertEqual(statements, [])

    def test_null_column_filter_is_rejected(self):
        messages = self.error_messages(EMPLOYEES % '{region: null}')
        self.assertIn('use isNull', messages[0])

    def test_null_inside_in_list_fails_validation(self):
        messages = self.error_messages(EMPLOYEES % '{employee_id: {in: [1, null]}}')
        self.assertIn('Expected value of type', messages[0])

    def test_oversize_in_list_is_rejected_before_sql(self):
        values = ', '.join(str(i) for i in range(settings.MAX_IN_LIST_SIZE + 1))
        statements = self.count_statements()
        messages = self.error_messages(EMPLOYEES % '{employee_id: {in: [%s]}}' % values)
        self.assertEqual(
            messages, [f'List exceeds the maximum of {settings.MAX_IN_LIST_SIZE} values.']
        )
        self.assertEqual(statements, [])

    def test_in_list_cap_follows_setting(self):
        with patch.object(settings, 'MAX_IN_LIST_SIZE', 2):
            self.assertEqual(self.employee_ids('{employee_id: {notIn: [1, 2]}}'),
                             [3, 4, 5, 6, 7, 8, 9])
            messages = self.error_messages(EMPLOYEES % '{employee_id: {notIn: [1, 2, 3]}}')
        self.assertEqual(messages, ['List exceeds the maximum of 2 values.'])

    def test_depth_cap(self):
        nested = '{employee_id: {eq: 1}}'
        for _ in range(schema_module._WHERE_MAX_DEPTH - 1):
            nested = '{not: %s}' % nested
        self.assertEqual(len(self.employee_ids(nested)), 8)

        statements = self.count_statements()
        messages = self.error_messages(EMPLOYEES % ('{not: %s}' % nested))
        self.assertEqual(
            messages,
            [f'Filter nesting exceeds the maximum depth of {schema_module._WHERE_MAX_DEPTH}.'],
        )
        self.assertEqual(statements, [])

    def test_predicate_cap(self):
        limit = schema_module._WHERE_MAX_PREDICATES
        ok = '{or: [%s]}' % ', '.join('{employee_id: {eq: %d}}' % i for i in range(limit))
        self.assertEqual(len(self.employee_ids(ok)), 9)

        too_many = '{or: [%s]}' % ', '.join(
            '{employee_id: {eq: %d}}' % i for i in range(limit + 1)
        )
        statements = self.count_statements()
        messages = self.error_messages(EMPLOYEES % too_many)
        self.assertEqual(messages, [f'Filter exceeds the maximum of {limit} conditions.'])
        self.assertEqual(statements, [])

    def test_where_has_no_regex_operator(self):
        messages = self.error_messages(EMPLOYEES % '{city: {regex: "^L"}}')
        self.assertEqual(messages, ["Field 'regex' is not defined by type 'StringFilter'."])

    def test_wrong_operand_type_fails_validation(self):
        messages = self.error_messages(EMPLOYEES % '{employee_id: {in: ["1"]}}')
        self.assertIn('Int cannot represent', messages[0])


# ---------------------------------------------------------------------------
# Legacy compatibility and mixing
# ---------------------------------------------------------------------------

class TestLegacyCompatibility(_GraphQLTestCase):

    def test_legacy_and_where_combine_with_and(self):
        legacy = self.employee_ids_for(
            '{ employees(city: "London", sort_by: "employee_id") '
            '{ edges { node { employee_id } } } }'
        )
        self.assertEqual(legacy, [5, 6, 7, 9])
        mixed = self.employee_ids_for(
            '{ employees(city: "London", where: {reports_to: {eq: 5}}, '
            'sort_by: "employee_id") { edges { node { employee_id } } } }'
        )
        self.assertEqual(mixed, [6, 7, 9])

    def test_logic_applies_only_to_legacy_arguments(self):
        mixed = self.employee_ids_for(
            '{ employees(city: "Tacoma", last_name: "King", logic: "or", '
            'where: {employee_id: {gt: 5}}, sort_by: "employee_id") '
            '{ edges { node { employee_id } } } }'
        )
        self.assertEqual(mixed, [7])

    def test_legacy_usage_is_logged(self):
        with self.assertLogs('grapinator.schema', level='INFO') as captured:
            self.employee_ids_for(
                '{ employees(city: "London") { edges { node { employee_id } } } }'
            )
        self.assertTrue(any('Deprecated filter arguments' in line and 'city' in line
                            for line in captured.output))

    def test_where_only_does_not_log_legacy_usage(self):
        with patch.object(schema_module.logger, 'info') as info:
            self.employee_ids('{city: {eq: "London"}}')
        self.assertFalse(any(
            'Deprecated filter arguments' in str(call.args[0]) for call in info.call_args_list
        ))

    def test_introspection_marks_only_legacy_filters_deprecated(self):
        body = self.post(
            '{ __type(name: "Query") { fields { name '
            'args(includeDeprecated: true) { name isDeprecated deprecationReason } } } }'
        )
        args = {
            arg['name']: arg
            for field in body['data']['__type']['fields'] if field['name'] == 'employees'
            for arg in field['args']
        }
        for name in ('city', 'employee_id', 'matches', 'logic'):
            self.assertTrue(args[name]['isDeprecated'], name)
            self.assertEqual(args[name]['deprecationReason'], 'Use the where argument instead.')
        for name in ('where', 'sort_by', 'sort_dir', 'first', 'last', 'before', 'after'):
            self.assertFalse(args[name]['isDeprecated'], name)

    def test_dct_deprecation_reason_takes_precedence(self):
        fields = _make_gql_query_fields([{
            'name': 'old_col', 'type': graphene.String, 'type_args': None,
            'isqueryable': True, 'ishidden': False, 'isresolver': False,
            'deprecation_reason': 'Use new_col.',
        }])
        self.assertEqual(fields['old_col'].kwargs['deprecation_reason'], 'Use new_col.')

    def employee_ids_for(self, query):
        body = self.post(query)
        self.assertNotIn('errors', body, body)
        return [edge['node']['employee_id'] for edge in body['data']['employees']['edges']]


# ---------------------------------------------------------------------------
# Schema generation
# ---------------------------------------------------------------------------

class TestWhereSchema(unittest.TestCase):

    def test_entity_filter_fields(self):
        filter_type = schema_module.gql_schema.graphql_schema.get_type('EmployeesFilter')
        self.assertIn('birth_date', filter_type.fields)
        self.assertIn('employee_id', filter_type.fields)
        self.assertIn('and', filter_type.fields)
        self.assertIn('or', filter_type.fields)
        self.assertIn('not', filter_type.fields)
        # Relationship navigation fields are not filterable.
        self.assertNotIn('territories', filter_type.fields)

    def test_scalar_filter_operators(self):
        schema = schema_module.gql_schema.graphql_schema
        self.assertEqual(
            set(schema.get_type('StringFilter').fields),
            {'eq', 'ne', 'in', 'notIn', 'contains', 'startsWith', 'endsWith', 'isNull'},
        )
        self.assertEqual(
            set(schema.get_type('IntFilter').fields),
            {'eq', 'ne', 'in', 'notIn', 'gt', 'gte', 'lt', 'lte', 'isNull'},
        )
        self.assertEqual(
            set(schema.get_type('DateTimeFilter').fields),
            set(schema.get_type('FloatFilter').fields),
        )
        self.assertEqual(
            set(_scalar_filter_type(graphene.Boolean)._meta.fields),
            {'eq', 'ne', 'isNull'},
        )

    def test_logical_column_name_fails_schema_build(self):
        with self.assertRaisesRegex(RuntimeError, 'logical operator'):
            _make_where_filter_type('Widgets', [{
                'name': 'not', 'type': graphene.String, 'desc': None,
                'isqueryable': True, 'ishidden': False, 'isresolver': False,
            }])

    def test_type_name_collision_fails_schema_build(self):
        # 'String' + 'Filter' is the StringFilter scalar filter's name.
        with self.assertRaisesRegex(RuntimeError, 'collides'):
            _make_where_filter_type('String', [])
        # An entity filter name that matches an existing GraphQL class name.
        with patch.dict(schema_module._FILTER_TYPE_OWNERS, {'WidgetsFilter': 'GraphQL class'}):
            with self.assertRaisesRegex(RuntimeError, 'collides'):
                _make_where_filter_type('Widgets', [])

    def test_rbac_schema_dictionary_builds(self):
        from grapinator.settings import SchemaSettings
        rbac_dct = os.path.join(
            os.path.dirname(schema_module.__file__), 'resources', 'schema_rbac.dct'
        )
        classes = SchemaSettings(schema_file=rbac_dct).get_gql_classes()
        employees = next(c for c in classes if c['gql_class'] == 'Employees')
        query_type = type('RbacQuery', (graphene.ObjectType,), {
            'employees': graphene.String(where=graphene.Argument(
                _make_where_filter_type('RbacEmployees', employees['gql_columns'])
            )),
        })
        schema = graphene.Schema(query=query_type, auto_camelcase=False)
        self.assertEqual(validate_schema(schema.graphql_schema), [])
        self.assertIn('birth_date', schema.graphql_schema.get_type('RbacEmployeesFilter').fields)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

class TestWhereRbac(_GraphQLTestCase):

    def setUp(self):
        super().setUp()
        registries = (
            (schema_module._FIELD_AUTH_ROLES, 'Employees'),
            (schema_module._QUERY_FILTER_AUTH_ROLES, 'employees'),
            (schema_module._FILTER_FIELD_AUTH_ROLES, 'db_Employees'),
            (schema_module._SORT_FIELD_AUTH_ROLES, 'db_Employees'),
            (schema_module._WHERE_FIELD_AUTH_ROLES, 'EmployeesFilter'),
        )
        for registry, key in registries:
            original = registry.get(key)
            registry[key] = {'birth_date': ['hr']}
            self.addCleanup(
                lambda r=registry, k=key, o=original:
                r.pop(k, None) if o is None else r.__setitem__(k, o)
            )
        schema_module._schema_for_role_key.cache_clear()
        self.addCleanup(schema_module._schema_for_role_key.cache_clear)

    def test_protected_and_unknown_columns_are_indistinguishable(self):
        for roles, authenticated in (([], False), (['reader'], True)):
            for template in ('%s', '{and: [%s]}', '{or: [%s]}', '{not: %s}'):
                with self.subTest(roles=roles, template=template):
                    statements = self.count_statements()
                    protected = self.error_messages(
                        EMPLOYEES % (template % '{birth_date: {gte: "1960-01-01T00:00:00"}}'),
                        roles=roles, authenticated=authenticated,
                    )
                    unknown = self.error_messages(
                        EMPLOYEES % (template % '{absent_probe: {gte: "1960-01-01T00:00:00"}}'),
                        roles=roles, authenticated=authenticated,
                    )
                    self.assertEqual(
                        [m.replace('birth_date', 'probe') for m in protected],
                        [m.replace('absent_probe', 'probe') for m in unknown],
                    )
                    self.assertFalse(any('Did you mean' in m for m in protected + unknown))
                    self.assertEqual(statements, [])

    def test_variables_do_not_leak_suggestions(self):
        query = ('query($w: EmployeesFilter) { employees(where: $w) '
                 '{ edges { node { employee_id } } } }')
        for roles, authenticated in (([], False), (['reader'], True)):
            with self.subTest(roles=roles):
                protected = self.error_messages(
                    query, variables={'w': {'birth_date': {'gte': '1960-01-01T00:00:00'}}},
                    roles=roles, authenticated=authenticated,
                )
                typo = self.error_messages(
                    query, variables={'w': {'birth_dat': {'gte': '1960-01-01T00:00:00'}}},
                    roles=roles, authenticated=authenticated,
                )
                self.assertEqual(
                    [m.replace('birth_date', 'probe') for m in protected],
                    [m.replace('birth_dat', 'probe') for m in typo],
                )
                self.assertFalse(any('Did you mean' in m for m in protected + typo))

    def test_hr_role_can_filter_on_protected_column(self):
        ids = self.employee_ids(
            '{birth_date: {lt: "1960-01-01T00:00:00"}}', roles=['hr'], authenticated=True,
        )
        self.assertEqual(ids, [4])

    def test_hr_role_gets_suggestions_for_typos(self):
        messages = self.error_messages(
            EMPLOYEES % '{birth_dat: {lt: "1950-01-01T00:00:00"}}',
            roles=['hr'], authenticated=True,
        )
        self.assertTrue(any('Did you mean' in m and 'birth_date' in m for m in messages))
        variable_messages = self.error_messages(
            'query($w: EmployeesFilter) { employees(where: $w) '
            '{ edges { node { employee_id } } } }',
            variables={'w': {'birth_dat': {'lt': '1950-01-01T00:00:00'}}},
            roles=['hr'], authenticated=True,
        )
        self.assertTrue(any('Did you mean' in m and 'birth_date' in m for m in variable_messages))

    def test_authenticated_callers_keep_operator_suggestions(self):
        messages = self.error_messages(
            EMPLOYEES % '{city: {eqq: "London"}}', roles=['reader'], authenticated=True,
        )
        self.assertTrue(any("Did you mean 'eq'" in m for m in messages))

    def test_introspection_shows_protected_column_only_to_role(self):
        query = '{ __type(name: "EmployeesFilter") { inputFields { name } } }'
        hr = self.post(query, roles=['hr'], authenticated=True)
        reader = self.post(query, roles=['reader'], authenticated=True)
        hr_fields = {f['name'] for f in hr['data']['__type']['inputFields']}
        reader_fields = {f['name'] for f in reader['data']['__type']['inputFields']}
        self.assertIn('birth_date', hr_fields)
        self.assertNotIn('birth_date', reader_fields)
        self.assertEqual(hr_fields - reader_fields, {'birth_date'})

    def test_translation_rejects_protected_column_without_sql(self):
        info = MagicMock()
        info.context = {'user_roles': ['reader']}
        model = schema_module.db_Employees
        with patch.object(SQLAlchemyConnectionField, 'get_query') as base_query:
            for where in (
                {'birth_date': {'gte': '1960-01-01'}},
                {'not': {'birth_date': {'isNull': True}}},
                {'unknown': {'eq': 1}},
                {'employee_id': {'regex': '.*'}},
            ):
                with self.subTest(where=where):
                    with self.assertRaisesRegex(ClientError, 'Invalid filter argument'):
                        MyConnectionField.get_query(model, info, where=where)
        base_query.assert_not_called()


class TestWhereCannotWidenPolicies(_GraphQLTestCase):

    def setUp(self):
        super().setUp()
        model = schema_module.db_Employees
        original = _MODEL_POLICIES.get(model)
        register_model_policy(model, row_auth_claims={'city': 'org.city'})
        self.addCleanup(
            lambda: _MODEL_POLICIES.pop(model, None)
            if original is None else _MODEL_POLICIES.__setitem__(model, original)
        )

    def test_row_policy_applies_inside_or_and_not(self):
        claims = {'org': {'city': 'London'}}
        for where in (
            '{or: [{employee_id: {gt: 0}}, {employee_id: {isNull: true}}]}',
            '{not: {city: {eq: "London"}}}',
            '{or: [{city: {eq: "Seattle"}}, {not: {city: {eq: "London"}}}]}',
        ):
            with self.subTest(where=where):
                ids = self.employee_ids(where, claims=claims)
                self.assertTrue(set(ids) <= {5, 6, 7, 9})
        self.assertEqual(self.employee_ids('{not: {city: {eq: "London"}}}', claims=claims), [])

    def test_entity_roles_still_deny(self):
        model = schema_module.db_Employees
        register_model_policy(model, roles=['hr'])
        original = schema_module._ENTITY_AUTH_ROLES.get('db_Employees')
        schema_module._ENTITY_AUTH_ROLES['db_Employees'] = ['hr']
        self.addCleanup(
            lambda: schema_module._ENTITY_AUTH_ROLES.pop('db_Employees', None)
            if original is None
            else schema_module._ENTITY_AUTH_ROLES.__setitem__('db_Employees', original)
        )
        self.assertEqual(
            self.employee_ids('{or: [{employee_id: {gt: 0}}, {not: {employee_id: {gt: 0}}}]}'),
            [],
        )


# ---------------------------------------------------------------------------
# Boolean columns (no Boolean column exists in Northwind)
# ---------------------------------------------------------------------------

_BoolBase = declarative_base()


class _Flag(_BoolBase):
    __tablename__ = 'flags'
    id = Column(Integer, primary_key=True)
    active = Column(Boolean)


_bool_engine = create_engine('sqlite:///:memory:')
_BoolBase.metadata.create_all(_bool_engine)
_BoolSession = scoped_session(sessionmaker(bind=_bool_engine))
with _BoolSession() as _seed:
    _seed.add_all([_Flag(id=1, active=True), _Flag(id=2, active=False), _Flag(id=3, active=None)])
    _seed.commit()


class TestBooleanWhere(unittest.TestCase):

    def setUp(self):
        _SORTABLE_FIELDS[_Flag.__name__] = {'id', 'active'}
        self.addCleanup(_SORTABLE_FIELDS.pop, _Flag.__name__, None)

    def ids(self, where):
        with patch.object(SQLAlchemyConnectionField, 'get_query',
                          return_value=_BoolSession.query(_Flag).order_by(_Flag.id)):
            return [row.id for row in MyConnectionField.get_query(_Flag, MagicMock(), where=where)]

    def test_boolean_operators(self):
        self.assertEqual(self.ids({'active': {'eq': True}}), [1])
        self.assertEqual(self.ids({'active': {'ne': True}}), [2])
        self.assertEqual(self.ids({'active': {'isNull': True}}), [3])
        self.assertEqual(self.ids({'active': {'isNull': False}}), [1, 2])

    def test_logical_keys_filled_with_none_are_ignored(self):
        self.assertEqual(self.ids({'active': {'eq': False}, 'and': None, 'or': None, 'not': None}), [2])


# ---------------------------------------------------------------------------
# MAX_PAGE_SIZE
# ---------------------------------------------------------------------------

class TestMaxPageSize(_GraphQLTestCase):

    PAGE = (
        '{ employees(%s sort_by: "employee_id") { pageInfo { hasNextPage '
        'hasPreviousPage endCursor } edges { node { employee_id } } } }'
    )

    def page(self, args=''):
        body = self.post(self.PAGE % args)
        self.assertNotIn('errors', body, body)
        connection = body['data']['employees']
        return [edge['node']['employee_id'] for edge in connection['edges']], connection['pageInfo']

    def test_unset_is_unlimited(self):
        with patch.object(settings, 'MAX_PAGE_SIZE', None):
            ids, info = self.page()
            self.assertEqual(len(ids), 9)
            self.assertFalse(info['hasNextPage'])
            self.assertEqual(len(self.page('first: 100,')[0]), 9)

    def test_values_within_limit_are_unchanged(self):
        with patch.object(settings, 'MAX_PAGE_SIZE', 4):
            self.assertEqual(self.page('first: 2,')[0], [1, 2])
            self.assertEqual(self.page('first: 4,')[0], [1, 2, 3, 4])
            self.assertEqual(self.page('last: 4,')[0], [6, 7, 8, 9])

    def test_oversized_first_is_clamped_and_cursors_continue(self):
        with patch.object(settings, 'MAX_PAGE_SIZE', 4):
            ids, info = self.page('first: 50,')
            self.assertEqual(ids, [1, 2, 3, 4])
            self.assertTrue(info['hasNextPage'])
            next_ids, next_info = self.page(f'first: 50, after: "{info["endCursor"]}",')
            self.assertEqual(next_ids, [5, 6, 7, 8])
            self.assertTrue(next_info['hasNextPage'])
            last_ids, last_info = self.page(f'first: 50, after: "{next_info["endCursor"]}",')
            self.assertEqual(last_ids, [9])
            self.assertFalse(last_info['hasNextPage'])

    def test_oversized_last_is_clamped(self):
        with patch.object(settings, 'MAX_PAGE_SIZE', 3):
            ids, info = self.page('last: 50,')
            self.assertEqual(ids, [7, 8, 9])
            self.assertTrue(info['hasPreviousPage'])

    def test_no_page_args_returns_at_most_limit(self):
        with patch.object(settings, 'MAX_PAGE_SIZE', 5):
            ids, info = self.page()
            self.assertEqual(ids, [1, 2, 3, 4, 5])
            self.assertTrue(info['hasNextPage'])

    def test_clamp_is_logged(self):
        with patch.object(settings, 'MAX_PAGE_SIZE', 2):
            with self.assertLogs('grapinator.schema', level='DEBUG') as captured:
                self.page('first: 3,')
        self.assertTrue(any('Page size clamped' in line for line in captured.output))


if __name__ == '__main__':
    unittest.main()
