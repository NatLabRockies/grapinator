# Changelog

## [1.0.0] - 2026-04-17

### Added
- Initial release as standalone sub-project extracted from grapinator `tests/`
- `run_graphql_tests.sh` as the single entry point; invoke by absolute path or add `bin/` to PATH
- Self-contained virtual environment created under `gql-tester/venv/` via `run_graphql_tests.sh setup` — nothing installed to system or base Python
- `gql_tester.integration` module for single and dual-endpoint testing
- `gql_tester.comparison` module for multi-endpoint comparison with schema and performance analysis
- Sample configuration files in `config/` (`sample_config.yaml`, `sample_endpoints.json`, `sample_queries.md`)
- `.gitignore` excluding `venv/`, `*.egg-info/`, `__pycache__/`, and log files
