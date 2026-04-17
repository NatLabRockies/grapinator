#!/bin/bash
# GraphQL Integration Test Runner
# This script provides easy commands to run GraphQL integration tests

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Locate project root relative to this script so it works from any PATH or
# absolute invocation (e.g. /opt/tools/gql-tester/bin/run_graphql_tests.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"

# Default values
QUERY_FILE="integration_test_queries.md"
CONFIG_FILE="test_config.yaml"
ENDPOINTS_FILE="endpoints.json"

# Resolve Python from the project-local venv
if [[ -f "$VENV_DIR/bin/python" ]]; then
    PYTHON_CMD="$VENV_DIR/bin/python"
elif [[ -f "$VENV_DIR/Scripts/python.exe" ]]; then
    PYTHON_CMD="$VENV_DIR/Scripts/python.exe"
else
    if [[ "$1" != "setup" ]]; then
        echo -e "${RED}Error: Virtual environment not found at $VENV_DIR${NC}"
        echo "Run '$(basename "$0") setup' first to create it."
        exit 1
    fi
    PYTHON_CMD="python3"
fi

print_usage() {
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  setup                    Install dependencies"
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
    echo -e "${YELLOW}Creating virtual environment at $VENV_DIR ...${NC}"
    python3 -m venv "$VENV_DIR"
    echo -e "${YELLOW}Installing dependencies into venv...${NC}"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install -e "$PROJECT_ROOT"
    echo -e "${GREEN}Setup complete. Virtual environment ready at $VENV_DIR${NC}"
}

create_sample_files() {
    echo -e "${YELLOW}Creating sample configuration files...${NC}"

    $PYTHON_CMD -m gql_tester.comparison --create-sample-endpoints

    echo -e "${GREEN}Created sample files:${NC}"
    echo "  - sample_endpoints.json: Sample endpoint configurations"
    echo ""
    echo "Edit these files with your actual endpoint URLs before running tests."
}

run_single_endpoint_test() {
    local endpoint="$1"
    local output_file="${2:-single_test_results.json}"

    echo -e "${YELLOW}Testing single endpoint: $endpoint${NC}"

    $PYTHON_CMD -m gql_tester.integration \
        --primary-endpoint "$endpoint" \
        --query-file "$QUERY_FILE" \
        --config-file "$CONFIG_FILE" \
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

    $PYTHON_CMD -m gql_tester.integration \
        --primary-endpoint "$endpoint1" \
        --secondary-endpoint "$endpoint2" \
        --query-file "$QUERY_FILE" \
        --config-file "$CONFIG_FILE" \
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

    $PYTHON_CMD -m gql_tester.comparison \
        --config "$CONFIG_FILE" \
        --endpoints "$ENDPOINTS_FILE" \
        --queries "$QUERY_FILE" \
        --output "$output_file" \
        ${VERBOSE:+--verbose}

    echo -e "${GREEN}Multi-endpoint test completed. Results saved to: $output_file${NC}"
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
        run_single_endpoint_test "$1" "$OUTPUT_FILE"
        ;;
    compare)
        if [ $# -lt 2 ]; then
            echo -e "${RED}Error: Two endpoint URLs required for comparison test${NC}"
            echo "Usage: $0 compare <endpoint1> <endpoint2>"
            exit 1
        fi
        run_comparison_test "$1" "$2" "$OUTPUT_FILE"
        ;;
    multi)
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
