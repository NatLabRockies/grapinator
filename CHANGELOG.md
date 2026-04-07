# Changelog

All notable changes to the GraphQL Integration Testing Suite.

## [2.1.3] - 2026-04-07

### Added

- **Structured logging across all modules** — every module now uses a named
  child logger under the `grapinator` hierarchy so output is routed through
  the existing `logging.conf` configuration with no changes to that file.

  | Module | Logger name | Key events |
  |--------|-------------|------------|
  | `__init__.py` | `grapinator` | `INFO` config/schema loaded; `CRITICAL` on fatal startup error |
  | `settings.py` | `grapinator.settings` | `DEBUG` file resolution; `WARNING` when `AUTH_DEV_SECRET` is set |
  | `model.py` | `grapinator.model` | `INFO` engine created + ORM count; `DEBUG` per-class registration |
  | `schema.py` | `grapinator.schema` | `INFO` type count + schema compiled; `DEBUG` per-type build + RBAC decisions |
  | `app.py` | `grapinator.app` | `INFO` endpoint registered; `DEBUG` per-request auth state |
  | `svc_cherrypy.py` | `grapinator.svc_cherrypy` | `INFO` server bind; `DEBUG` middleware stack layers |
  | `auth.py` | `grapinator.auth` | `INFO` middleware init; `WARNING` dev-secret or failed token; `DEBUG` all pass-through paths |

- **`logging.config.fileConfig` fix** — `disable_existing_loggers=False` passed
  so child loggers created during imports are not silenced by `fileConfig`.

- **`tests/test_logging.py`** — 33 new tests (2 conditionally skipped when the
  default schema has no entity auth roles) verifying:
  - Correct logger names for all modules
  - Log levels: `DEBUG` for routine decisions, `INFO` for startup milestones,
    `WARNING` for security-relevant events (dev secret, invalid/missing tokens)
  - All `BearerAuthMiddleware.__call__` code paths emit the right level
  - `app.py` per-request auth state is logged at `DEBUG`

## [2.1.2] - 2026-04-07

### Added

- **`GRAPINATOR_CONFIG` environment variable** — override the ini file loaded at
  startup without changing code.  Defaults to `/resources/grapinator.ini`.
  Follows the same pattern as the existing `GQLAPI_CRYPT_KEY` env var.
- **`docs/grapinator_ini.md`** — new "Selecting the ini file at runtime" section
  documenting `GRAPINATOR_CONFIG` with usage examples.

## [2.1.1] - 2026-04-07

### Bug Fixes

#### RBAC / JWT auth not working — three root causes (Issue #17)

- **`tests/test_rbac.sh` — wrong shebang** (`!#/bin/sh` → `#!/bin/sh`):
  The reversed characters prevented the OS from recognising the interpreter
  directive, so the script could not be executed directly.

- **`tests/test_rbac.sh` — no signing secret passed to `dev_jwt.py`** *(primary cause)*:
  `dev_jwt.py` requires `--secret` or `GRAPINATOR_DEV_SECRET`.  Neither was
  provided, so the tool exited with an error, `TOKEN` was empty, and curl sent
  `Authorization: Bearer ` (no token).  `BearerAuthMiddleware` attempted to
  decode the empty string, failed immediately, and returned 401 — so no
  GraphQL execution occurred and `birth_date` appeared as `null` in the error
  response rather than from a resolver.  Fixed by adding
  `--secret change-me-local-dev-only` to match the `AUTH_DEV_SECRET` configured
  in `grapinator.ini`.

- **Both ini files — `Authorization` missing from `CORS_ALLOW_HEADERS`**:
  Browser preflight (`OPTIONS`) did not advertise `Authorization` as an allowed
  header, causing browsers to refuse to send the JWT when using the GraphiQL
  IDE.  Added `Authorization` to `CORS_ALLOW_HEADERS` in both
  `grapinator.ini` and `grapinator_rbac.ini`.

#### Flask dev server bypasses auth middleware

`BearerAuthMiddleware` is only inserted into the WSGI stack by `svc_cherrypy.py`.
Flask's built-in dev server (`app.py` / `flask run`) does not invoke the
middleware, so JWT tokens are silently ignored and role-restricted fields return
their real values to all callers.  Documentation and `test_rbac.sh` now
prominently note that RBAC testing requires running `svc_cherrypy.py`.

### New Files
- **`grapinator/resources/schema_rbac.dct`** — Example schema with `gql_auth_roles`
  on `birth_date` (restricted to `['admin', 'hr']`) for RBAC testing
