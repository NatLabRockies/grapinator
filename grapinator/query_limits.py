"""GraphQL operation limits and static persisted-query allowlists."""

import hashlib
import json

from graphql import GraphQLError
from graphql.language.ast import (
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    IntValueNode,
    InlineFragmentNode,
    OperationDefinitionNode,
)
from graphql import get_named_type, is_list_type, is_non_null_type
from graphql.validation import ValidationRule

from grapinator import settings


def load_persisted_queries(file_path):
    """Load a JSON mapping of SHA-256 hashes to query documents."""
    if not file_path:
        return None
    with open(file_path, encoding='utf-8') as query_file:
        persisted_queries = json.load(query_file)
    if not isinstance(persisted_queries, dict):
        raise ValueError('Persisted queries file must contain a JSON object.')

    for query_hash, query in persisted_queries.items():
        if not isinstance(query_hash, str) or not isinstance(query, str):
            raise ValueError('Persisted query entries must map hash strings to query strings.')
        expected_hash = hashlib.sha256(query.encode('utf-8')).hexdigest()
        if query_hash.lower() != expected_hash:
            raise ValueError(f'Persisted query hash does not match its document: {query_hash!r}.')
    return {query_hash.lower(): query for query_hash, query in persisted_queries.items()}


def resolve_persisted_query(query, extensions, persisted_queries):
    """Resolve and enforce an optional static persisted-query allowlist."""
    if persisted_queries is None:
        return query

    persisted_request = (extensions or {}).get('persistedQuery') or {}
    if not isinstance(persisted_request, dict):
        raise GraphQLError('Persisted query metadata must be an object.')
    query_hash = persisted_request.get('sha256Hash')
    if query_hash is not None and not isinstance(query_hash, str):
        raise GraphQLError('Persisted query hash must be a string.')
    if persisted_request and persisted_request.get('version') != 1:
        raise GraphQLError('Unsupported persisted query version.')

    if query:
        actual_hash = hashlib.sha256(query.encode('utf-8')).hexdigest()
        if query_hash and query_hash.lower() != actual_hash:
            raise GraphQLError('Persisted query hash does not match the query document.')
        if actual_hash not in persisted_queries:
            raise GraphQLError('Query is not present in the server persisted-query allowlist.')
        return query

    if query_hash and query_hash.lower() in persisted_queries:
        return persisted_queries[query_hash.lower()]
    raise GraphQLError('Persisted query is not present in the server allowlist.')


