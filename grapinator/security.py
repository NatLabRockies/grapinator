"""Request-scoped authorization criteria for SQLAlchemy ORM queries."""

from sqlalchemy import and_, event, false
from sqlalchemy.orm import Session, with_loader_criteria


REQUEST_CONTEXT_KEY = 'grapinator.security_context'
_MODEL_POLICIES = {}


def register_model_policy(model, roles=None, row_auth_claims=None):
    """Register entity roles and model-attribute-to-claim row predicates."""
    row_auth_claims = row_auth_claims or {}
    if not isinstance(row_auth_claims, dict):
        raise ValueError('ROW_AUTH_CLAIMS must map ORM attributes to JWT claim paths.')
    if isinstance(roles, str):
        raise ValueError('Entity authorization roles must be a list of role names.')
    for attribute, claim_path in row_auth_claims.items():
        mapped_property = getattr(getattr(model, attribute, None), 'property', None)
        if (
            not hasattr(mapped_property, 'columns')
            or not mapped_property.columns
            or not isinstance(claim_path, str)
            or not claim_path.strip()
        ):
            raise ValueError(
                f'Row authorization attribute {attribute!r} is not a mapped '
                f'column with a claim path on {model.__name__}.'
            )
    _MODEL_POLICIES[model] = {
        'roles': tuple(roles or ()),
        'row_auth_claims': dict(row_auth_claims),
    }


def set_request_context(session, context):
    """Bind the current GraphQL identity to its request-scoped ORM session."""
    session.info[REQUEST_CONTEXT_KEY] = context or {}


def _claim_value(claims, claim_path):
    value = claims
    for part in claim_path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
        if value is None:
            return None
    return value


@event.listens_for(Session, 'do_orm_execute')
def _apply_request_policies(execute_state):
    """Apply policies to ORM selects, including relationship and identity loads."""
    if not execute_state.is_select or not _MODEL_POLICIES:
        return

    context = execute_state.session.info.get(REQUEST_CONTEXT_KEY, {})
    user_roles = set(context.get('user_roles') or ())
    user_claims = context.get('user_claims') or {}
    statement = execute_state.statement

    for model, policy in _MODEL_POLICIES.items():
        criteria = []
        required_roles = policy['roles']
        if required_roles and not user_roles.intersection(required_roles):
            criteria.append(false())

        for attribute, claim_path in policy['row_auth_claims'].items():
            claim = _claim_value(user_claims, claim_path)
            if not isinstance(claim, (str, int, float, bool)):
                criteria.append(false())
            else:
                criteria.append(getattr(model, attribute) == claim)

        if criteria:
            statement = statement.options(
                with_loader_criteria(
                    model,
                    and_(*criteria),
                    include_aliases=True,
                )
            )

    execute_state.statement = statement