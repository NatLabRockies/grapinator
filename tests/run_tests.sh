#!/bin/bash
# Simple test execution script

# Test single endpoint
echo "Testing single endpoint..."
python test_integration_queries.py \
    --primary-endpoint "http://localhost:8443/northwind/gql" \
    --output "single_endpoint_results.json"

# Compare two endpoints (uncomment and modify URLs as needed)
# echo "Comparing two endpoints..."
# python test_integration_queries.py \
#     --primary-endpoint "http://localhost:8443/northwind/gql" \
#     --secondary-endpoint "http://localhost:8444/northwind/gql" \
#     --output "comparison_results.json"

echo "Test execution completed. Check the output files for results."
