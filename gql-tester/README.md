# gql-tester

GraphQL endpoint integration test runner for Grapinator APIs.

## Installation

Clone the `gql-tester` directory to wherever you want to install it, then run `setup` to
create a self-contained virtual environment with all dependencies. Nothing is installed to
your system or base Python.

```bash
# Clone the grapinator repo and copy (or symlink) just the gql-tester subdirectory,
# or sparse-clone directly:
git clone --filter=blob:none --sparse https://github.com/NatLabRockies/grapinator.git /opt/tools/gql-tester
cd /opt/tools/gql-tester
git sparse-checkout set gql-tester
mv gql-tester/* . && rm -rf gql-tester .git

# Create the virtual environment and install all dependencies into it
/opt/tools/gql-tester/bin/run_graphql_tests.sh setup
```

After setup, either add `bin/` to your PATH or invoke the script by absolute path:

```bash
# Option A — add to PATH (e.g. in ~/.bashrc or ~/.zshrc)
export PATH="/opt/tools/gql-tester/bin:$PATH"

# Option B — invoke directly
/opt/tools/gql-tester/bin/run_graphql_tests.sh single http://myserver/northwind/gql
```

The virtual environment lives at `gql-tester/venv/` and is never shared with or affected by
any other Python installation on the system.

## Usage

```bash
# Test a single endpoint
run_graphql_tests.sh single http://myserver/northwind/gql

# Compare two endpoints
run_graphql_tests.sh compare http://server1/gql http://server2/gql

# Test multiple endpoints from a JSON config
run_graphql_tests.sh multi -e endpoints.json

# Use custom queries and config files
run_graphql_tests.sh single http://myserver/gql -q my_queries.md -c my_config.yaml -o results.json

# Create sample configuration files
run_graphql_tests.sh create-sample-config
```

## Configuration

Copy the sample files from `config/` as a starting point:

- `sample_config.yaml` — performance thresholds, expected counts, validation rules
- `sample_endpoints.json` — endpoint definitions for multi-endpoint tests
- `sample_queries.md` — GraphQL queries in fenced code blocks

## Dependencies

- Python >= 3.9
- requests
- deepdiff
- PyYAML
