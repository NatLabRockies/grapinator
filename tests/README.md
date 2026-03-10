# GraphQL Integration Testing Suite

This directory contains a comprehensive testing framework for GraphQL APIs, specifically designed for the Northwind database but adaptable to any GraphQL endpoint. The suite includes query execution, result validation, performance testing, and endpoint comparison capabilities.

## 📁 Files Overview

### Core Test Files
- **`integration_test_queries.md`** - 34 comprehensive GraphQL test queries covering all major scenarios
- **`test_integration_queries.py`** - Main Python test runner for single/dual endpoint testing
- **`test_endpoint_comparison.py`** - Advanced multi-endpoint comparison and schema validation
- **`test_config.yaml`** - Configuration file defining validation rules and test criteria

### Supporting Files  
- **`run_graphql_tests.sh`** - Convenient shell script wrapper for all test operations
- **`requirements-test.txt`** - Python dependencies for the test suite
- **`README.md`** - This documentation file

## 🚀 Quick Start

### 1. Install Dependencies
```bash
# Using the provided script
./run_graphql_tests.sh setup

# Or manually with pip
pip install -r requirements-test.txt
```

### 2. Test a Single Endpoint
```bash
# Using the shell script (recommended)
./run_graphql_tests.sh single http://localhost:8443/northwind/gql

# Or directly with Python
python test_integration_queries.py --primary-endpoint http://localhost:8443/northwind/gql
```

### 3. Compare Two Endpoints
```bash
# Compare production vs staging
./run_graphql_tests.sh compare \
    http://localhost:8443/northwind/gql \
    http://localhost:8444/northwind/gql

# With custom output file
python test_integration_queries.py \
    --primary-endpoint http://localhost:8443/northwind/gql \
    --secondary-endpoint http://localhost:8444/northwind/gql \
    --output comparison_results.json
```

## 📋 Test Categories

The test suite includes 34 different query scenarios organized into categories:

### Basic Operations
- **Entity Retrieval** - Simple queries for employees, products, customers, categories
- **Single Record Lookup** - Specific ID-based queries with validation
- **Reference Data** - Complete retrieval of lookup tables (regions, shippers)

### Advanced Features  
- **Complex Relationships** - Multi-level joins (orders → customers → employees → territories)
- **Filtering & Sorting** - Country filters, date ranges, price comparisons
- **Pattern Matching** - Contains, startswith, greater than, less than operations
- **Business Logic** - Inventory levels, discontinued products, high-value orders

### Performance & Edge Cases
- **Large Datasets** - Full table retrievals for performance testing
- **Error Handling** - Non-existent IDs, empty results, invalid parameters
- **Data Integrity** - Foreign key validation, required field checks

## ⚙️ Configuration

### Test Configuration (`test_config.yaml`)

The configuration file allows you to customize validation rules:

```yaml
# Performance thresholds (milliseconds)
performance_thresholds:
  max_simple_query_time: 100
  max_complex_query_time: 500
  max_large_dataset_time: 2000

# Expected result counts
expected_counts:
  GetAllEmployees: 9
  GetAllCategories: 8
  CustomersByCountry: 13  # USA customers

# Business logic validation
business_logic_tests:
  DiscontinuedProducts:
    field_validation:
      discontinued: "1"
  
  ExpensiveProducts:
    field_comparison:
      unit_price: {"operator": "gt", "value": 50}
```

### Endpoint Configuration (`endpoints.json`)

For multi-endpoint testing, create an endpoints configuration:

```json
[
  {
    "name": "local",
    "url": "http://localhost:8443/northwind/gql",
    "description": "Local development server"
  },
  {
    "name": "staging",
    "url": "https://staging-api.example.com/northwind/gql",
    "description": "Staging environment"
  },
  {
    "name": "production",
    "url": "https://api.example.com/northwind/gql",
    "description": "Production environment"
  }
]
```

## 🔧 Advanced Usage

### Multi-Endpoint Testing

Test schema compatibility and data consistency across multiple environments:

```bash
# Create sample configuration files
./run_graphql_tests.sh create-sample-config

# Edit endpoints.json with your actual URLs
# Then run comprehensive multi-endpoint tests
./run_graphql_tests.sh multi

# Or with Python directly
python test_endpoint_comparison.py \
    --config test_config.yaml \
    --endpoints endpoints.json \
    --queries integration_test_queries.md
```

### Custom Query Files

