# Documentation for grapinator schema

## Introduction
The schema you define for this code is the core of the program's operation.  This is where you define the database tables, primary keys, dynamically created SQLAlchemy classes, table relationships, and all the associated Graphene definitions for your specific needs.  From this file, grapinator is able to dynamically generate at runtime a fully functional GraphQL query service.

### Dictionary definition
In simple terms the grapinator schema is a list of Python dictionaries.  Each dictionary within the list contains all the elements that define a specific table to graph, including further lists of dictionaries that define each column you wish to expose from the database and their relationships to other tables.

### Dictionary elements
- **GQL_CLASS_NAME:** The name of the class for GraphQL
- **GQL_CONN_QUERY_NAME:** The name to use within a query
- **DB_CLASS_NAME:** The name of the SQLAlchemy model class
- **DB_TABLE_NAME:** The name of the table in the database
- **DB_TABLE_PK:** The column name of the primary key used by the database
- **DB_DEFAULT_SORT_COL:** Default sort column
- **AUTH_ROLES:** *(Optional)* Entity-level role gate — list of role strings required to query
  this entity at all.  Callers whose roles do not intersect this list receive an empty result
  set (not a 401).  Omit or set to `None` / `[]` for public entities (no restriction).
  See [RBAC — Role-based access control](#rbac--role-based-access-control) for full details.
- **FIELDS:** List of dictionaries defining each column to expose
    - **gql_col_name:** GraphQL column name
    - **gql_type:** Graphene type
    - **gql_description:** Description string for the GraphiQL web browser
    - **gql_deprecation_reason:** *(Optional)* Marks the field as deprecated in the GraphQL schema. The string value is displayed in GraphiQL's schema explorer as the reason for deprecation. Deprecated fields are hidden in GraphiQL by default but remain fully queryable. Omit this key (or set it to `None`) for non-deprecated fields.
    - **gql_auth_roles:** *(Optional)* Field-level role gate — list of role strings required to
      read this field.  Callers without a matching role receive `null` for this field; they can
      still query and see the field in the schema (introspection is unrestricted).  Omit or set
      to `None` / `[]` for public fields (no restriction).
    - **db_col_name:** Database column name.  
    - **db_type:** SQLAlchemy database type
- **RELATIONSHIPS:** List of dictionaries containing SQLAlchemy class model [relationships](https://docs.sqlalchemy.org/en/13/orm/relationship_api.html#sqlalchemy.orm.relationship)
    - **rel_name:** SQLAlchemy relationship name
    - **rel_class_name:** SQLAlchemy model class name
    - **rel_arguments:** Dictionary of elements to pass to database class constructor
        - **foreign_keys:** Foreign keys in this relationship
        - **primaryjoin:** SQLAlchemy join

### Schema File Location

The complete grapinator schema definition is located at: `grapinator/resources/schema.dct`

### Complete Annotated Schema from grapinator/resources/schema.dct

Below is the complete schema from the actual file with detailed annotations explaining what each element does:

```python
[
    # =============================================================================
    # EMPLOYEES TABLE - Central entity representing company employees
    # =============================================================================
    {
        'GQL_CLASS_NAME': 'Employees',                    # The GraphQL type name that clients will use in queries
        'GQL_CONN_QUERY_NAME': 'employees',              # The root query field name for accessing employees
        'DB_CLASS_NAME': 'db_Employees',                 # SQLAlchemy model class name (dynamically created)
        'DB_TABLE_NAME': 'Employees',                    # Actual database table name
        'DB_TABLE_PK': 'EmployeeID',                     # Primary key column in the database
        'DB_DEFAULT_SORT_COL': 'EmployeeID',             # Default column for sorting results
        'FIELDS': [
            # Primary key field - directly queryable
            {
                'gql_col_name': 'employee_id',            # GraphQL field name (snake_case)
                'gql_type': graphene.Int,                 # GraphQL type (maps to database Integer)
                'gql_description': 'Employee id (PK).',   # Description shown in GraphiQL documentation
                'db_col_name': 'EmployeeID',              # Database column name (usually PascalCase)
                'db_type': Integer                        # SQLAlchemy type for database column
            },
            # Standard string fields for employee information
            {
                'gql_col_name': 'first_name',
                'gql_type': graphene.String,
                'gql_description': 'Employee first name.',
                'db_col_name': 'FirstName',
                'db_type': String
            },
            {
                'gql_col_name': 'last_name',
                'gql_type': graphene.String,
                'gql_description': 'Employee last name.',
                'db_col_name': 'LastName',
                'db_type': String
            },
            {
                'gql_col_name': 'title',
                'gql_type': graphene.String,
                'gql_description': 'Employee title.',
                'db_col_name': 'Title',
                'db_type': String
            },
            {
                'gql_col_name': 'title_of_courtesy',
                'gql_type': graphene.String,
                'gql_description': 'Employee title of courtesy.',
                'db_col_name': 'TitleOfCourtesy',
                'db_type': String
            },
            # Date fields using GraphQL DateTime type
            {
                'gql_col_name': 'birth_date',
                'gql_type': graphene.DateTime,             # DateTime type for proper date/time handling
                'gql_description': 'Employee birth date.',
                'db_col_name': 'BirthDate',
                'db_type': Date                           # SQLAlchemy Date type
            },
            {
                'gql_col_name': 'hire_date',
                'gql_type': graphene.DateTime,
                'gql_description': 'Employee hire date.',
                'db_col_name': 'HireDate',
                'db_type': Date
            },
            # Address and contact information fields
            {
                'gql_col_name': 'address',
                'gql_type': graphene.String,
                'gql_description': 'Employee address.',
                'db_col_name': 'Address',
                'db_type': String
            },
            {
                'gql_col_name': 'city',
                'gql_type': graphene.String,
                'gql_description': 'Employee city.',
                'db_col_name': 'City',
                'db_type': String
            },
            {
                'gql_col_name': 'region',
                'gql_type': graphene.String,
                'gql_description': 'Employee region.',
                'db_col_name': 'Region',
                'db_type': String
            },
            {
                'gql_col_name': 'postal_code',
                'gql_type': graphene.String,
                'gql_description': 'Employee postal code.',
                'db_col_name': 'PostalCode',
                'db_type': String
            },
            {
                'gql_col_name': 'country',
                'gql_type': graphene.String,
                'gql_description': 'Employee country.',
                'db_col_name': 'Country',
                'db_type': String
            },
            {
                'gql_col_name': 'home_phone',
                'gql_type': graphene.String,
                'gql_description': 'Employee home phone.',
                'db_col_name': 'HomePhone',
                'db_type': String
            },
            {
                'gql_col_name': 'extension',
                'gql_type': graphene.String,
                'gql_description': 'Employee extension.',
                'db_col_name': 'Extension',
                'db_type': String
            },
            {
                'gql_col_name': 'notes',
                'gql_type': graphene.String,
                'gql_description': 'Employee notes.',
                'db_col_name': 'Notes',
                'db_type': String
            },
            # Foreign key field (references another employee - manager)
            {
                'gql_col_name': 'reports_to',
                'gql_type': graphene.Int,
                'gql_description': 'Employee reports to.',
                'db_col_name': 'ReportsTo',
                'db_type': Integer
            },
            {
                'gql_col_name': 'photo_path',
                'gql_type': graphene.String,
                'gql_description': 'Employee photo path.',
                'db_col_name': 'PhotoPath',
                'db_type': String
            },
            # RELATIONSHIP FIELDS - These are not directly queryable but provide navigation
            {
                'gql_isqueryable': False,                 # Cannot filter/sort by this field
                'gql_col_name': 'employee_territories',   # Field name for accessing related territories
                'gql_of_type': 'grapinator.schema.EmployeeTerritories',  # Target GraphQL type
                'gql_type': graphene.List,                # This field returns a list of objects
                'gql_description': 'Employee territories.',
                'db_col_name': 'employee_territories',    # Relationship name in SQLAlchemy
                'db_type': String                         # Placeholder type for relationship fields
            },
            {
                'gql_isqueryable': False,
                'gql_col_name': 'orders',                 # Navigate to orders assigned to this employee
                'gql_of_type': 'grapinator.schema.Orders',
                'gql_type': graphene.List,
                'gql_description': 'Orders for employee.',
                'db_col_name': 'orders',
                'db_type': String
            },
        ],
        # RELATIONSHIPS - Define how this table connects to others via SQLAlchemy relationships
        'RELATIONSHIPS': [
            {
                'rel_name': 'employee_territories',      # Relationship accessor name
                'rel_class_name': 'db_EmployeeTerritories',  # Target SQLAlchemy model class
                'rel_arguments': {                        # Arguments passed to SQLAlchemy relationship()
                    'foreign_keys': '[db_EmployeeTerritories.employee_id]',      # FK in related table
                    'primaryjoin': 'db_EmployeeTerritories.employee_id == db_Employees.employee_id',  # Join condition
                    'uselist': True                       # Returns a list (one-to-many)
                }
            },
            {
                'rel_name': 'orders',
                'rel_class_name': 'db_Orders',
                'rel_arguments': {
                    'foreign_keys': '[db_Orders.employee_id]',
                    'primaryjoin': 'db_Orders.employee_id == db_Employees.employee_id',
                    'uselist': True
                }
            },
        ]
    },
    
    # =============================================================================
    # EMPLOYEE_TERRITORIES TABLE - Junction table linking employees to territories
    # =============================================================================
    {
        'GQL_CLASS_NAME': 'EmployeeTerritories',
        'GQL_CONN_QUERY_NAME': 'employee_territories',
        'DB_CLASS_NAME': 'db_EmployeeTerritories',
        'DB_TABLE_NAME': 'EmployeeTerritories',
        'DB_TABLE_PK': 'TerritoryID',
        'DB_DEFAULT_SORT_COL': 'TerritoryID',
        'FIELDS': [
            {
                'gql_col_name': 'territory_id',
                'gql_type': graphene.Int,
                'gql_description': 'Territory id (PK).',
                'db_col_name': 'TerritoryID',
                'db_type': Integer
            },
            {
                'gql_col_name': 'employee_id',
                'gql_type': graphene.Int,
                'gql_description': 'Employee id.',
                'db_col_name': 'EmployeeID',
                'db_type': Integer
            },
            # Bidirectional relationships allow navigation in both directions
            {
                'gql_isqueryable': False,
                'gql_col_name': 'employees',              # Navigate back to employee records
                'gql_of_type': 'grapinator.schema.Employees',
                'gql_type': graphene.List,
                'gql_description': 'Employee assigned to territories.',
                'db_col_name': 'employees',
                'db_type': String
            },
            {
                'gql_isqueryable': False,
                'gql_col_name': 'territories',            # Navigate to territory records
                'gql_of_type': 'grapinator.schema.Territories',
                'gql_type': graphene.List,
                'gql_description': 'Territories.',
                'db_col_name': 'territories',
                'db_type': String
            },
        ],
        'RELATIONSHIPS': [
            {
                'rel_name': 'employees',
                'rel_class_name': 'db_Employees',
                'rel_arguments': {
                    'foreign_keys': '[db_Employees.employee_id]',
                    'primaryjoin': 'db_Employees.employee_id == db_EmployeeTerritories.employee_id',
                    'uselist': True
                }
            },
            {
                'rel_name': 'territories',
                'rel_class_name': 'db_Territories',
                'rel_arguments': {
                    'foreign_keys': '[db_Territories.territory_id]',
                    'primaryjoin': 'db_Territories.territory_id == db_EmployeeTerritories.territory_id',
                    'uselist': True
                }
            },
        ]
    },
    
    # Additional tables continue with similar patterns...
    # Each table follows the same structure with appropriate fields and relationships
    
    # =============================================================================
    # TERRITORIES TABLE - Geographic territories for sales
    # =============================================================================
    {
        'GQL_CLASS_NAME': 'Territories',
        'GQL_CONN_QUERY_NAME': 'territories',
        'DB_CLASS_NAME': 'db_Territories',
        'DB_TABLE_NAME': 'Territories',
        'DB_TABLE_PK': 'TerritoryID',
        'DB_DEFAULT_SORT_COL': 'TerritoryID',
        'FIELDS': [
            {
                'gql_col_name': 'territory_id',
                'gql_type': graphene.Int,
                'gql_description': 'Territory id (PK).',
                'db_col_name': 'TerritoryID',
                'db_type': Integer
            },
            {
                'gql_col_name': 'territory_description',
                'gql_type': graphene.String,
                'gql_description': 'Territory description.',
                'db_col_name': 'TerritoryDescription',
                'db_type': String
            },
            {
                'gql_col_name': 'region_id',               # Foreign key to Regions table
                'gql_type': graphene.Int,
                'gql_description': 'Region id.',
                'db_col_name': 'RegionID',
                'db_type': Integer
            },
            {
                'gql_isqueryable': False,
                'gql_col_name': 'region',                 # Navigate to parent region
                'gql_of_type': 'grapinator.schema.Regions',
                'gql_type': graphene.List,
                'gql_description': 'Region for territory.',
                'db_col_name': 'region',
                'db_type': String
            },
        ],
        'RELATIONSHIPS': [
            {
                'rel_name': 'region',
                'rel_class_name': 'db_Regions',
                'rel_arguments': {
                    'foreign_keys': '[db_Regions.region_id]',
                    'primaryjoin': 'db_Regions.region_id == db_Territories.region_id',
                    'uselist': True
                }
            },
        ]
    },

    # Continue with remaining tables...
    # (The pattern continues for all remaining tables: Regions, Customers, Orders, etc.)
    # Each table maintains consistent structure and appropriate relationships
]
```

### Key Schema Pattern Elements

**Table Definition Pattern:**
- Each table entry contains metadata about the GraphQL and database representations
- Class names follow consistent patterns: `GQL_CLASS_NAME` for GraphQL, `DB_CLASS_NAME` for SQLAlchemy
- Query names are typically lowercase plurals for accessing collections

**Field Types:**
- **Queryable fields**: Regular database columns that can be used in filters and sorting
- **Relationship fields**: Marked with `'gql_isqueryable': False` - used for navigation only
- **Deprecated fields**: Marked with `'gql_deprecation_reason': '<reason text>'` - still queryable but surfaced as deprecated in GraphiQL
- **Type mapping**: GraphQL types (Int, String, DateTime, Float) map to SQLAlchemy types (Integer, String, Date, Numeric)

**Deprecating a Field:**

Add the optional `gql_deprecation_reason` key to any field you want to retire without removing it from the API. GraphiQL will hide the field by default and display the reason text when "Show Deprecated Fields" is toggled on.

```python
{
    'gql_col_name': 'model',
    'gql_type': graphene.String,
    'gql_deprecation_reason': 'Deprecated. Use model_number instead.',  # optional
    'db_col_name': 'MODEL',
    'db_type': String
},
{
    'gql_col_name': 'model_number',
    'gql_type': graphene.String,
    'gql_description': 'Manufacturer model number.',
    'db_col_name': 'MODEL_NUMBER',
    'db_type': String
},
```

**Relationships:**
- Use SQLAlchemy relationship syntax for defining table joins
- `foreign_keys` specify which columns are foreign keys
- `primaryjoin` defines the exact join condition
- `uselist: True` indicates one-to-many relationships (returns lists)

This schema enables grapinator to automatically generate a fully functional GraphQL API with proper relationships, type safety, and query capabilities.


---

## RBAC — Role-based access control

Grapinator supports two granularities of role-based access control, both declared inline in
`schema.dct`.  Auth is **off by default** — omitting both keys leaves everything public and
fully backward compatible.

Auth mode must be enabled in `grapinator.ini` for RBAC to take effect.  With `AUTH_MODE = off`
(the default), all RBAC declarations are silently ignored and every caller receives the full
data set.  See [grapinator_ini.md](grapinator_ini.md) for configuration details.

> **Important — use `svc_cherrypy.py` when testing RBAC:**
> JWT authentication is enforced by `BearerAuthMiddleware`, which is only inserted into the
> WSGI stack when the service runs under the CherryPy production server.  Flask's built-in
> development server (`grapinator/app.py` / `flask run`) does **not** invoke the middleware,
> so `Authorization` headers are silently ignored and role-restricted fields return their
> real values for all callers.  To test RBAC end-to-end, always start the server with:
>
> ```bash
> python grapinator/svc_cherrypy.py
> ```

### Entity-level access: `AUTH_ROLES`

`AUTH_ROLES` is a top-level key on the entity dictionary.  It gates access to the **entire
entity** (all rows).  Callers whose JWT roles do not intersect the list receive an empty result
set — not a 401.  This keeps the API contract consistent and prevents information leakage about
whether the entity even exists.

```python
{
    'GQL_CLASS_NAME': 'SalaryBands',
    'GQL_CONN_QUERY_NAME': 'salary_bands',
    'DB_CLASS_NAME': 'db_SalaryBands',
    'DB_TABLE_NAME': 'SalaryBands',
    'DB_TABLE_PK': 'BandID',
    'DB_DEFAULT_SORT_COL': 'BandID',
    # Only callers with the 'hr' OR 'finance' role see any rows.
    # All other callers get an empty result set.
    'AUTH_ROLES': ['hr', 'finance'],
    'FIELDS': [ ... ],
    'RELATIONSHIPS': [],
}
```

- A list means "any one of these roles is sufficient" (logical OR).
- An empty list `[]` or absent key means no restriction (public).

### Field-level access: `gql_auth_roles`

`gql_auth_roles` is an optional key inside a field descriptor.  It gates access to a **single
field**.  The entity query itself is allowed for all callers; only the protected field returns
`null` for callers who lack the required role.  Auth-restricted fields are still fully
introspectable — they appear in the schema but resolve to `null` for unauthorised callers.

```python
'FIELDS': [
    {
        'gql_col_name': 'salary',
        'gql_type': graphene.Float,
        'gql_description': 'Employee salary — HR and finance only.',
        'db_col_name': 'Salary',
        'db_type': Float,
        # Only callers with the 'hr' OR 'finance' role receive the real value.
        # All other callers receive null for this field.
        'gql_auth_roles': ['hr', 'finance'],
    },
    {
        'gql_col_name': 'first_name',
        'gql_type': graphene.String,
        'gql_description': 'Employee first name.',
        'db_col_name': 'FirstName',
        'db_type': String,
        # No gql_auth_roles key -> public field, no restriction.
    },
]
```

### Combining both levels

You can stack `AUTH_ROLES` and `gql_auth_roles` on the same entity.  For example: the entity
is visible to all authenticated users (`AUTH_ROLES` absent), but the `salary` field within it
is restricted to HR (`gql_auth_roles: ['hr']`).

### Role name conventions

Role names are arbitrary strings.  They must match the values in the JWT roles claim exactly
(case-sensitive).  The roles claim name and its location inside the token are controlled by
`AUTH_ROLES_CLAIM` in `grapinator.ini` (default: `roles`).

#### Azure Entra ID

Define App Roles in your App Registration with the desired `Value` strings (e.g. `hr`,
`finance`).  An Entra ID admin assigns users or groups to each role.  The token's `roles`
claim will contain the `Value` strings — so those values must match what you put in
`gql_auth_roles` / `AUTH_ROLES`.  You (the App Owner) define the role names; only the
assignment of people to roles requires an admin.

#### Keycloak

Roles are defined in the Realm and assigned to users or groups.  With
`AUTH_ROLES_CLAIM = realm_access.roles`, the claim inside the token is a list of realm-role
names.

#### Auth0

Use Actions or Rules to embed a custom claim (e.g. `https://grapinator/roles`) containing a
list of role names, then set `AUTH_ROLES_CLAIM = https://grapinator/roles`.

### Complete example — mixed public and restricted data

```python
[
    # PUBLIC entity — no AUTH_ROLES, no field-level restrictions
    {
        'GQL_CLASS_NAME': 'Products',
        'GQL_CONN_QUERY_NAME': 'products',
        'DB_CLASS_NAME': 'db_Products',
        'DB_TABLE_NAME': 'Products',
        'DB_TABLE_PK': 'ProductID',
        'DB_DEFAULT_SORT_COL': 'ProductID',
        # No AUTH_ROLES key -> public, no token required in mixed mode
        'FIELDS': [
            {
                'gql_col_name': 'product_id',
                'gql_type': graphene.Int,
                'gql_description': 'PK.',
                'db_col_name': 'ProductID',
                'db_type': Integer,
            },
            {
                'gql_col_name': 'product_name',
                'gql_type': graphene.String,
                'gql_description': 'Name.',
                'db_col_name': 'ProductName',
                'db_type': String,
            },
            {
                # Cost price is visible only to buyers and managers
                'gql_col_name': 'unit_cost',
                'gql_type': graphene.Float,
                'gql_description': 'Cost price (buyers/managers only).',
                'db_col_name': 'UnitCost',
                'db_type': Float,
                'gql_auth_roles': ['buyer', 'manager'],
            },
        ],
        'RELATIONSHIPS': [],
    },

    # RESTRICTED entity — only hr role can query this table at all
    {
        'GQL_CLASS_NAME': 'EmployeeSalaries',
        'GQL_CONN_QUERY_NAME': 'employee_salaries',
        'DB_CLASS_NAME': 'db_EmployeeSalaries',
        'DB_TABLE_NAME': 'EmployeeSalaries',
        'DB_TABLE_PK': 'SalaryID',
        'DB_DEFAULT_SORT_COL': 'SalaryID',
        'AUTH_ROLES': ['hr'],   # entity-level gate
        'FIELDS': [
            {
                'gql_col_name': 'salary_id',
                'gql_type': graphene.Int,
                'gql_description': 'PK.',
                'db_col_name': 'SalaryID',
                'db_type': Integer,
            },
            {
                'gql_col_name': 'employee_id',
                'gql_type': graphene.Int,
                'gql_description': 'FK.',
                'db_col_name': 'EmployeeID',
                'db_type': Integer,
            },
            {
                'gql_col_name': 'salary',
                'gql_type': graphene.Float,
                'gql_description': 'Annual salary.',
                'db_col_name': 'Salary',
                'db_type': Float,
            },
        ],
        'RELATIONSHIPS': [],
    },
]
```

With `AUTH_MODE = mixed` in `grapinator.ini`:

| Caller | `products` query | `products.unit_cost` field | `employee_salaries` query |
|--------|-----------------|---------------------------|--------------------------|
| No token (unauthenticated) | rows returned | `null` (no `buyer`/`manager` role) | Empty result set |
| Token with `['buyer']` | rows returned | real value | Empty result set |
| Token with `['hr']` | rows returned | `null` (no `buyer`/`manager` role) | rows returned |
| Token with `['buyer', 'hr']` | rows returned | real value | rows returned |
