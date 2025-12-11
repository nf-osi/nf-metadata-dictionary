#!/usr/bin/env python3
"""
Validate generated JSON Schema files.

This script validates that generated enum and mapping files:
1. Are valid JSON
2. Follow JSON Schema Draft 07 specification
3. Have consistent data
4. Have no duplicate RRIDs
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any, Set, Tuple, Optional
from pathlib import Path


class ValidationError:
    """Represents a validation error."""

    def __init__(self, severity: str, file: str, message: str):
        self.severity = severity  # 'error' or 'warning'
        self.file = file
        self.message = message

    def __str__(self):
        icon = '✗' if self.severity == 'error' else '⚠'
        return f"{icon} [{self.severity.upper()}] {self.file}: {self.message}"


def validate_json_syntax(file_path: str) -> Tuple[bool, Optional[Dict]]:
    """
    Validate that a file contains valid JSON.

    Args:
        file_path: Path to JSON file

    Returns:
        Tuple of (is_valid, parsed_data or None)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return True, data
    except json.JSONDecodeError as e:
        return False, None
    except Exception as e:
        return False, None


def validate_enum_schema(file_path: str, data: Dict[str, Any]) -> List[ValidationError]:
    """
    Validate an enum schema file.

    Args:
        file_path: Path to enum schema file
        data: Parsed JSON data

    Returns:
        List of validation errors
    """
    errors = []
    file_name = os.path.basename(file_path)

    # Check required JSON Schema fields
    if '$schema' not in data:
        errors.append(ValidationError('warning', file_name, "Missing '$schema' field"))
    elif data['$schema'] != "http://json-schema.org/draft-07/schema#":
        errors.append(ValidationError('warning', file_name, f"Unexpected schema version: {data['$schema']}"))

    # Check required fields
    required_fields = ['type', 'enum']
    for field in required_fields:
        if field not in data:
            errors.append(ValidationError('error', file_name, f"Missing required field: {field}"))

    # Validate type
    if data.get('type') != 'string':
        errors.append(ValidationError('error', file_name, f"Expected type 'string', got: {data.get('type')}"))

    # Validate enum array
    if 'enum' in data:
        if not isinstance(data['enum'], list):
            errors.append(ValidationError('error', file_name, "Field 'enum' must be an array"))
        elif len(data['enum']) == 0:
            errors.append(ValidationError('warning', file_name, "Enum array is empty"))
        else:
            # Check for duplicates
            seen = set()
            duplicates = set()
            for value in data['enum']:
                if value in seen:
                    duplicates.add(value)
                seen.add(value)

            if duplicates:
                errors.append(ValidationError(
                    'error',
                    file_name,
                    f"Duplicate enum values found: {', '.join(list(duplicates)[:5])}"
                ))

            # Check that values are strings
            non_strings = [v for v in data['enum'] if not isinstance(v, str)]
            if non_strings:
                errors.append(ValidationError(
                    'error',
                    file_name,
                    f"Enum contains non-string values: {non_strings[:3]}"
                ))

    # Check metadata fields
    if 'meta:sourceTable' not in data:
        errors.append(ValidationError('warning', file_name, "Missing 'meta:sourceTable' field"))

    if 'meta:lastUpdated' not in data:
        errors.append(ValidationError('warning', file_name, "Missing 'meta:lastUpdated' field"))

    if 'meta:recordCount' in data:
        expected_count = data['meta:recordCount']
        actual_count = len(data.get('enum', []))
        if expected_count != actual_count:
            errors.append(ValidationError(
                'warning',
                file_name,
                f"Record count mismatch: meta says {expected_count}, enum has {actual_count}"
            ))

    return errors