- **`grapinator/resources/grapinator_rbac.ini`** — Matching ini with
  `AUTH_MODE = mixed` and `AUTH_DEV_SECRET` for local RBAC dev/testing
- **`tests/test_rbac.sh`** — Shell script that generates an `hr` JWT and queries
  the `birth_date` field to verify field-level RBAC end-to-end

### Tests
- **Fixed `TestSettingsAuthSection`** — tests now check `Settings` class-level
  attribute defaults rather than the loaded singleton, so they remain valid
  regardless of what `grapinator.ini` currently has configured

### Documentation
- **`docs/grapinator_ini.md`** — Added CherryPy requirement callout to the
  "Local development" section; replaced the generic curl example with the
  contents of `tests/test_rbac.sh`
- **`docs/schema_docs.md`** — Added CherryPy requirement callout at the top of
  the RBAC section

## [2.1.0] - 2026-04-06

### New Features

#### JWT Bearer Token Authentication & RBAC (Issue #17)

**IdP-agnostic JWT middleware** — validates bearer tokens against any OIDC-compatible
identity provider (Azure Entra ID, Keycloak, Auth0, …) using standard JWKS / RFC 7519
parameters.  No provider-specific logic lives in the codebase — all IdP specifics are
externalized to `grapinator.ini`.

- **Three auth modes** controlled by `AUTH_MODE` in a new `[AUTH]` ini section:
  - `off` *(default)* — zero behaviour change; existing deployments completely unaffected
  - `mixed` — unauthenticated requests reach public data; role-restricted fields/entities
    gate on the caller's JWT roles; an invalid token always returns 401
  - `required` — every request must carry a valid bearer token (except CORS preflight
    and, optionally, the GraphiQL IDE page)
- **Entity-level access control** via `AUTH_ROLES: ['role1', ...]` on any schema.dct
  entity — callers without a matching role receive an empty result set (not a 401)
- **Field-level access control** via `gql_auth_roles: ['role1', ...]` on any field —
  callers without a matching role receive `null`; the field remains introspectable
- **Dotted-path roles claim** — `AUTH_ROLES_CLAIM` supports nested JWT claims such as
  `realm_access.roles` (Keycloak) in addition to flat claims like `roles` (Entra ID)
- **GraphiQL access control** via `GRAPHIQL_ACCESS`: `authenticated` (default), `open`
  (IDE served without auth), or `off` (IDE disabled entirely)
- **Local dev JWT generator** — `tools/dev_jwt.py` generates HS256 tokens signed with
  `AUTH_DEV_SECRET` for testing without a live IdP; supports `--roles`, `--claim`,
  `--expiry`, `--print-header`

### New Files
- **`grapinator/auth.py`** — `BearerAuthMiddleware` WSGI middleware
- **`tools/dev_jwt.py`** — Local development JWT generator

### Modified Files
- **`grapinator/settings.py`** — `AUTH_*` attributes with safe defaults; optional
  `[AUTH]` INI section loading; `_make_gql_classes()` propagates `gql_auth_roles`
  and `AUTH_ROLES` from schema.dct
- **`grapinator/schema.py`** — Field-level auth resolver wrapper in
  `gql_class_constructor`; entity-level `query.filter(sql_false())` gate in
  `MyConnectionField.get_query`; `_ENTITY_AUTH_ROLES` module-level registry
- **`grapinator/app.py`** — `@before_request` threads WSGI auth state into Flask `g`;
  `context_value=_get_graphql_context` exposes `user_roles` to resolvers
- **`grapinator/svc_cherrypy.py`** — `BearerAuthMiddleware` inserted inside
  `CorsMiddleware` when `AUTH_MODE != 'off'`
- **`grapinator/resources/grapinator.ini`** — Added `[AUTH]` section (`AUTH_MODE = off`
  default; all production settings commented out with IdP examples)
- **`setup.cfg`** — Added `PyJWT[crypto]>=2.8.0` to `install_requires`

### Tests
- **Added `tests/test_bearer_auth.py`** — 70 new tests:
  - Middleware: all three modes, all token scenarios (valid, expired, wrong secret,
    malformed), CORS preflight bypass, GraphiQL access control (`open`/`authenticated`)
  - RSA/JWKS code path via self-generated key pair (no network calls)
  - Field-level RBAC: matching role returns value; missing role returns `null`;
    multi-role OR logic; public fields have no injected resolver
  - Entity-level RBAC: matching role runs query normally; missing role applies
    `filter(false())`; no `AUTH_ROLES` key means public
  - Dev JWT tool: token generation, nested claim paths, expiry enforcement,
    end-to-end validation through middleware
  - Settings defaults: all `AUTH_*` attributes verified

