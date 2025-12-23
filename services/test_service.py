#!/usr/bin/env python3
"""
Test script for NF Auto-fill Service

Tests all endpoints and validates integration with Synapse.

Usage:
    export SYNAPSE_AUTH_TOKEN=your_token
    python test_service.py

    # Or specify service URL
    python test_service.py --url http://localhost:8000
"""

import argparse
import requests
import json
import sys
from typing import Dict, Any


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


def print_success(message: str):
    """Print success message in green."""
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")


def print_error(message: str):
    """Print error message in red."""
    print(f"{Colors.RED}✗ {message}{Colors.RESET}")


def print_info(message: str):
    """Print info message in blue."""
    print(f"{Colors.BLUE}ℹ {message}{Colors.RESET}")


def print_warning(message: str):
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.RESET}")


class ServiceTester:
    """Test harness for auto-fill service."""

    def __init__(self, service_url: str):
        self.service_url = service_url.rstrip('/')
        self.tests_passed = 0
        self.tests_failed = 0

    def test(self, name: str, func):
        """Run a test function."""
        print(f"\n{'='*70}")
        print(f"TEST: {name}")
        print('='*70)

        try:
            func()
            self.tests_passed += 1
            print_success(f"{name} PASSED")
        except AssertionError as e:
            self.tests_failed += 1
            print_error(f"{name} FAILED: {e}")
        except Exception as e:
            self.tests_failed += 1
            print_error(f"{name} ERROR: {e}")

    def test_health_check(self):
        """Test /health endpoint."""
        url = f"{self.service_url}/health"
        print_info(f"GET {url}")

        response = requests.get(url)

        print(f"  Status: {response.status_code}")
        assert response.status_code == 200, "Expected 200 OK"

        data = response.json()
        print(f"  Response: {json.dumps(data, indent=2)}")

        assert data['status'] == 'healthy', "Expected healthy status"
        assert data['synapse_connected'] == True, "Expected Synapse connection"

        print_success("Service is healthy")

    def test_root_endpoint(self):
        """Test / root endpoint."""
        url = f"{self.service_url}/"
        print_info(f"GET {url}")

        response = requests.get(url)

        assert response.status_code == 200, "Expected 200 OK"

        data = response.json()
        print(f"  Service: {data.get('service')}")
        print(f"  Version: {data.get('version')}")

        assert 'endpoints' in data, "Expected endpoints list"
        print_success("Root endpoint working")

    def test_list_templates(self):
        """Test /api/v1/templates endpoint."""
        url = f"{self.service_url}/api/v1/templates"
        print_info(f"GET {url}")

        response = requests.get(url)

        assert response.status_code == 200, "Expected 200 OK"

        data = response.json()
        print(f"  Template count: {data['count']}")

        for template_name, config in data['templates'].items():
            print(f"  - {template_name}")
            print(f"      Table: {config['table_id']}")
            print(f"      Type: {config['tool_type']}")
            print(f"      Fields: {len(config['autofill_fields'])}")

        assert data['count'] > 0, "Expected at least one template"
        assert 'AnimalIndividualTemplate' in data['templates'], "Expected AnimalIndividualTemplate"

        print_success("Templates endpoint working")

    def test_get_enum_values(self):
        """Test /api/v1/enums endpoint."""
        template = 'AnimalIndividualTemplate'
        field = 'modelSystemName'
        url = f"{self.service_url}/api/v1/enums/{template}/{field}"

        print_info(f"GET {url}")

        response = requests.get(url)

        assert response.status_code == 200, "Expected 200 OK"

        data = response.json()
        print(f"  Field: {data['field']}")
        print(f"  Template: {data['template']}")
        print(f"  Value count: {data['count']}")
        print(f"  Sample values:")
        for value in data['values'][:5]:
            print(f"    - {value}")

        assert data['count'] > 0, "Expected at least one enum value"
        assert isinstance(data['values'], list), "Expected values list"

        print_success("Enum endpoint working")

    def test_autofill_lookup(self):
        """Test /api/v1/autofill endpoint."""
        url = f"{self.service_url}/api/v1/autofill"

        request_data = {
            "template": "AnimalIndividualTemplate",
            "trigger_field": "modelSystemName",
            "trigger_value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
        }

        print_info(f"POST {url}")
        print(f"  Request: {json.dumps(request_data, indent=2)}")

        response = requests.post(url, json=request_data)

        print(f"  Status: {response.status_code}")
        assert response.status_code == 200, "Expected 200 OK"

        data = response.json()
        print(f"  Response:")
        print(f"    Success: {data['success']}")
        print(f"    Template: {data['template']}")
        print(f"    Trigger: {data['trigger_field']} = {data['trigger_value']}")

        if data['success']:
            print(f"    Auto-fill fields:")
            for field, value in data['autofill'].items():
                # Truncate long values
                display_value = value if len(str(value)) < 50 else str(value)[:47] + "..."
                print(f"      {field:25s} = {display_value}")

            assert len(data['autofill']) > 0, "Expected at least one auto-fill field"
            assert 'species' in data['autofill'], "Expected species field"

            print_success("Auto-fill lookup working")
        else:
            print_warning(f"Lookup returned no data: {data.get('message')}")

    def test_autofill_invalid_template(self):
        """Test auto-fill with invalid template."""
        url = f"{self.service_url}/api/v1/autofill"

        request_data = {
            "template": "InvalidTemplate",
            "trigger_field": "someField",
            "trigger_value": "someValue"
        }

        print_info(f"POST {url}")
        print(f"  Request: {json.dumps(request_data, indent=2)}")

        response = requests.post(url, json=request_data)

        print(f"  Status: {response.status_code}")
        assert response.status_code == 404, "Expected 404 Not Found for invalid template"

        print_success("Invalid template handling working")

    def test_autofill_no_data(self):
        """Test auto-fill with value that has no data."""
        url = f"{self.service_url}/api/v1/autofill"

        request_data = {
            "template": "AnimalIndividualTemplate",
            "trigger_field": "modelSystemName",
            "trigger_value": "NonexistentModel123456"
        }

        print_info(f"POST {url}")
        print(f"  Request: {json.dumps(request_data, indent=2)}")

        response = requests.post(url, json=request_data)

        print(f"  Status: {response.status_code}")
        assert response.status_code == 200, "Expected 200 OK"

        data = response.json()
        print(f"  Success: {data['success']}")
        print(f"  Message: {data.get('message')}")

        assert data['success'] == False, "Expected success=false for missing data"
        assert data['message'] is not None, "Expected error message"

        print_success("Missing data handling working")

    def test_cache_info(self):
        """Test cache info endpoint."""
        url = f"{self.service_url}/api/v1/cache/info"
        print_info(f"GET {url}")

        response = requests.get(url)

        assert response.status_code == 200, "Expected 200 OK"

        data = response.json()
        print(f"  Cache info:")
        print(f"    Hits: {data['hits']}")
        print(f"    Misses: {data['misses']}")
        print(f"    Size: {data['size']}/{data['maxsize']}")

        print_success("Cache info endpoint working")

    def run_all_tests(self):
        """Run all tests."""
        print("\n" + "="*70)
        print("NF AUTO-FILL SERVICE TEST SUITE")
        print("="*70)
        print(f"Service URL: {self.service_url}")

        # Basic endpoints
        self.test(
            "Health Check",
            self.test_health_check
        )
        self.test(
            "Root Endpoint",
            self.test_root_endpoint
        )
        self.test(
            "List Templates",
            self.test_list_templates
        )

        # Enum endpoint
        self.test(
            "Get Enum Values",
            self.test_get_enum_values
        )

        # Auto-fill endpoint - happy path
        self.test(
            "Auto-fill Lookup (Success)",
            self.test_autofill_lookup
        )

        # Auto-fill endpoint - error cases
        self.test(
            "Auto-fill Invalid Template",
            self.test_autofill_invalid_template
        )
        self.test(
            "Auto-fill No Data",
            self.test_autofill_no_data
        )

        # Cache endpoint
        self.test(
            "Cache Info",
            self.test_cache_info
        )

        # Summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        total = self.tests_passed + self.tests_failed
        print(f"Total tests: {total}")
        print_success(f"Passed: {self.tests_passed}")
        if self.tests_failed > 0:
            print_error(f"Failed: {self.tests_failed}")
        else:
            print_success("All tests passed!")
        print("="*70)

        return self.tests_failed == 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test NF Auto-fill Service",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--url',
        default='http://localhost:8000',
        help='Service URL (default: http://localhost:8000)'
    )

    args = parser.parse_args()

    # Check service is reachable
    try:
        response = requests.get(args.url, timeout=5)
    except requests.exceptions.ConnectionError:
        print_error(f"Cannot connect to service at {args.url}")
        print_info("Make sure the service is running:")
        print_info("  python autofill_service.py")
        return 1
    except Exception as e:
        print_error(f"Error connecting to service: {e}")
        return 1

    # Run tests
    tester = ServiceTester(args.url)
    success = tester.run_all_tests()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