You can test with your own GraphQL queries by creating a markdown file following this format:

```markdown
### 1. Your Query Name
Description of what this query tests.
```graphql
query YourQueryName {
  your_field {
    edges {
      node {
        field1
        field2
      }
    }
  }
}
```
```

### Verbose Logging

Enable detailed logging for troubleshooting:

```bash
./run_graphql_tests.sh single http://localhost:8443/northwind/gql --verbose

python test_integration_queries.py \
    --primary-endpoint http://localhost:8443/northwind/gql \
    --verbose
```

## 📊 Understanding Results

### Test Output Structure

Results are saved as JSON files containing:

```json
{
  "execution_summary": {
    "total_queries": 34,
    "primary_success_rate": 97.1,
    "primary_avg_response_time_ms": 125.3
  },
  "validation_summary": {
    "validation_pass_rate": 94.1,
    "failed_validations": [...]
  },
  "comparison_summary": {
    "match_rate": 98.5,
    "mismatched_queries": [...]
  }
}
```

### Key Metrics

- **Success Rate** - Percentage of queries that executed without GraphQL errors
- **Validation Pass Rate** - Percentage of queries meeting expected criteria  
- **Match Rate** - Percentage of queries returning identical results across endpoints
- **Average Response Time** - Mean execution time across all queries

### Common Issues

1. **Schema Incompatibility** - Different GraphQL schemas between endpoints
2. **Performance Degradation** - Queries exceeding configured thresholds
3. **Data Inconsistency** - Different result counts or values between endpoints
4. **Missing Relationships** - Broken foreign key relationships in complex queries

## 🎯 Expected Results (Standard Northwind Dataset)

When testing against a standard Northwind database, expect these counts:

| Query | Expected Count | Description |
|-------|----------------|-------------|
| GetAllEmployees | 9 | Total employees |
| GetAllCategories | 8 | Product categories |
| CustomersByCountry (USA) | 13 | US customers |
| AllRegions | 4 | Geographic regions |
| AllShippers | 3 | Shipping companies |

## 🔍 Troubleshooting

### Connection Issues
```bash
# Test basic connectivity
curl -X POST -H "Content-Type: application/json" \
  -d '{"query": "{__schema{queryType{name}}}"}' \
  http://localhost:8443/northwind/gql
```

### Missing Dependencies
```bash
# Reinstall test dependencies
pip install --upgrade requests deepdiff PyYAML
```

### Performance Issues
```bash
# Run with timing information
python test_integration_queries.py \
    --primary-endpoint http://localhost:8443/northwind/gql \
    --verbose 2>&1 | grep "completed in"
```

## 📈 Integration with CI/CD

### GitHub Actions Example
```yaml
name: GraphQL API Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install dependencies
        run: pip install -r tests/requirements-test.txt
      - name: Run integration tests
        run: |
          cd tests
          python test_integration_queries.py \
            --primary-endpoint ${{ secrets.STAGING_GRAPHQL_URL }} \
            --secondary-endpoint ${{ secrets.PRODUCTION_GRAPHQL_URL }}
```

### Docker Integration
```dockerfile
FROM python:3.9
COPY tests/ /tests/
WORKDIR /tests
RUN pip install -r requirements-test.txt
CMD ["python", "test_integration_queries.py", "--primary-endpoint", "$GRAPHQL_ENDPOINT"]
```

## 📝 Extending the Test Suite

### Adding New Queries

1. Add your GraphQL query to `integration_test_queries.md` following the existing format
2. Update `test_config.yaml` with expected results if needed
3. Add validation rules for business logic if applicable

### Custom Validators

Extend the `ResultValidator` class in `test_integration_queries.py`:

```python
def validate_custom_business_rule(self, query_name: str, result: QueryResult) -> List[str]:
    """Add your custom validation logic here."""
    errors = []
    # Your validation code
    return errors
```

### New Comparison Metrics

Add custom comparison logic in `EndpointComparator` class:

```python
def compare_custom_metric(self, result1: QueryResult, result2: QueryResult) -> bool:
    """Add your custom comparison logic here."""
    # Your comparison code
    return True
```

## 🤝 Contributing

1. Follow the existing code structure and naming conventions
2. Add tests for any new functionality
3. Update this README with new features or configuration options
4. Ensure all tests pass before submitting changes

## 📄 License

This test suite is part of the Grapinator project. See the main project LICENSE file for details.