def validate_mapping_file(file_path: str, data: Dict[str, Any]) -> List[ValidationError]:
    """
    Validate a mapping file.

    Args:
        file_path: Path to mapping file
        data: Parsed JSON data

    Returns:
        List of validation errors
    """
    errors = []
    file_name = os.path.basename(file_path)

    # Check that it's a dictionary
    if not isinstance(data, dict):
        errors.append(ValidationError('error', file_name, "Mapping file must be a JSON object"))
        return errors

    # Check for empty mapping
    if len(data) == 0:
        errors.append(ValidationError('warning', file_name, "Mapping is empty"))
        return errors

    # Validate each mapping entry
    for tool_name, attributes in data.items():
        if not isinstance(attributes, dict):
            errors.append(ValidationError(
                'error',
                file_name,
                f"Attributes for '{tool_name}' must be an object, got {type(attributes).__name__}"
            ))
            continue

        # Check for empty attributes
        if len(attributes) == 0:
            errors.append(ValidationError(
                'warning',
                file_name,
                f"Tool '{tool_name}' has no attributes"
            ))

        # Check for null values (should have been filtered out)
        null_attrs = [k for k, v in attributes.items() if v is None]
        if null_attrs:
            errors.append(ValidationError(
                'warning',
                file_name,
                f"Tool '{tool_name}' has null attributes: {', '.join(null_attrs)}"
            ))

    return errors


def check_rrid_duplicates(enum_files: List[str], mapping_files: List[str]) -> List[ValidationError]:
    """
    Check for duplicate RRIDs across tools.

    Args:
        enum_files: List of enum file paths
        mapping_files: List of mapping file paths

    Returns:
        List of validation errors for RRID conflicts
    """
    errors = []
    rrid_to_tools = {}

    # Collect RRIDs from mappings
    for mapping_file in mapping_files:
        with open(mapping_file, 'r', encoding='utf-8') as f:
            mappings = json.load(f)

        for tool_name, attributes in mappings.items():
            rrid = attributes.get('RRID')
            if rrid:
                # Normalize RRID format
                rrid_normalized = rrid.upper().replace('RRID:', '')
                if rrid_normalized not in rrid_to_tools:
                    rrid_to_tools[rrid_normalized] = []
                rrid_to_tools[rrid_normalized].append((tool_name, os.path.basename(mapping_file)))

    # Check for duplicates
    for rrid, tools in rrid_to_tools.items():
        if len(tools) > 1:
            tool_list = ', '.join([f"'{t[0]}' ({t[1]})" for t in tools[:3]])
            errors.append(ValidationError(
                'warning',
                'RRID check',
                f"RRID {rrid} used by multiple tools: {tool_list}"
            ))

    return errors


def check_enum_mapping_consistency(enum_file: str, mapping_file: str) -> List[ValidationError]:
    """
    Check consistency between enum and mapping files.

    Args:
        enum_file: Path to enum file
        mapping_file: Path to mapping file

    Returns:
        List of validation errors
    """
    errors = []

    with open(enum_file, 'r', encoding='utf-8') as f:
        enum_data = json.load(f)

    with open(mapping_file, 'r', encoding='utf-8') as f:
        mapping_data = json.load(f)

    enum_values = set(enum_data.get('enum', []))
    mapping_keys = set(mapping_data.keys())

    # Check for values in enum but not in mapping
    missing_in_mapping = enum_values - mapping_keys
    if missing_in_mapping and len(missing_in_mapping) <= 5:
        errors.append(ValidationError(
            'warning',
            os.path.basename(enum_file),
            f"Enum values without mappings: {', '.join(list(missing_in_mapping)[:5])}"
        ))
    elif missing_in_mapping:
        errors.append(ValidationError(
            'warning',
            os.path.basename(enum_file),
            f"{len(missing_in_mapping)} enum values without mappings"
        ))

    # Check for values in mapping but not in enum
    missing_in_enum = mapping_keys - enum_values
    if missing_in_enum and len(missing_in_enum) <= 5:
        errors.append(ValidationError(
            'warning',
            os.path.basename(mapping_file),
            f"Mapping entries not in enum: {', '.join(list(missing_in_enum)[:5])}"
        ))
    elif missing_in_enum:
        errors.append(ValidationError(
            'warning',
            os.path.basename(mapping_file),
            f"{len(missing_in_enum)} mapping entries not in enum"
        ))

    return errors