class QueryLimitsRule(ValidationRule):
    """Reject operations exceeding configured depth, size, or alias limits."""

    GQL_MAX_QUERY_DEPTH = None
    GQL_MAX_QUERY_COMPLEXITY = None
    GQL_MAX_QUERY_FIELDS = None
    GQL_MAX_ALIASES = None

    def _limit(self, setting_name):
        override = getattr(type(self), setting_name, None)
        return override if override is not None else getattr(settings, setting_name)

    def enter_document(self, document, *_args):
        fragments = {
            definition.name.value: definition
            for definition in document.definitions
            if isinstance(definition, FragmentDefinitionNode)
        }

        for operation in document.definitions:
            if isinstance(operation, OperationDefinitionNode):
                field_count, alias_count, depth, complexity = self._measure(
                    operation.selection_set,
                    fragments,
                    schema=self.context.schema,
                    parent_type=self._root_type(operation.operation.value),
                    max_field_count=self._limit('GQL_MAX_QUERY_FIELDS'),
                )
                max_depth = self._limit('GQL_MAX_QUERY_DEPTH')
                if depth > max_depth:
                    self.report_error(GraphQLError(
                        f'Query depth exceeds the limit of {max_depth}.'
                    ))
                max_fields = self._limit('GQL_MAX_QUERY_FIELDS')
                if field_count > max_fields:
                    self.report_error(GraphQLError(
                        f'Query field count exceeds the limit of {max_fields}.'
                    ))
                max_aliases = self._limit('GQL_MAX_ALIASES')
                if alias_count > max_aliases:
                    self.report_error(GraphQLError(
                        f'Query alias count exceeds the limit of {max_aliases}.'
                    ))
                max_complexity = self._limit('GQL_MAX_QUERY_COMPLEXITY')
                if complexity > max_complexity:
                    self.report_error(GraphQLError(
                        'Estimated query complexity exceeds the configured limit '
                        f'of {max_complexity}.'
                    ))

    def _root_type(self, operation):
        return {
            'query': self.context.schema.query_type,
            'mutation': self.context.schema.mutation_type,
            'subscription': self.context.schema.subscription_type,
        }.get(operation)

    @staticmethod
    def _measure(
        selection_set,
        fragments,
        depth=0,
        fragment_stack=(),
        schema=None,
        parent_type=None,
        multiplier=1,
        connection_bound=None,
        traversal_budget=None,
        max_field_count=None,
    ):
        if traversal_budget is None:
            traversal_budget = [0]
        if max_field_count is None:
            max_field_count = settings.GQL_MAX_QUERY_FIELDS
        field_count = 0
        alias_count = 0
        max_depth = depth
        complexity = 0

        for selection in selection_set.selections:
            if traversal_budget[0] > max_field_count:
                break
            if isinstance(selection, FieldNode):
                traversal_budget[0] += 1
                if traversal_budget[0] > max_field_count:
                    field_count = max_field_count + 1
                    break
                field_depth = depth + 1
                field_count += 1
                alias_count += int(selection.alias is not None)
                max_depth = max(max_depth, field_depth)
                complexity += field_depth * multiplier
                child_multiplier = multiplier
                child_connection_bound = None
                output_type = None
                if parent_type is not None:
                    field_definition = parent_type.fields.get(selection.name.value)
                    if field_definition is not None:
                        output_type = field_definition.type

                if output_type is not None:
                    unwrapped_type = output_type
                    while is_non_null_type(unwrapped_type):
                        unwrapped_type = unwrapped_type.of_type
                    named_type = get_named_type(output_type)
                    edge_field = getattr(named_type, 'fields', {}).get('edges')
                    is_connection = edge_field is not None and is_list_type(
                        edge_field.type.of_type
                        if is_non_null_type(edge_field.type) else edge_field.type
                    )
                    if is_connection:
                        child_connection_bound = QueryLimitsRule._connection_page_size(
                            selection.arguments
                        )
                        child_multiplier *= child_connection_bound
                    elif is_list_type(unwrapped_type) and connection_bound is None:
                        child_multiplier *= settings.GQL_MAX_PAGE_SIZE
                    elif is_list_type(unwrapped_type):
                        child_connection_bound = connection_bound

                if selection.selection_set:
                    child_fields, child_aliases, child_depth, child_cost = QueryLimitsRule._measure(
                        selection.selection_set,
                        fragments,
                        field_depth,
                        fragment_stack,
                        schema,
                        get_named_type(output_type) if output_type is not None else None,
                        child_multiplier,
                        child_connection_bound,
                        traversal_budget,
                        max_field_count,
                    )
                    field_count += child_fields
                    alias_count += child_aliases
                    max_depth = max(max_depth, child_depth)
                    complexity += child_cost
            elif isinstance(selection, InlineFragmentNode):
                child_fields, child_aliases, child_depth, child_cost = QueryLimitsRule._measure(
                    selection.selection_set,
                    fragments,
                    depth,
                    fragment_stack,
                    schema,
                    schema.get_type(selection.type_condition.name.value)
                    if schema and selection.type_condition else parent_type,
                    multiplier,
                    connection_bound,
                    traversal_budget,
                    max_field_count,
                )
                field_count += child_fields
                alias_count += child_aliases
                max_depth = max(max_depth, child_depth)
                complexity += child_cost
            elif isinstance(selection, FragmentSpreadNode):
                name = selection.name.value
                fragment = fragments.get(name)
                if fragment is not None and name not in fragment_stack:
                    child_fields, child_aliases, child_depth, child_cost = QueryLimitsRule._measure(
                        fragment.selection_set,
                        fragments,
                        depth,
                        fragment_stack + (name,),
                        schema,
                        schema.get_type(fragment.type_condition.name.value)
                        if schema else parent_type,
                        multiplier,
                        connection_bound,
                        traversal_budget,
                        max_field_count,
                    )
                    field_count += child_fields
                    alias_count += child_aliases
                    max_depth = max(max_depth, child_depth)
                    complexity += child_cost

        return field_count, alias_count, max_depth, complexity

    @staticmethod
    def _connection_page_size(arguments):
        page_size = settings.GQL_MAX_PAGE_SIZE
        for argument in arguments:
            if argument.name.value in ('first', 'last'):
                if isinstance(argument.value, IntValueNode):
                    page_size = min(int(argument.value.value), page_size)
                break
        return max(1, page_size)