#!/usr/bin/env python3
"""
GraphQL Integration Test Suite for Northwind Database

This script executes GraphQL queries against one or more endpoints and validates results.
It supports comparative testing between endpoints to ensure consistency.

Usage:
    python test_integration_queries.py --endpoint http://localhost:8443/northwind/gql
    python test_integration_queries.py --primary http://localhost:8443/northwind/gql --secondary http://localhost:8444/northwind/gql
"""

import argparse
import json
import re
import time
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse
import logging

import requests
import yaml
from deepdiff import DeepDiff

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('integration_test_results.log')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Container for GraphQL query execution results."""
    query_name: str
    query: str
    success: bool
    response_time_ms: float
    data: Optional[Dict[Any, Any]] = None
    errors: Optional[List[Dict[str, Any]]] = None
    http_status: int = 200
    endpoint: str = ""


@dataclass
class ValidationResult:
    """Container for query validation results."""
    query_name: str
    passed: bool
    expected_count: Optional[int] = None
    actual_count: Optional[int] = None
    validation_errors: List[str] = None
    
    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []


@dataclass
class ComparisonResult:
    """Container for endpoint comparison results."""
    query_name: str
    endpoints_match: bool
    primary_endpoint: str
    secondary_endpoint: str
    differences: Optional[Dict] = None
    primary_count: Optional[int] = None
    secondary_count: Optional[int] = None


class QueryParser:
    """Parse GraphQL queries from markdown file."""
    
    def __init__(self, markdown_file: str):
        self.markdown_file = Path(markdown_file)
        self.queries = {}
        self._parse_queries()
    
    def _parse_queries(self):
        """Extract GraphQL queries from markdown file."""
        if not self.markdown_file.exists():
            raise FileNotFoundError(f"Query file not found: {self.markdown_file}")
        
        content = self.markdown_file.read_text()
        
        # Pattern to match query blocks with names - more flexible approach
        pattern = r'### (\d+)\.\s+(.+?)\n.*?```graphql\n(.*?)\n```'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for match in matches:
            query_number, description, query_content = match
            
            # Clean up and validate the query content
            query_content = query_content.strip()
            
            # Extract query name from the query content
            query_name_match = re.search(r'query\s+(\w+)', query_content)
            if not query_name_match:
                logger.warning(f"Could not extract query name from query {query_number}")
                continue
                
            query_name = query_name_match.group(1)
            
            self.queries[query_name] = {
                'number': int(query_number),
                'description': description.strip(),
                'name': query_name,
                'query': query_content
            }
        
        logger.info(f"Parsed {len(self.queries)} queries from {self.markdown_file}")


class GraphQLClient:
    """GraphQL client for executing queries."""
    
    def __init__(self, endpoint: str, timeout: int = 300):
        self.endpoint = endpoint
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def execute_query(self, query: str, variables: Optional[Dict] = None) -> QueryResult:
        """Execute a GraphQL query and return results."""
        payload = {
            'query': query,
            'variables': variables or {}
        }
        
        start_time = time.time()
        
        try:
            response = self.session.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout
            )
            
            response_time_ms = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                result_data = response.json()
                
                return QueryResult(
                    query_name="",  # Will be set by caller
                    query=query,
                    success='errors' not in result_data or not result_data['errors'],
                    response_time_ms=response_time_ms,
                    data=result_data.get('data'),
                    errors=result_data.get('errors'),
                    http_status=response.status_code,
                    endpoint=self.endpoint
                )
            else:
                return QueryResult(
                    query_name="",
                    query=query,
                    success=False,
                    response_time_ms=response_time_ms,
                    errors=[{
                        'message': f'HTTP {response.status_code}: {response.text}',
                        'extensions': {'code': 'HTTP_ERROR'}
                    }],
                    http_status=response.status_code,
                    endpoint=self.endpoint
                )
        
        except requests.exceptions.RequestException as e:
            response_time_ms = (time.time() - start_time) * 1000
            return QueryResult(
                query_name="",
                query=query,
                success=False,
                response_time_ms=response_time_ms,
                errors=[{
                    'message': f'Request failed: {str(e)}',
                    'extensions': {'code': 'REQUEST_ERROR'}
                }],
                endpoint=self.endpoint
            )


class ResultValidator:
    """Validate GraphQL query results against expected criteria."""
    
    def __init__(self, config_file: Optional[str] = None):
        """Initialize validator with configuration."""
        self.config = {}
        self.expected_counts = {}
        self.performance_thresholds = {}
        
        # Load configuration if provided
        if config_file and Path(config_file).exists():
            try:
                with open(config_file, 'r') as f:
                    self.config = yaml.safe_load(f)
                    self.expected_counts = self.config.get('expected_counts', {})
                    self.performance_thresholds = self.config.get('performance_thresholds', {})
                    logger.info(f"Loaded configuration from {config_file}")
                    logger.debug(f"Expected counts: {self.expected_counts}")
                    logger.debug(f"Performance thresholds: {self.performance_thresholds}")
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")
                self._use_default_config()
        else:
            logger.info("No config file provided, using default expected counts")
            self._use_default_config()
    
    def _use_default_config(self):
        """Fallback to hardcoded expected counts."""
        # Expected counts for standard Northwind dataset
        self.expected_counts = {
            'GetAllEmployees': 9,
            'GetEmployeeById': 1,
            'GetAllCategories': 8,
            'CustomersByCountry': 13,  # USA customers
            'AllRegions': 4,
            'AllShippers': 3,
        }
        # Default performance thresholds
        self.performance_thresholds = {
            'max_simple_query_time': 100,
            'max_complex_query_time': 500,
            'max_large_dataset_time': 2000
        }
    
    # Queries that should return specific employee (Nancy Davolio)
    NANCY_DAVOLIO_QUERIES = ['GetEmployeeById']
    
    # Queries that should return empty results
    EMPTY_RESULT_QUERIES = ['NonExistentEmployee', 'NoResultsExpected']
    
    def validate_query_result(self, query_name: str, result: QueryResult) -> ValidationResult:
        """Validate a single query result."""
        validation_errors = []
        
        # Check if query executed successfully
        if not result.success:
            validation_errors.append(f"Query failed: {result.errors}")
            return ValidationResult(
                query_name=query_name,
                passed=False,
                validation_errors=validation_errors
            )
        
        # Check response time performance
        threshold = self._get_performance_threshold(query_name)
        if result.response_time_ms > threshold:
            validation_errors.append(f"Query too slow: {result.response_time_ms:.1f}ms > {threshold}ms")
        
        # Validate data structure
        if not result.data:
            if query_name not in self.EMPTY_RESULT_QUERIES:
                validation_errors.append("No data returned")
            return ValidationResult(
                query_name=query_name,
                passed=query_name in self.EMPTY_RESULT_QUERIES,
                validation_errors=validation_errors
            )
        
        # Get the main collection from the result
        main_collection = self._extract_main_collection(result.data)
        if not main_collection:
            validation_errors.append("Could not find main data collection in result")
            return ValidationResult(
                query_name=query_name,
                passed=False,
                validation_errors=validation_errors
            )
        
        # Count validation
        actual_count = len(main_collection.get('edges', []))
        expected_count = self.expected_counts.get(query_name)
        
        if expected_count is not None and actual_count != expected_count:
            validation_errors.append(
                f"Count mismatch: expected {expected_count}, got {actual_count}"
            )
        
        # Specific content validation
        if query_name in self.NANCY_DAVOLIO_QUERIES:
            if not self._validate_nancy_davolio(main_collection):
                validation_errors.append("Expected Nancy Davolio not found")
        
        # Empty result validation
        if query_name in self.EMPTY_RESULT_QUERIES:
            if actual_count > 0:
                validation_errors.append(f"Expected empty result, got {actual_count} items")
        
        return ValidationResult(
            query_name=query_name,
            passed=len(validation_errors) == 0,
            expected_count=expected_count,
            actual_count=actual_count,
            validation_errors=validation_errors
        )
    
    def _get_performance_threshold(self, query_name: str) -> float:
        """Get appropriate performance threshold based on query type."""
        # Determine query complexity based on name patterns
        query_lower = query_name.lower()
        
        # Large dataset queries - use max_large_dataset_time
        if any(pattern in query_lower for pattern in ['all', 'orders', 'large', 'unshipped']):
            return self.performance_thresholds.get('max_large_dataset_time', 2000)
        
        # Complex relationship queries - use max_complex_query_time  
        elif any(pattern in query_lower for pattern in ['with', 'complete', 'details', 'chain', 'history']):
            return self.performance_thresholds.get('max_complex_query_time', 500)
        
        # Simple queries - use max_simple_query_time
        else:
            return self.performance_thresholds.get('max_simple_query_time', 100)
    
    def _extract_main_collection(self, data: Dict) -> Optional[Dict]:
        """Extract the main data collection from GraphQL response."""
        if not data:
            return None
        
        # Find the first collection-like field (should have edges)
        for key, value in data.items():
            if isinstance(value, dict) and 'edges' in value:
                return value
        
        return None
    
    def _validate_nancy_davolio(self, collection: Dict) -> bool:
        """Validate that Nancy Davolio is in the result."""
        edges = collection.get('edges', [])
        for edge in edges:
            node = edge.get('node', {})
            if (node.get('first_name') == 'Nancy' and 
                node.get('last_name') == 'Davolio'):
                return True
        return False


class EndpointComparator:
    """Compare results between different GraphQL endpoints."""
    
    def __init__(self, primary_endpoint: str, secondary_endpoint: str):
        self.primary_endpoint = primary_endpoint
        self.secondary_endpoint = secondary_endpoint
    
    def compare_results(self, query_name: str, primary_result: QueryResult, 
                       secondary_result: QueryResult) -> ComparisonResult:
        """Compare results from two endpoints."""
        
        # If both failed, they match in failure
        if not primary_result.success and not secondary_result.success:
            return ComparisonResult(
                query_name=query_name,
                endpoints_match=True,
                primary_endpoint=self.primary_endpoint,
                secondary_endpoint=self.secondary_endpoint
            )
        
        # If one succeeded and one failed, they don't match
        if primary_result.success != secondary_result.success:
            return ComparisonResult(
                query_name=query_name,
                endpoints_match=False,
                primary_endpoint=self.primary_endpoint,
                secondary_endpoint=self.secondary_endpoint,
                differences={'success_mismatch': {
                    'primary': primary_result.success,
                    'secondary': secondary_result.success
                }}
            )
        
        # Both succeeded, compare data
        if primary_result.success and secondary_result.success:
            return self._compare_data(
                query_name, 
                primary_result.data, 
                secondary_result.data
            )
        
        # Fallback
        return ComparisonResult(
            query_name=query_name,
            endpoints_match=False,
            primary_endpoint=self.primary_endpoint,
            secondary_endpoint=self.secondary_endpoint
        )
    
    def _compare_data(self, query_name: str, primary_data: Dict, 
                     secondary_data: Dict) -> ComparisonResult:
        """Compare the actual data from two successful responses."""
        
        # Use DeepDiff for detailed comparison
        diff = DeepDiff(primary_data, secondary_data, ignore_order=True)
        
        # Count items for comparison
        primary_count = self._count_items(primary_data)
        secondary_count = self._count_items(secondary_data)
        
        matches = len(diff) == 0
        
        return ComparisonResult(
            query_name=query_name,
            endpoints_match=matches,
            primary_endpoint=self.primary_endpoint,
            secondary_endpoint=self.secondary_endpoint,
            differences=dict(diff) if diff else None,
            primary_count=primary_count,
            secondary_count=secondary_count
        )
    
    def _count_items(self, data: Dict) -> int:
        """Count items in the main collection."""
        if not data:
            return 0
        
        for key, value in data.items():
            if isinstance(value, dict) and 'edges' in value:
                return len(value['edges'])
        
        return 0


class IntegrationTestSuite:
    """Main test suite coordinator."""
    
    def __init__(self, query_file: str, primary_endpoint: str, 
                 secondary_endpoint: Optional[str] = None, config_file: Optional[str] = None):
        self.query_parser = QueryParser(query_file)
        self.primary_client = GraphQLClient(primary_endpoint)
        self.secondary_client = GraphQLClient(secondary_endpoint) if secondary_endpoint else None
        self.validator = ResultValidator(config_file)
        self.comparator = EndpointComparator(primary_endpoint, secondary_endpoint) if secondary_endpoint else None
        
        self.primary_results: Dict[str, QueryResult] = {}
        self.secondary_results: Dict[str, QueryResult] = {}
        self.validation_results: Dict[str, ValidationResult] = {}
        self.comparison_results: Dict[str, ComparisonResult] = {}
    
    def _get_queries_for_comparison(self) -> Dict[str, Any]:
        """Get the list of queries to execute for endpoint comparison based on config."""
        # Check if identical_result_queries is configured
        comparison_config = self.validator.config.get('comparison_tests', {})
        identical_queries = comparison_config.get('identical_result_queries', [])
        
        if identical_queries:
            # Filter queries to only include the specified ones
            filtered_queries = {}
            for query_name in identical_queries:
                if query_name in self.query_parser.queries:
                    filtered_queries[query_name] = self.query_parser.queries[query_name]
                else:
                    logger.warning(f"Query '{query_name}' specified in identical_result_queries but not found in query file")
            return filtered_queries
        else:
            # Return all queries if no filter is configured
            return self.query_parser.queries

    def run_tests(self) -> Dict[str, Any]:
        """Execute all tests and return comprehensive results."""
        logger.info("Starting GraphQL integration test suite")
        
        start_time = time.time()
        
        # Execute queries on primary endpoint
        logger.info(f"Executing {len(self.query_parser.queries)} queries on primary endpoint")
        self._execute_queries_on_endpoint(self.primary_client, self.primary_results)
        
        # Execute queries on secondary endpoint if provided
        if self.secondary_client:
            # For comparison tests, use filtered query set if configured
            queries_to_compare = self._get_queries_for_comparison()
            logger.info(f"Executing {len(queries_to_compare)} queries on secondary endpoint for comparison")
            self._execute_queries_on_endpoint(self.secondary_client, self.secondary_results, queries_to_compare)
        
        # Validate primary results
        logger.info("Validating query results")
        self._validate_results()
        
        # Compare endpoints if both available
        if self.comparator and self.secondary_results:
            logger.info("Comparing results between endpoints")
            self._compare_endpoints()
        
        total_time = time.time() - start_time
        
        # Generate summary
        summary = self._generate_summary(total_time)
        
        logger.info(f"Test suite completed in {total_time:.2f}s")
        
        return summary
    
    def _execute_queries_on_endpoint(self, client: GraphQLClient, results_dict: Dict[str, QueryResult], 
                                   queries_to_run: Optional[Dict[str, Any]] = None):
        """Execute queries on a specific endpoint.
        
        Args:
            client: The GraphQL client to use
            results_dict: Dictionary to store results
            queries_to_run: Optional dict of queries to run, defaults to all queries
        """
        if queries_to_run is None:
            queries_to_run = self.query_parser.queries
            
        for query_name, query_info in queries_to_run.items():
            logger.info(f"Executing query: {query_name}")
            
            result = client.execute_query(query_info['query'])
            result.query_name = query_name
            results_dict[query_name] = result
            
            if result.success:
                logger.debug(f"✓ {query_name} completed in {result.response_time_ms:.1f}ms")
            else:
                logger.warning(f"✗ {query_name} failed: {result.errors}")
    
    def _validate_results(self):
        """Validate all primary endpoint results."""
        for query_name, result in self.primary_results.items():
            validation = self.validator.validate_query_result(query_name, result)
            self.validation_results[query_name] = validation
            
            if validation.passed:
                logger.debug(f"✓ {query_name} validation passed")
            else:
                logger.warning(f"✗ {query_name} validation failed: {validation.validation_errors}")
    
    def _compare_endpoints(self):
        """Compare results between primary and secondary endpoints."""
        for query_name in self.primary_results.keys():
            if query_name in self.secondary_results:
                comparison = self.comparator.compare_results(
                    query_name,
                    self.primary_results[query_name],
                    self.secondary_results[query_name]
                )
                self.comparison_results[query_name] = comparison
                
                if comparison.endpoints_match:
                    logger.debug(f"✓ {query_name} endpoints match")
                else:
                    logger.warning(f"✗ {query_name} endpoints differ")
    
    def _generate_summary(self, total_time: float) -> Dict[str, Any]:
        """Generate comprehensive test summary."""
        
        # Primary endpoint stats
        primary_success_count = sum(1 for r in self.primary_results.values() if r.success)
        primary_avg_time = sum(r.response_time_ms for r in self.primary_results.values()) / len(self.primary_results)
        
        # Validation stats
        validation_pass_count = sum(1 for v in self.validation_results.values() if v.passed)
        
        # Comparison stats (if available)
        comparison_match_count = 0
        if self.comparison_results:
            comparison_match_count = sum(1 for c in self.comparison_results.values() if c.endpoints_match)
        
        summary = {
            'execution_summary': {
                'total_queries': len(self.query_parser.queries),
                'total_execution_time': total_time,
                'primary_endpoint': self.primary_client.endpoint,
                'primary_success_count': primary_success_count,
                'primary_success_rate': primary_success_count / len(self.primary_results) * 100,
                'primary_avg_response_time_ms': primary_avg_time
            },
            'validation_summary': {
                'validation_pass_count': validation_pass_count,
                'validation_pass_rate': validation_pass_count / len(self.validation_results) * 100,
                'failed_validations': [
                    {
                        'query': name,
                        'errors': result.validation_errors
                    }
                    for name, result in self.validation_results.items()
                    if not result.passed
                ]
            },
            'detailed_results': {
                'query_results': {name: asdict(result) for name, result in self.primary_results.items()},
                'validation_results': {name: asdict(result) for name, result in self.validation_results.items()}
            }
        }
        
        # Add secondary endpoint data if available
        if self.secondary_client:
            secondary_success_count = sum(1 for r in self.secondary_results.values() if r.success)
            secondary_avg_time = sum(r.response_time_ms for r in self.secondary_results.values()) / len(self.secondary_results)
            
            summary['execution_summary'].update({
                'secondary_endpoint': self.secondary_client.endpoint,
                'secondary_success_count': secondary_success_count,
                'secondary_success_rate': secondary_success_count / len(self.secondary_results) * 100,
                'secondary_avg_response_time_ms': secondary_avg_time
            })
            
            summary['comparison_summary'] = {
                'total_comparisons': len(self.comparison_results),
                'matching_count': comparison_match_count,
                'match_rate': comparison_match_count / len(self.comparison_results) * 100 if self.comparison_results else 0,
                'mismatched_queries': [
                    {
                        'query': name,
                        'differences': result.differences,
                        'primary_count': result.primary_count,
                        'secondary_count': result.secondary_count
                    }
                    for name, result in self.comparison_results.items()
                    if not result.endpoints_match
                ]
            }
            
            summary['detailed_results']['comparison_results'] = {
                name: asdict(result) for name, result in self.comparison_results.items()
            }
            
            # Add secondary endpoint results to detailed output
            summary['detailed_results']['secondary_query_results'] = {
                name: asdict(result) for name, result in self.secondary_results.items()
            }
        
        return summary


def main():
    """Main entry point for the test suite."""
    parser = argparse.ArgumentParser(description='GraphQL Integration Test Suite')
    parser.add_argument('--query-file', '-f', default='integration_test_queries.md',
                        help='Path to markdown file containing queries')
    parser.add_argument('--config-file', '-c', default='test_config.yaml', 
                        help='Path to YAML configuration file')
    parser.add_argument('--primary-endpoint', '-p', required=True,
                        help='Primary GraphQL endpoint URL')
    parser.add_argument('--secondary-endpoint', '-s',
                        help='Secondary GraphQL endpoint URL for comparison')
    parser.add_argument('--output', '-o', default='test_results.json',
                        help='Output file for test results')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Initialize and run test suite
        test_suite = IntegrationTestSuite(
            query_file=args.query_file,
            primary_endpoint=args.primary_endpoint,
            secondary_endpoint=args.secondary_endpoint,
            config_file=args.config_file
        )
        
        results = test_suite.run_tests()
        
        # Save results to file
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info(f"Results saved to {args.output}")
        
        # Print summary
        print("\n" + "="*80)
        print("GRAPHQL INTEGRATION TEST SUMMARY")
        print("="*80)
        
        execution = results['execution_summary']
        validation = results['validation_summary']
        
        print(f"Total Queries: {execution['total_queries']}")
        print(f"Execution Time: {execution['total_execution_time']:.2f}s")
        
        # Primary endpoint stats
        print(f"\nPrimary Endpoint: {execution['primary_endpoint']}")
        print(f"  Success Rate: {execution['primary_success_rate']:.1f}%")
        print(f"  Avg Response Time: {execution['primary_avg_response_time_ms']:.1f}ms")
        
        # Secondary endpoint stats (if available)
        if 'secondary_endpoint' in execution:
            print(f"\nSecondary Endpoint: {execution['secondary_endpoint']}")
            print(f"  Success Rate: {execution['secondary_success_rate']:.1f}%")
            print(f"  Avg Response Time: {execution['secondary_avg_response_time_ms']:.1f}ms")
        
        print(f"\nValidation Pass Rate: {validation['validation_pass_rate']:.1f}%")
        
        if 'comparison_summary' in results:
            comparison = results['comparison_summary']
            print(f"Endpoint Match Rate: {comparison['match_rate']:.1f}%")
        
        # Print failed tests
        if validation['failed_validations']:
            print(f"\nFAILED VALIDATIONS ({len(validation['failed_validations'])}):")
            for failure in validation['failed_validations']:
                print(f"  ✗ {failure['query']}: {', '.join(failure['errors'])}")
        
        if 'comparison_summary' in results and results['comparison_summary']['mismatched_queries']:
            print(f"\nMISMATCHED ENDPOINTS ({len(results['comparison_summary']['mismatched_queries'])}):")
            for mismatch in results['comparison_summary']['mismatched_queries']:
                print(f"  ✗ {mismatch['query']}: Count diff {mismatch['primary_count']} vs {mismatch['secondary_count']}")
        
        print("\n" + "="*80)
        
        # Exit with error code if tests failed
        total_failures = len(validation['failed_validations'])
        if 'comparison_summary' in results:
            total_failures += len(results['comparison_summary']['mismatched_queries'])
        
        sys.exit(0 if total_failures == 0 else 1)
        
    except Exception as e:
        logger.error(f"Test suite failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()