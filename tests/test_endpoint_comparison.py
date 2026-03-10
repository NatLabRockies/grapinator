#!/usr/bin/env python3
"""
Advanced GraphQL Endpoint Comparison Test Runner

This script performs comprehensive testing between multiple GraphQL endpoints,
including schema validation, performance comparison, and data consistency checks.

Usage:
    python test_endpoint_comparison.py --config test_config.yaml --endpoints endpoints.json
"""

import argparse
import json
import yaml
import time
import itertools
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import logging
import concurrent.futures
from urllib.parse import urlparse

import requests
from deepdiff import DeepDiff

from test_integration_queries import (
    QueryParser, GraphQLClient, QueryResult, 
    ValidationResult, ComparisonResult, IntegrationTestSuite
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class PerformanceComparison:
    """Compare performance metrics between endpoints."""
    query_name: str
    endpoint_1: str
    endpoint_2: str
    time_1_ms: float
    time_2_ms: float
    performance_difference_percent: float
    faster_endpoint: str


@dataclass
class SchemaCompatibilityResult:
    """Result of schema compatibility check between endpoints."""
    endpoints: Tuple[str, str]
    compatible: bool
    schema_differences: Optional[Dict] = None
    introspection_errors: List[str] = None


class AdvancedValidator:
    """Enhanced validator using configuration file."""
    
    def __init__(self, config_file: str):
        self.config = self._load_config(config_file)
    
    def _load_config(self, config_file: str) -> Dict:
        """Load test configuration from YAML file."""
        config_path = Path(config_file)
        if not config_path.exists():
            logger.warning(f"Config file {config_file} not found, using defaults")
            return {}
        
        with open(config_path) as f:
            return yaml.safe_load(f)
    
    def validate_performance(self, query_name: str, result: QueryResult) -> List[str]:
        """Validate query performance against configured thresholds."""
        errors = []
        thresholds = self.config.get('performance_thresholds', {})
        
        # Determine query type and appropriate threshold
        if 'All' in query_name or 'Large' in query_name:
            threshold = thresholds.get('max_large_dataset_time', 2000)
        elif any(rel in query_name.lower() for rel in ['with', 'details', 'complete']):
            threshold = thresholds.get('max_complex_query_time', 500)
        else:
            threshold = thresholds.get('max_simple_query_time', 100)
        
        if result.response_time_ms > threshold:
            errors.append(
                f"Performance threshold exceeded: {result.response_time_ms:.1f}ms > {threshold}ms"
            )
        
        return errors
    
    def validate_business_logic(self, query_name: str, result: QueryResult) -> List[str]:
        """Validate business logic rules from configuration."""
        errors = []
        business_tests = self.config.get('business_logic_tests', {})
        
        if query_name not in business_tests:
            return errors
        
        test_config = business_tests[query_name]
        main_collection = self._extract_main_collection(result.data)
        
        if not main_collection:
            return errors
        
        edges = main_collection.get('edges', [])
        
        # Field validation - all items must have specific values
        field_validation = test_config.get('field_validation', {})
        for field, expected_value in field_validation.items():
            for edge in edges:
                node = edge.get('node', {})
                if node.get(field) != expected_value:
                    errors.append(
                        f"Business rule violation: {field} should be '{expected_value}', "
                        f"got '{node.get(field)}' in item {node.get('product_id', 'unknown')}"
                    )
        
        # Field comparison - numeric/date comparisons
        field_comparison = test_config.get('field_comparison', {})
        for field, comparison in field_comparison.items():
            operator = comparison['operator']
            threshold_value = comparison['value']
            
            for edge in edges:
                node = edge.get('node', {})
                actual_value = node.get(field)
                
                if actual_value is not None:
                    if operator == 'gt' and actual_value <= threshold_value:
                        errors.append(f"Field {field} should be > {threshold_value}, got {actual_value}")
                    elif operator == 'lt' and actual_value >= threshold_value:
                        errors.append(f"Field {field} should be < {threshold_value}, got {actual_value}")
                    elif operator == 'gte' and actual_value < threshold_value:
                        errors.append(f"Field {field} should be >= {threshold_value}, got {actual_value}")
                    elif operator == 'lte' and actual_value > threshold_value:
                        errors.append(f"Field {field} should be <= {threshold_value}, got {actual_value}")
        
        return errors
    
    def validate_relationships(self, query_name: str, result: QueryResult) -> List[str]:
        """Validate relationship integrity from configuration."""
        errors = []
        relationship_tests = self.config.get('relationship_tests', {})
        
        if query_name not in relationship_tests:
            return errors
        
        test_config = relationship_tests[query_name]
        main_collection = self._extract_main_collection(result.data)
        
        if not main_collection:
            return errors
        
        required_relationships = test_config.get('required_relationships', [])
        edges = main_collection.get('edges', [])
        
        for edge in edges:
            node = edge.get('node', {})
            for relationship_path in required_relationships:
                if not self._check_relationship_path(node, relationship_path):
                    errors.append(f"Missing required relationship: {relationship_path}")
        
        return errors
    
    def _extract_main_collection(self, data: Dict) -> Optional[Dict]:
        """Extract the main data collection from GraphQL response."""
        if not data:
            return None
        
        for key, value in data.items():
            if isinstance(value, dict) and 'edges' in value:
                return value
        return None
    
    def _check_relationship_path(self, node: Dict, path: str) -> bool:
        """Check if a nested relationship path exists in the node."""
        parts = path.split('.')
        current = node
        
        for part in parts:
            if not isinstance(current, dict):
                return False
            current = current.get(part)
            if current is None:
                return False
            if isinstance(current, list) and current:
                current = current[0]  # Check first item in list
        
        return True


class EndpointComparator:
    """Enhanced endpoint comparison with configuration support."""
    
    def __init__(self, config: Dict):
        self.config = config
    
    def compare_performance(self, query_name: str, result1: QueryResult, 
                          result2: QueryResult) -> PerformanceComparison:
        """Compare performance between two endpoints."""
        time_diff = abs(result1.response_time_ms - result2.response_time_ms)
        percent_diff = (time_diff / min(result1.response_time_ms, result2.response_time_ms)) * 100
        
        faster_endpoint = result1.endpoint if result1.response_time_ms < result2.response_time_ms else result2.endpoint
        
        return PerformanceComparison(
            query_name=query_name,
            endpoint_1=result1.endpoint,
            endpoint_2=result2.endpoint,
            time_1_ms=result1.response_time_ms,
            time_2_ms=result2.response_time_ms,
            performance_difference_percent=percent_diff,
            faster_endpoint=faster_endpoint
        )
    
    def compare_data_with_config(self, query_name: str, data1: Dict, data2: Dict) -> Dict:
        """Compare data using configuration rules."""
        ignore_fields = self.config.get('comparison_tests', {}).get('ignore_fields', [])
        
        # Remove ignored fields from both datasets
        cleaned_data1 = self._remove_ignored_fields(data1, ignore_fields)
        cleaned_data2 = self._remove_ignored_fields(data2, ignore_fields)
        
        # Different comparison strictness based on query type
        comparison_config = self.config.get('comparison_tests', {})
        flexible_queries = comparison_config.get('flexible_comparison_queries', [])
        
        if query_name in flexible_queries:
            # More lenient comparison for flexible queries
            diff = DeepDiff(cleaned_data1, cleaned_data2, ignore_order=True, significant_digits=2)
        else:
            # Strict comparison for exact match requirements
            diff = DeepDiff(cleaned_data1, cleaned_data2, ignore_order=True)
        
        return dict(diff) if diff else {}
    
    def _remove_ignored_fields(self, data: Any, ignore_fields: List[str]) -> Any:
        """Recursively remove ignored fields from data."""
        if isinstance(data, dict):
            return {
                k: self._remove_ignored_fields(v, ignore_fields)
                for k, v in data.items()
                if k not in ignore_fields
            }
        elif isinstance(data, list):
            return [self._remove_ignored_fields(item, ignore_fields) for item in data]
        else:
            return data


class SchemaCompatibilityChecker:
    """Check GraphQL schema compatibility between endpoints."""
    
    INTROSPECTION_QUERY = """
    query IntrospectionQuery {
      __schema {
        types {
          name
          kind
          fields {
            name
            type {
              name
              kind
              ofType {
                name
                kind
              }
            }
          }
        }
        queryType {
          name
        }
      }
    }
    """
    
    def check_compatibility(self, endpoint1: str, endpoint2: str) -> SchemaCompatibilityResult:
        """Check schema compatibility between two endpoints."""
        client1 = GraphQLClient(endpoint1)
        client2 = GraphQLClient(endpoint2)
        
        schema1_result = client1.execute_query(self.INTROSPECTION_QUERY)
        schema2_result = client2.execute_query(self.INTROSPECTION_QUERY)
        
        errors = []
        
        if not schema1_result.success:
            errors.append(f"Failed to get schema from {endpoint1}: {schema1_result.errors}")
        
        if not schema2_result.success:
            errors.append(f"Failed to get schema from {endpoint2}: {schema2_result.errors}")
        
        if errors:
            return SchemaCompatibilityResult(
                endpoints=(endpoint1, endpoint2),
                compatible=False,
                introspection_errors=errors
            )
        
        # Compare schemas
        schema_diff = DeepDiff(schema1_result.data, schema2_result.data, ignore_order=True)
        
        return SchemaCompatibilityResult(
            endpoints=(endpoint1, endpoint2),
            compatible=len(schema_diff) == 0,
            schema_differences=dict(schema_diff) if schema_diff else None
        )


class MultiEndpointTestSuite:
    """Test suite for comparing multiple GraphQL endpoints."""
    
    def __init__(self, config_file: str, endpoints_file: str, query_file: str):
        self.config = self._load_config(config_file)
        self.endpoints = self._load_endpoints(endpoints_file)
        self.query_parser = QueryParser(query_file)
        self.validator = AdvancedValidator(config_file)
        self.comparator = EndpointComparator(self.config)
        self.schema_checker = SchemaCompatibilityChecker()
        
        self.results: Dict[str, Dict[str, QueryResult]] = {}
        self.performance_comparisons: List[PerformanceComparison] = []
        self.schema_compatibility_results: List[SchemaCompatibilityResult] = []
    
    def _load_config(self, config_file: str) -> Dict:
        """Load test configuration."""
        try:
            with open(config_file) as f:
                return yaml.safe_load(f)
        except Exception:
            logger.warning(f"Could not load config file {config_file}, using defaults")
            return {}
    
    def _load_endpoints(self, endpoints_file: str) -> List[Dict]:
        """Load endpoint configurations."""
        try:
            with open(endpoints_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Could not load endpoints file {endpoints_file}: {e}")
            raise
    
    def run_comprehensive_tests(self) -> Dict[str, Any]:
        """Run comprehensive multi-endpoint testing."""
        logger.info("Starting multi-endpoint GraphQL test suite")
        
        start_time = time.time()
        
        # 1. Check schema compatibility between all endpoint pairs
        logger.info("Checking schema compatibility between endpoints")
        self._check_all_schema_compatibility()
        
        # 2. Execute queries on all endpoints
        logger.info("Executing queries on all endpoints")
        self._execute_queries_on_all_endpoints()
        
        # 3. Performance comparison between endpoints
        logger.info("Comparing performance between endpoints")
        self._compare_performance_across_endpoints()
        
        # 4. Data consistency validation
        logger.info("Validating data consistency across endpoints")
        data_consistency_results = self._validate_data_consistency()
        
        total_time = time.time() - start_time
        
        # Generate comprehensive summary
        summary = self._generate_comprehensive_summary(
            total_time, data_consistency_results
        )
        
        logger.info(f"Multi-endpoint test suite completed in {total_time:.2f}s")
        
        return summary
    
    def _check_all_schema_compatibility(self):
        """Check schema compatibility between all endpoint pairs."""
        endpoint_urls = [ep['url'] for ep in self.endpoints]
        
        for ep1, ep2 in itertools.combinations(endpoint_urls, 2):
            compatibility = self.schema_checker.check_compatibility(ep1, ep2)
            self.schema_compatibility_results.append(compatibility)
            
            if compatibility.compatible:
                logger.info(f"✓ Schema compatible: {ep1} ↔ {ep2}")
            else:
                logger.warning(f"✗ Schema incompatible: {ep1} ↔ {ep2}")
    
    def _execute_queries_on_all_endpoints(self):
        """Execute all queries on all endpoints concurrently."""
        for endpoint_config in self.endpoints:
            endpoint_url = endpoint_config['url']
            endpoint_name = endpoint_config.get('name', endpoint_url)
            
            logger.info(f"Executing queries on {endpoint_name}")
            
            client = GraphQLClient(endpoint_url)
            self.results[endpoint_name] = {}
            
            # Execute queries concurrently for better performance
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_query = {
                    executor.submit(client.execute_query, query_info['query']): query_name
                    for query_name, query_info in self.query_parser.queries.items()
                }
                
                for future in concurrent.futures.as_completed(future_to_query):
                    query_name = future_to_query[future]
                    try:
                        result = future.result()
                        result.query_name = query_name
                        result.endpoint = endpoint_name
                        self.results[endpoint_name][query_name] = result
                    except Exception as e:
                        logger.error(f"Query {query_name} failed on {endpoint_name}: {e}")
    
    def _compare_performance_across_endpoints(self):
        """Compare performance metrics across all endpoint pairs."""
        endpoint_names = list(self.results.keys())
        
        for ep1, ep2 in itertools.combinations(endpoint_names, 2):
            for query_name in self.query_parser.queries.keys():
                if query_name in self.results[ep1] and query_name in self.results[ep2]:
                    result1 = self.results[ep1][query_name]
                    result2 = self.results[ep2][query_name]
                    
                    if result1.success and result2.success:
                        perf_comparison = self.comparator.compare_performance(
                            query_name, result1, result2
                        )
                        self.performance_comparisons.append(perf_comparison)
    
    def _validate_data_consistency(self) -> Dict[str, Any]:
        """Validate that data is consistent across all endpoints."""
        consistency_results = {
            'total_queries': len(self.query_parser.queries),
            'consistent_queries': 0,
            'inconsistent_queries': [],
            'endpoint_pairs_compared': 0,
            'successful_comparisons': 0
        }
        
        endpoint_names = list(self.results.keys())
        
        for query_name in self.query_parser.queries.keys():
            query_consistent = True
            query_inconsistencies = []
            
            # Compare all pairs of endpoints for this query
            for ep1, ep2 in itertools.combinations(endpoint_names, 2):
                consistency_results['endpoint_pairs_compared'] += 1
                
                if (query_name in self.results[ep1] and 
                    query_name in self.results[ep2]):
                    
                    result1 = self.results[ep1][query_name]
                    result2 = self.results[ep2][query_name]
                    
                    if result1.success and result2.success:
                        consistency_results['successful_comparisons'] += 1
                        
                        # Compare data using configuration
                        differences = self.comparator.compare_data_with_config(
                            query_name, result1.data, result2.data
                        )
                        
                        if differences:
                            query_consistent = False
                            query_inconsistencies.append({
                                'endpoints': [ep1, ep2],
                                'differences': differences
                            })
            
            if query_consistent:
                consistency_results['consistent_queries'] += 1
            else:
                consistency_results['inconsistent_queries'].append({
                    'query_name': query_name,
                    'inconsistencies': query_inconsistencies
                })
        
        return consistency_results
    
    def _generate_comprehensive_summary(self, total_time: float, 
                                      consistency_results: Dict) -> Dict[str, Any]:
        """Generate comprehensive test results summary."""
        
        # Schema compatibility summary
        compatible_schemas = sum(1 for r in self.schema_compatibility_results if r.compatible)
        
        # Performance analysis
        if self.performance_comparisons:
            avg_perf_diff = sum(p.performance_difference_percent for p in self.performance_comparisons) / len(self.performance_comparisons)
            max_perf_diff = max(p.performance_difference_percent for p in self.performance_comparisons)
        else:
            avg_perf_diff = max_perf_diff = 0
        
        # Overall success rates
        endpoint_success_rates = {}
        for endpoint_name, results in self.results.items():
            success_count = sum(1 for r in results.values() if r.success)
            endpoint_success_rates[endpoint_name] = {
                'success_count': success_count,
                'total_queries': len(results),
                'success_rate': success_count / len(results) * 100 if results else 0
            }
        
        summary = {
            'test_execution_summary': {
                'total_execution_time': total_time,
                'endpoints_tested': len(self.endpoints),
                'queries_executed': len(self.query_parser.queries),
                'total_query_executions': sum(len(results) for results in self.results.values())
            },
            'schema_compatibility': {
                'total_comparisons': len(self.schema_compatibility_results),
                'compatible_pairs': compatible_schemas,
                'compatibility_rate': compatible_schemas / len(self.schema_compatibility_results) * 100 if self.schema_compatibility_results else 0,
                'incompatible_pairs': [
                    {
                        'endpoints': list(r.endpoints),
                        'differences_count': len(r.schema_differences) if r.schema_differences else 0
                    }
                    for r in self.schema_compatibility_results if not r.compatible
                ]
            },
            'performance_analysis': {
                'total_performance_comparisons': len(self.performance_comparisons),
                'average_performance_difference_percent': avg_perf_diff,
                'maximum_performance_difference_percent': max_perf_diff,
                'significant_performance_differences': [
                    asdict(p) for p in self.performance_comparisons 
                    if p.performance_difference_percent > 50  # More than 50% difference
                ]
            },
            'data_consistency': consistency_results,
            'endpoint_health': endpoint_success_rates,
            'detailed_results': {
                'query_results': self.results,
                'performance_comparisons': [asdict(p) for p in self.performance_comparisons],
                'schema_compatibility': [asdict(r) for r in self.schema_compatibility_results]
            }
        }
        
        return summary


def create_sample_endpoints_file():
    """Create a sample endpoints configuration file."""
    sample_endpoints = [
        {
            "name": "production",
            "url": "https://api.production.com/graphql",
            "description": "Production GraphQL endpoint"
        },
        {
            "name": "staging", 
            "url": "https://api.staging.com/graphql",
            "description": "Staging GraphQL endpoint"
        },
        {
            "name": "local",
            "url": "http://localhost:8443/northwind/gql",
            "description": "Local development endpoint"
        }
    ]
    
    with open('sample_endpoints.json', 'w') as f:
        json.dump(sample_endpoints, f, indent=2)
    
    logger.info("Created sample_endpoints.json - modify with your actual endpoints")


def main():
    """Main entry point for multi-endpoint testing."""
    parser = argparse.ArgumentParser(description='Multi-Endpoint GraphQL Test Suite')
    parser.add_argument('--config', '-c', default='test_config.yaml',
                        help='Path to test configuration file')
    parser.add_argument('--endpoints', '-e', required=True,
                        help='Path to endpoints JSON configuration')
    parser.add_argument('--queries', '-q', default='integration_test_queries.md',
                        help='Path to queries markdown file')
    parser.add_argument('--output', '-o', default='multi_endpoint_results.json',
                        help='Output file for test results')
    parser.add_argument('--create-sample-endpoints', action='store_true',
                        help='Create a sample endpoints configuration file')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.create_sample_endpoints:
        create_sample_endpoints_file()
        return
    
    try:
        # Initialize and run multi-endpoint test suite
        test_suite = MultiEndpointTestSuite(
            config_file=args.config,
            endpoints_file=args.endpoints,
            query_file=args.queries
        )
        
        results = test_suite.run_comprehensive_tests()
        
        # Save results
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info(f"Results saved to {args.output}")
        
        # Print summary
        print("\n" + "="*80)
        print("MULTI-ENDPOINT GRAPHQL TEST SUMMARY")
        print("="*80)
        
        execution = results['test_execution_summary']
        schema = results['schema_compatibility']
        performance = results['performance_analysis']
        consistency = results['data_consistency']
        
        print(f"Endpoints Tested: {execution['endpoints_tested']}")
        print(f"Total Execution Time: {execution['total_execution_time']:.2f}s")
        print(f"Query Executions: {execution['total_query_executions']}")
        
        print(f"\nSchema Compatibility: {schema['compatibility_rate']:.1f}%")
        print(f"Data Consistency: {consistency['consistent_queries']}/{consistency['total_queries']} queries")
        print(f"Avg Performance Difference: {performance['average_performance_difference_percent']:.1f}%")
        
        # Print issues
        if schema['incompatible_pairs']:
            print(f"\nSCHEMA INCOMPATIBILITIES ({len(schema['incompatible_pairs'])}):")
            for pair in schema['incompatible_pairs']:
                print(f"  ✗ {' ↔ '.join(pair['endpoints'])}")
        
        if consistency['inconsistent_queries']:
            print(f"\nDATA INCONSISTENCIES ({len(consistency['inconsistent_queries'])}):")
            for inconsistency in consistency['inconsistent_queries'][:5]:  # Show first 5
                print(f"  ✗ {inconsistency['query_name']}")
        
        print("\n" + "="*80)
        
    except Exception as e:
        logger.error(f"Multi-endpoint test suite failed: {str(e)}")
        raise


if __name__ == '__main__':
    main()