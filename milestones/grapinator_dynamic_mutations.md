# Grapinator: Dynamic Mutations via Schema File

## Yes — Dynamic Mutations Are Feasible

The codebase's existing patterns extend naturally to mutations. The same `type()` dynamic class factory approach used for `SQLAlchemyObjectType` subclasses can generate `graphene.Mutation` subclasses. Here's what would need to change, and where the friction points are.

---

## What the current machinery already gives you

- `schema.dct` is the single source of truth for each entity's fields and types — that metadata is exactly what mutation `Arguments` classes need.
- `gql_class_constructor()` in `grapinator/schema.py` proves `type()` works with Graphene's metaclass-heavy types.
- `db_session` is already imported into `schema.py` via `from grapinator.model import *`.
- The final `gql_schema = graphene.Schema(query=Query, ...)` at the bottom of `grapinator/schema.py` just needs `mutation=Mutation` added — there's a natural hook.

---

## Changes Required

### 1. Extend `schema.dct` per entity

Add a `MUTATIONS` list alongside `FIELDS` and `RELATIONSHIPS`:

```python
'MUTATIONS': [
    {
        'mutation_name': 'create_employee',   # GraphQL mutation field name
        'operation': 'create',                # 'create' | 'update' | 'delete'
        'input_fields': ['first_name', 'last_name', 'title'],  # subset of gql_col_names
    },
    {
        'mutation_name': 'update_employee',
        'operation': 'update',
        'pk_field': 'employee_id',            # required for update/delete
        'input_fields': ['first_name', 'last_name'],
    },
    {
        'mutation_name': 'delete_employee',
        'operation': 'delete',
        'pk_field': 'employee_id',
    },
],
```

No new fields are needed in `FIELDS` itself — the field types/names are already there and reusable.

---

### 2. Add `_make_mutation_classes()` to `SchemaSettings` in `settings.py`

The method cross-references `MUTATIONS` entries against `FIELDS` to resolve types, then stores a flat list of mutation descriptors alongside `_gql_classes`. It would produce dicts like:

```python
{
    'mutation_name': 'create_employee',
    'operation': 'create',
    'gql_class': 'Employees',         # return type (for create/update)
    'db_class': 'db_Employees',       # SQLAlchemy model name
    'pk_field': None,                 # or 'employee_id' for update/delete
    'input_fields': [                 # resolved field descriptors
        {'name': 'first_name', 'type': graphene.String, ...},
        ...
    ]
}
```

---

### 3. Add `mutation_class_constructor()` to `schema.py`

This is the core factory. A `graphene.Mutation` subclass requires:
- An `Arguments` inner class with the input fields
- A `mutate` classmethod (or staticmethod) that performs the DB operation
- Output fields on the class itself (what the mutation returns)

```python
def mutation_class_constructor(descriptor, db_clazz, return_gql_clazz):
    # Build Arguments inner class dynamically
    args_attrs = {}
    for f in descriptor['input_fields']:
        args_attrs[f['name']] = f['type'](f['type_args'])
    Arguments = type('Arguments', (), args_attrs)

    # Generic mutate implementations keyed by operation
    def _mutate_create(root, info, **kwargs):
        obj = db_clazz(**{f['name']: kwargs.get(f['name']) for f in descriptor['input_fields']})
        db_session.add(obj)
        db_session.commit()
        return obj

    def _mutate_update(root, info, **kwargs):
        pk_val = kwargs.pop(descriptor['pk_field'])
        obj = db_session.get(db_clazz, pk_val)
        for k, v in kwargs.items():
            if v is not None:
                setattr(obj, k, v)
        db_session.commit()
        return obj

    def _mutate_delete(root, info, **kwargs):
        obj = db_session.get(db_clazz, kwargs[descriptor['pk_field']])
        db_session.delete(obj)
        db_session.commit()
        return obj

    op = descriptor['operation']
    mutate_fn = {'create': _mutate_create, 'update': _mutate_update, 'delete': _mutate_delete}[op]

    return_field_name = descriptor['gql_class'][0].lower() + descriptor['gql_class'][1:]  # e.g. 'employees'
    mutation_attrs = {
        'Arguments': Arguments,
        return_field_name: graphene.Field(return_gql_clazz),
        'mutate': classmethod(mutate_fn),   # or staticmethod depending on graphene version
    }
    return type(str(descriptor['mutation_name']), (graphene.Mutation,), mutation_attrs)
```

---

### 4. Build `Mutation` root type dynamically in `schema.py`

Parallel to how `Query` is built:

```python
mutation_attrs = {'node': relay.Node.Field()}
for m in schema_settings.get_mutation_classes():
    gql_cls = globals()[m['gql_class']]
    db_cls  = globals()[m['db_class']]
    mutation_class = mutation_class_constructor(m, db_cls, gql_cls)
    mutation_attrs[m['mutation_name']] = mutation_class.Field()

Mutation = type('Mutation', (graphene.ObjectType,), mutation_attrs)

gql_schema = graphene.Schema(query=Query, mutation=Mutation, auto_camelcase=False)
```

---

## Known Friction Points

| Issue | Mitigation |
|---|---|
| `graphene.Mutation`'s metaclass processes `Arguments` at class creation time — `type()` may not trigger it the same way as a `class` statement | Test with a single entity first; if needed, use `graphene.Mutation.__init_subclass__` mechanics or call `graphene.Mutation._meta` directly after construction |
| `mutate` must be a `classmethod` in Graphene 3.x | Wrap with `classmethod()` as shown above — same applies as for resolver functions already in the codebase |
| `db_session` is module-level and not thread-local-safe across mutations | Already fine — `db_session` in `model.py` is a `scoped_session` which handles thread safety |
| Validation (required fields, FK integrity) has no natural slot | Either add a `validators` key to the mutation descriptor (list of callables), or rely on SQLAlchemy constraint errors surfaced through Graphene's error handling |
| Hidden or resolver-only fields in `FIELDS` shouldn't be in mutation `Arguments` | Filter them by `ishidden` and `isresolver` in `_make_mutation_classes()`, same as queries already do |

---

## Alternative: Data-Driven Classes Without `type()`

If `graphene.Mutation` + `type()` proves difficult due to metaclass edge cases, define mutations in a **separate Python module** (e.g. `grapinator/mutations.py`) that is referenced from `grapinator.ini` and imported conditionally at startup. Mutations there are still "data-driven" (they loop over `schema_settings.get_gql_classes()` and a per-entity config) but written as real Python classes instead of `type()` calls.

The `schema.dct` additions (`MUTATIONS`) would still apply — the difference is only where the class construction code lives and whether it uses `type()` or a `class` statement inside a loop.