### Documentation
- **`docs/grapinator_ini.md`** — Full `[AUTH]` section reference: all settings,
  provider-specific examples (Azure Entra ID, Keycloak, Auth0), CORS note,
  local dev workflow with `dev_jwt.py` usage examples
- **`docs/schema_docs.md`** — Added `AUTH_ROLES` and `gql_auth_roles` to dictionary
  element reference; new **RBAC** section with entity-level/field-level/combined
  examples, role naming guide per provider, and a behaviour matrix table

## [2.0.2] - 2026-03-25

### New Features

#### GraphQL Field Deprecation Support (Issue #13)
- **Added `gql_deprecation_reason` field key** to the schema dictionary format — marks a GraphQL field as deprecated with a human-readable reason string
- Deprecated fields surface in GraphiQL's schema explorer with the reason text displayed; they are hidden by default but remain fully queryable
- `gql_deprecation_reason` is optional — fields without it continue to behave as before

#### Schema Changes
- **Deprecated `model` field** on the `Asset` type with message *"Deprecated. Use model_number instead."*

### Bug Fixes
- **Fixed `deprecation_reason` not being applied** to generated Graphene fields — the reason must be passed to the field constructor, not assigned as a post-construction attribute
- **Fixed key name mismatch** between `settings.py` (which stores the key as `deprecation_reason`) and `schema.py` (which was incorrectly looking up `gql_deprecation_reason`)
- **Fixed `_make_gql_query_fields`** to correctly scope field construction inside the `isqueryable` guard, preventing hidden/non-queryable fields from being added as filter arguments

### Tests
- **Added `test_deprecation_reason_parsed`** in `test_schema_settings.py` — verifies that `SchemaSettings` correctly parses `gql_deprecation_reason` from the schema dict into the column descriptor
- **Added `test_gql_deprecation_reason_on_fields`** in `test_gql_class_creation.py` — verifies that the mounted Graphene field on each generated type carries the expected `deprecation_reason` value

### Documentation
- **Updated `docs/schema_docs.md`** with full documentation for `gql_deprecation_reason` including field reference entry, a "Deprecated fields" bullet in key patterns, and an annotated code example

## [2.0.1] - 2026-03-12

### Bug Fixes

#### Configuration Loading Issue
- **Fixed critical bug** in `test_integration_queries.py` where YAML configuration was ignored
- Test framework was using hardcoded expected counts instead of loading from `test_config.yaml`
- Added proper YAML configuration loading with fallback to defaults
- Added `--config-file` command line parameter to specify configuration file path

#### Test Framework Improvements  
- **Enhanced `ResultValidator` class** to accept and load YAML configuration files
- **Modified `IntegrationTestSuite`** to pass configuration file to validator
- **Added PyYAML import** for proper YAML file processing
- **Improved error handling** when configuration files are missing or invalid

#### Configuration Corrections
- **Updated `test_config.yaml`** with correct expected counts based on actual database state:
  - `EmployeesByCity: 2` (corrected from 5) - Seattle employees count
  - `BeverageProductsSorted: 11` (corrected from 12) - Active beverage products count
- **Verified all expected counts** match actual database query results

### Technical Improvements

#### Validation Framework  
- **Configuration-driven validation** now properly implemented
- **Dynamic expected counts** loaded from YAML instead of hardcoded values
- **Proper test failure behavior** when expected vs actual counts don't match
- **Comprehensive logging** shows which configuration file is loaded and expected counts

#### Testing Verification
- ✅ **Test properly fails** when expected counts are incorrect (exit code 1)
- ✅ **Test properly passes** when expected counts match actual results (exit code 0) 
- ✅ **Configuration loading confirmed** with debug logging
- ✅ **Validation errors display** count mismatches clearly in output

## [2.0.0] - 2026-03-10

### Major Version Upgrade - Breaking Changes

