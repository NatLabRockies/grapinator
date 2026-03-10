#!/bin/bash
# GraphQL Integration Test Runner
# This script provides easy commands to run GraphQL integration tests

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
QUERY_FILE="integration_test_queries.md"
CONFIG_FILE="test_config.yaml"
ENDPOINTS_FILE="endpoints.json"

print_usage() {
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  setup                    Install test dependencies"
    echo "  single <endpoint>        Test single endpoint"
    echo "  compare <ep1> <ep2>      Compare two endpoints"
    echo "  multi                    Test multiple endpoints from config"
    echo "  create-sample-config     Create sample configuration files"
    echo ""
    echo "Options:"
    echo "  -q, --queries FILE       Path to queries markdown file (default: $QUERY_FILE)"
    echo "  -c, --config FILE        Path to test config file (default: $CONFIG_FILE)"  
    echo "  -e, --endpoints FILE     Path to endpoints JSON file (default: $ENDPOINTS_FILE)"
    echo "  -o, --output FILE        Output file for results"
    echo "  -v, --verbose            Enable verbose logging"
    echo ""
    echo "Examples:"
    echo "  $0 setup"
    echo "  $0 single http://localhost:8443/northwind/gql"
    echo "  $0 compare http://localhost:8443/northwind/gql http://localhost:8444/northwind/gql"
    echo "  $0 multi -e production_endpoints.json"
}

install_dependencies() {
    echo -e "${YELLOW}Installing test dependencies...${NC}"
    
    if [ -f "requirements-test.txt" ]; then
        pip install -r requirements-test.txt
    else
        echo "Installing dependencies directly..."
        pip install requests deepdiff PyYAML
    fi
    
    echo -e "${GREEN}Dependencies installed successfully${NC}"
}

create_sample_files() {
    echo -e "${YELLOW}Creating sample configuration files...${NC}"
    
    # Create sample endpoints file
    cat > sample_endpoints.json << 'EOF'
[
  {
    "name": "local",
    "url": "http://localhost:8443/northwind/gql",
    "description": "Local development server"
  },
  {
    "name": "staging", 
    "url": "https://api-staging.example.com/northwind/gql",
    "description": "Staging environment"
  },
  {
    "name": "production",
    "url": "https://api.example.com/northwind/gql", 
    "description": "Production environment"
  }
]
EOF

    # Create simple run script
    cat > run_tests.sh << 'EOF'
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
EOF

    chmod +x run_tests.sh
    
    echo -e "${GREEN}Created sample files:${NC}"
    echo "  - sample_endpoints.json: Sample endpoint configurations"
    echo "  - run_tests.sh: Simple test runner script"
    echo ""
    echo "Edit these files with your actual endpoint URLs before running tests."
}

run_single_endpoint_test() {
    local endpoint="$1"
    local output_file="${2:-single_test_results.json}"
    
    echo -e "${YELLOW}Testing single endpoint: $endpoint${NC}"
    
    python test_integration_queries.py \
        --primary-endpoint "$endpoint" \
        --query-file "$QUERY_FILE" \
        --output "$output_file" \
        ${VERBOSE:+--verbose}
    
    echo -e "${GREEN}Single endpoint test completed. Results saved to: $output_file${NC}"
}

run_comparison_test() {
    local endpoint1="$1"
    local endpoint2="$2"
    local output_file="${3:-comparison_results.json}"
    
    echo -e "${YELLOW}Comparing endpoints:${NC}"
    echo -e "  Primary: $endpoint1"
    echo -e "  Secondary: $endpoint2"
    
    python test_integration_queries.py \
        --primary-endpoint "$endpoint1" \
        --secondary-endpoint "$endpoint2" \
        --query-file "$QUERY_FILE" \
        --output "$output_file" \
        ${VERBOSE:+--verbose}
    
    echo -e "${GREEN}Comparison test completed. Results saved to: $output_file${NC}"
}

run_multi_endpoint_test() {
    local output_file="${1:-multi_endpoint_results.json}"
    
    if [ ! -f "$ENDPOINTS_FILE" ]; then
        echo -e "${RED}Error: Endpoints file '$ENDPOINTS_FILE' not found${NC}"
        echo "Run '$0 create-sample-config' to create a sample file."
        exit 1
    fi
    
    echo -e "${YELLOW}Running multi-endpoint tests using: $ENDPOINTS_FILE${NC}"
    
    python test_endpoint_comparison.py \
        --config "$CONFIG_FILE" \
        --endpoints "$ENDPOINTS_FILE" \
        --queries "$QUERY_FILE" \
        --output "$output_file" \
        ${VERBOSE:+--verbose}
    
    echo -e "${GREEN}Multi-endpoint test completed. Results saved to: $output_file${NC}"
}

check_python_files() {
    local missing_files=()
    
    if [ ! -f "test_integration_queries.py" ]; then
        missing_files+=("test_integration_queries.py")
    fi
    
    if [ ! -f "test_endpoint_comparison.py" ]; then
        missing_files+=("test_endpoint_comparison.py")
    fi
    
    if [ ${#missing_files[@]} -gt 0 ]; then
        echo -e "${RED}Error: Missing required Python test files:${NC}"
        for file in "${missing_files[@]}"; do
            echo "  - $file"
        done
        echo ""
        echo "Please ensure all test files are present in the current directory."
        exit 1
    fi
}

# Parse command line arguments
COMMAND=""
POSITIONAL_ARGS=()
VERBOSE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -q|--queries)
            QUERY_FILE="$2"
            shift 2
            ;;
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -e|--endpoints)
            ENDPOINTS_FILE="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE="--verbose"
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        setup|single|compare|multi|create-sample-config)
            COMMAND="$1"
            shift
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

# Restore positional parameters
set -- "${POSITIONAL_ARGS[@]}"

# Main command execution
case "$COMMAND" in
    setup)
        install_dependencies
        ;;
    single)
        if [ $# -lt 1 ]; then
            echo -e "${RED}Error: Endpoint URL required for single endpoint test${NC}"
            echo "Usage: $0 single <endpoint_url>"
            exit 1
        fi
        check_python_files
        run_single_endpoint_test "$1" "$OUTPUT_FILE"
        ;;
    compare)
        if [ $# -lt 2 ]; then
            echo -e "${RED}Error: Two endpoint URLs required for comparison test${NC}"
            echo "Usage: $0 compare <endpoint1> <endpoint2>"
            exit 1
        fi
        check_python_files
        run_comparison_test "$1" "$2" "$OUTPUT_FILE"
        ;;
    multi)
        check_python_files
        run_multi_endpoint_test "$OUTPUT_FILE"
        ;;
    create-sample-config)
        create_sample_files
        ;;
    *)
        echo -e "${RED}Error: Invalid or missing command${NC}"
        echo ""
        print_usage
        exit 1
        ;;
esac