def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(
        description='Validate generated JSON Schema files'
    )
    parser.add_argument(
        '--directory',
        default='auto-generated/',
        help='Directory containing generated schemas (default: auto-generated/)'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat warnings as errors'
    )

    args = parser.parse_args()

    print("="*60)
    print("VALIDATING GENERATED SCHEMAS")
    print("="*60)

    all_errors = []

    # Find all enum and mapping files
    enum_dir = os.path.join(args.directory, 'enums')
    mapping_dir = os.path.join(args.directory, 'mappings')

    enum_files = []
    mapping_files = []

    if os.path.exists(enum_dir):
        enum_files = [os.path.join(enum_dir, f) for f in os.listdir(enum_dir) if f.endswith('.json')]

    if os.path.exists(mapping_dir):
        mapping_files = [os.path.join(mapping_dir, f) for f in os.listdir(mapping_dir) if f.endswith('.json')]

    if not enum_files and not mapping_files:
        print(f"\n✗ No JSON files found in {args.directory}")
        return 1

    print(f"\nFound {len(enum_files)} enum files and {len(mapping_files)} mapping files\n")

    # Validate enum files
    print("Validating enum files...")
    for enum_file in sorted(enum_files):
        file_name = os.path.basename(enum_file)
        print(f"  Checking {file_name}...")

        # Check JSON syntax
        is_valid, data = validate_json_syntax(enum_file)
        if not is_valid:
            all_errors.append(ValidationError('error', file_name, "Invalid JSON syntax"))
            continue

        # Validate schema structure
        errors = validate_enum_schema(enum_file, data)
        all_errors.extend(errors)

    # Validate mapping files
    print("\nValidating mapping files...")
    for mapping_file in sorted(mapping_files):
        file_name = os.path.basename(mapping_file)
        print(f"  Checking {file_name}...")

        # Check JSON syntax
        is_valid, data = validate_json_syntax(mapping_file)
        if not is_valid:
            all_errors.append(ValidationError('error', file_name, "Invalid JSON syntax"))
            continue

        # Validate mapping structure
        errors = validate_mapping_file(mapping_file, data)
        all_errors.extend(errors)

    # Check RRID duplicates
    print("\nChecking for RRID conflicts...")
    rrid_errors = check_rrid_duplicates(enum_files, mapping_files)
    all_errors.extend(rrid_errors)

    # Check enum/mapping consistency
    print("\nChecking enum/mapping consistency...")
    # Match enum files with corresponding mapping files
    for enum_file in enum_files:
        enum_name = os.path.basename(enum_file).replace('_enum.json', '')
        # Try to find corresponding mapping file
        for mapping_file in mapping_files:
            mapping_name = os.path.basename(mapping_file).replace('_mappings.json', '')
            # Match by tool type (heuristic)
            if any(part in mapping_name for part in enum_name.split('_')):
                consistency_errors = check_enum_mapping_consistency(enum_file, mapping_file)
                all_errors.extend(consistency_errors)
                break

    # Print results
    print("\n" + "="*60)
    print("VALIDATION RESULTS")
    print("="*60)

    errors_by_severity = {'error': [], 'warning': []}
    for error in all_errors:
        errors_by_severity[error.severity].append(error)

    if errors_by_severity['error']:
        print(f"\n{len(errors_by_severity['error'])} ERROR(S):")
        for error in errors_by_severity['error']:
            print(f"  {error}")

    if errors_by_severity['warning']:
        print(f"\n{len(errors_by_severity['warning'])} WARNING(S):")
        for error in errors_by_severity['warning']:
            print(f"  {error}")

    if not all_errors:
        print("\n✓ All validations passed!")
        print("="*60)
        return 0
    else:
        has_errors = len(errors_by_severity['error']) > 0
        has_warnings = len(errors_by_severity['warning']) > 0

        if args.strict and has_warnings:
            print("\n✗ Validation failed (strict mode: warnings treated as errors)")
            print("="*60)
            return 1
        elif has_errors:
            print("\n✗ Validation failed with errors")
            print("="*60)
            return 1
        else:
            print("\n⚠ Validation passed with warnings")
            print("="*60)
            return 0


if __name__ == '__main__':
    sys.exit(main())