#### Dependency Upgrades
- **Upgraded Graphene to 3.4.3+** - Major breaking change from Graphene 2.x
- **Replaced cx_Oracle with oracledb>=3.4.2** - Modern Oracle database driver
- **Added graphene-sqlalchemy==3.0.0rc2** - First Graphene 3.x compatible release
- **Replaced Flask-GraphQL with graphql-server[flask]>=3.0.0** - GraphQL Core 3.x compatibility
- **Upgraded SQLAlchemy to >=2.0.48,<2.1** - Modern SQLAlchemy 2.x support
- **Upgraded Flask to >=3.1.3** and **Flask-Cors to >=6.0.2**
- **Upgraded CherryPy to >=18.10.0**, **pylint to >=4.0.5**, **pymysql to >=1.1.2**
- **Bumped Python requirement to >=3.9** - Dropped support for older Python versions

#### GraphQL Server Modernization
- **Updated GraphQLView imports** to use `graphql_server.flask.views`
- **Fixed GraphQL schema integration** to work with Graphene 3.x
- **Added FixedGraphQLView subclass** to patch graphql-server 3.0.0 bugs:
  - Fixed `None` rendered as JavaScript identifier issue
  - Fixed `operationName`/`operation_name` snake/camel case mismatch causing SyntaxError
- **Enhanced GraphQL IDE rendering** for better development experience

### Added

#### Comprehensive Integration Testing Framework
- **Added complete test suite** with 34 GraphQL queries covering all major operations
- **Created `tests/integration_test_queries.md`** - Comprehensive query collection
- **Added `tests/test_integration_queries.py`** - Main Python test runner
- **Added `tests/test_endpoint_comparison.py`** - Advanced multi-endpoint testing
- **Created `tests/run_graphql_tests.sh`** - Convenient shell script wrapper
- **Added `tests/test_config.yaml`** - Comprehensive configuration system
- **Created `tests/README.md`** - Detailed testing documentation

#### Schema and Documentation Improvements
- **Enhanced `docs/schema_docs.md`** - Updated schema documentation
- **Updated `docs/demo_queries.md`** - Fixed examples to match Northwind schema
- **Added new relationships** in `grapinator/resources/schema.dct`
- **Removed deprecated `GQL_CONN_CLASS_NAME`** configuration option

#### Unit Testing Framework
- **Added comprehensive unit tests** covering core functionality:
  - `tests/test_connection_field.py` - Database connection testing
  - `tests/test_flask_app.py` - Flask application testing  
  - `tests/test_gql_class_creation.py` - GraphQL class generation testing
  - `tests/test_orm_class_creation.py` - ORM model testing
  - `tests/test_schema_settings.py` - Schema configuration testing
  - `tests/test_settings_class.py` - Settings validation testing

### Fixed

#### Schema Compatibility Issues
- **Fixed `schema.py`** to accept non-string values for queries (e.g., `employee_id: 1`)
- **Updated field type handling** for proper GraphQL type conversion
- **Enhanced query filter processing** for numeric and boolean types
- **Improved relationship definitions** in schema dictionary

#### Development Environment
- **Updated VSCode settings** for better pylint integration
- **Moved pylint to optional development dependencies** - No longer required for basic usage
- **Updated unittest discovery configuration** with proper arguments
- **Enhanced .gitignore** for better development workflow

#### Configuration Management
- **Updated .env file** with secure dummy key
- **Improved setup.cfg** dependency management
- **Enhanced development vs production dependency separation**

### Technical Improvements

#### Model and Schema Enhancements
- **Updated `grapinator/model.py`** for Graphene 3.x compatibility
- **Refactored `grapinator/schema.py`** with modern Graphene patterns
- **Improved type definitions** and field resolvers
- **Enhanced error handling** in GraphQL operations

#### Performance and Reliability
- **Optimized query processing** for better performance
- **Enhanced error reporting** with detailed stack traces
- **Improved connection handling** for database operations
- **Better resource management** and cleanup

### Documentation

#### Updated Documentation
- **Enhanced README.md** with updated installation and usage instructions
- **Updated schema documentation** with current field definitions
- **Added testing framework documentation** with examples and best practices
- **Improved development setup guides** for contributors

#### Migration Guide
- **Breaking changes documentation** for upgrading from 1.x to 2.x
- **Dependency update instructions** for existing installations
- **Configuration migration guide** for deprecated options
- **Testing framework integration** examples for existing projects

## [1.0.0] - 2026-03-10

### Added

#### Core Testing Framework
- **`integration_test_queries.md`** - Created comprehensive test suite with 34 GraphQL queries covering:
  - Basic entity retrieval (employees, products, customers, categories)
  - Complex relationship testing (multi-level joins)
  - Filtering and sorting operations
  - Pattern matching (contains, startswith, comparisons)
  - Performance testing with large datasets
  - Edge cases and error handling
  - Business logic validation
  - Data integrity checks

#### Test Execution Scripts
- **`test_integration_queries.py`** - Main Python test runner with features:
  - Single endpoint testing with comprehensive validation
  - Dual endpoint comparison testing
  - Performance benchmarking (response time tracking)
  - Data consistency validation
  - Configurable validation rules
  - Detailed JSON result reporting
  - Query parsing from markdown format
  
- **`test_endpoint_comparison.py`** - Advanced multi-endpoint testing framework:
  - Schema compatibility checks using GraphQL introspection
  - Concurrent query execution for improved performance
  - Comprehensive data consistency validation across endpoints
  - Performance comparison analysis between endpoints
  - Business logic rule validation
  - Flexible comparison rules (strict vs. lenient)

#### Configuration System
- **`test_config.yaml`** - Comprehensive test configuration supporting:
  - Performance thresholds for different query types
  - Expected result counts for validation
  - Business logic validation rules
  - Relationship integrity checks
  - Comparison testing settings
  - Field validation rules

#### Convenience Tools
- **`run_graphql_tests.sh`** - Shell script wrapper providing:
  - Easy dependency installation
  - Simple command interface for all test modes
  - Sample configuration file creation
  - Color-coded output and error handling
  - Verbose logging options

#### Documentation & Support
- **`README.md`** - Comprehensive documentation including:
  - Quick start guide
  - Detailed usage examples
  - Configuration options
  - Troubleshooting guide
  - CI/CD integration examples
  - Extension guidelines
  
- **`requirements-test.txt`** - Python dependencies specification
- **`sample_endpoints.json`** - Example endpoint configuration

### Technical Improvements

#### Query Parsing Engine
- Implemented robust regex-based GraphQL query extraction from markdown
- Enhanced pattern matching to handle multi-line queries with nested braces
- Added query name extraction and validation
- Improved error handling for malformed queries

#### Validation Framework
- Created configurable validation system with multiple validation types:
  - Performance validation (response time thresholds)
  - Content validation (expected results, field checks)
  - Business logic validation (custom rules)
  - Relationship validation (foreign key integrity)
- Implemented flexible comparison system with field ignoring capabilities

#### Error Handling & Logging
- Comprehensive logging system with multiple levels (INFO, DEBUG, WARNING, ERROR)
- Graceful handling of connection failures and GraphQL errors
- Detailed error reporting with context information
- Performance metrics collection and reporting

### Bug Fixes

#### Field Name Corrections
- Fixed `reports_to_id` → `reports_to` in employee queries
- Removed `units_on_order` field (not present in schema)  
- Fixed `homepage` → `home_page` in supplier queries

#### Query Parsing Issues
- Resolved regex pattern to properly capture multi-line GraphQL queries
- Fixed nested brace handling in query extraction
- Improved query validation and error reporting

#### Schema Compatibility
- Aligned all test queries with actual Northwind GraphQL schema
- Validated all field names against schema introspection
- Ensured query syntax matches GraphQL specification

### Testing & Validation

#### Test Coverage Verification
- Verified 100% success rate on all 34 test queries
- Confirmed performance benchmarks (average response time <30ms)
- Validated endpoint comparison functionality
- Tested error handling for edge cases

#### Integration Testing
- Single endpoint testing: ✅ 100% success rate
- Dual endpoint comparison: ✅ 100% match rate  
- Multi-endpoint testing: ✅ Schema compatibility verified
- CI/CD integration examples provided and tested

### Performance Metrics

- **Query Execution**: Average response time 28.3ms
- **Test Suite Runtime**: Complete suite execution <1 second
- **Concurrent Processing**: Multi-endpoint testing with thread pooling
- **Memory Efficiency**: Streaming JSON processing for large datasets

### Security & Best Practices

- Input validation for all GraphQL queries
- Secure HTTP session management
- Configurable timeout handling
- No credential exposure in logs or output

---

## Development Notes

### Architecture Decisions
- Modular design allowing independent use of components
- Configuration-driven approach for extensibility
- Clear separation of concerns (parsing, execution, validation, comparison)
- Comprehensive error handling and logging

### Testing Philosophy
- Comprehensive coverage of GraphQL operations
- Real-world business logic validation
- Performance-aware testing with configurable thresholds
- Cross-environment consistency validation

### Future Extensibility
- Plugin architecture for custom validators
- Configurable query templates
- Multiple output formats support
- Integration with testing frameworks