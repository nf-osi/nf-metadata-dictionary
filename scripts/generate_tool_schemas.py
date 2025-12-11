#!/usr/bin/env python3
"""
Generate JSON Schema enums and mappings from Synapse research tools data.

This script transforms research tool metadata into:
1. JSON Schema enumerations (controlled vocabularies)
2. Attribute mappings for auto-fill functionality
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path


# Field mappings for each tool type
# Maps source table columns to schema field names
FIELD_MAPPINGS = {
    'animal_models': {
        'name_field': 'modelSystemName',
        'id_field': 'rrid',
        'attributes': {
            'species': 'species',
            'organism': lambda row: row.get('species', '').split()[0] if row.get('species') else None,
            'genotype': 'genotype',
            'backgroundStrain': 'backgroundStrain',
            'RRID': 'rrid',
            'modelSystemType': lambda row: 'animal',
            'geneticModification': 'geneticModification',
            'targetGene': 'targetGene',
            'sourceURL': 'resourceURL',
            'repository': 'repository',
            'catalogNumber': 'catalogNumber',
        }
    },
    'cell_lines': {
        'name_field': 'cellLineName',
        'id_field': 'rrid',
        'attributes': {
            'species': 'species',
            'tissue': 'tissue',
            'organ': 'organ',
            'cellType': 'cellType',
            'disease': 'disease',
            'RRID': 'rrid',
            'STRProfile': 'strProfile',
            'modelSystemType': lambda row: 'cell line',
            'vendor': 'vendor',
            'catalogNumber': 'catalogNumber',
            'sourceURL': 'resourceURL',
        }
    },
    'antibodies': {
        'name_field': 'antibodyName',
        'id_field': 'antibodyID',
        'attributes': {
            'targetProtein': 'targetProtein',
            'hostSpecies': 'hostSpecies',
            'clonality': 'clonality',
            'applications': 'applications',
            'RRID': 'rrid',
            'vendor': 'vendor',
            'catalogNumber': 'catalogNumber',
            'sourceURL': 'resourceURL',
        }
    },
    'genetic_reagents': {
        'name_field': 'reagentName',
        'id_field': 'reagentID',
        'attributes': {
            'reagentType': 'reagentType',
            'targetGene': 'targetGene',
            'vectorBackbone': 'vectorBackbone',
            'RRID': 'rrid',
            'repository': 'repository',
            'catalogNumber': 'catalogNumber',
            'sourceURL': 'resourceURL',
        }
    },
    'biobanks': {
        'name_field': 'biobank',
        'id_field': 'biobankID',
        'attributes': {
            'sampleType': 'sampleType',
            'tissue': 'tissue',
            'biospecimenType': 'biospecimenType',
            'accessProcedure': 'accessProcedure',
            'institution': 'institution',
            'sourceURL': 'resourceURL',
        }
    }
}


def normalize_value(value: Any) -> Optional[Any]:
    """
    Normalize a value for JSON output.

    Args:
        value: Value to normalize

    Returns:
        Normalized value or None
    """
    if value is None:
        return None

    # Handle pandas/numpy types
    if hasattr(value, 'item'):
        value = value.item()

    # Handle strings
    if isinstance(value, str):
        value = value.strip()
        if not value or value.lower() in ['nan', 'none', 'null', 'n/a', '']:
            return None
        return value

    # Handle lists/arrays
    if isinstance(value, (list, tuple)):
        normalized = [normalize_value(v) for v in value]
        normalized = [v for v in normalized if v is not None]
        return normalized if normalized else None

    return value


def get_field_value(row: Dict[str, Any], field_spec: Any) -> Optional[Any]:
    """
    Get a field value from a row using a field specification.

    Args:
        row: Data row dictionary
        field_spec: Either a string (column name) or callable (transformation function)

    Returns:
        Field value or None
    """
    if callable(field_spec):
        return normalize_value(field_spec(row))
    elif isinstance(field_spec, str):
        return normalize_value(row.get(field_spec))
    return None


def format_name_with_id(name: str, id_value: Optional[str]) -> str:
    """
    Format a tool name with its ID (e.g., "Name (RRID:XXX)").

    Args:
        name: Tool name
        id_value: ID value (RRID, catalog number, etc.)

    Returns:
        Formatted name string
    """
    if not name:
        return None

    if id_value:
        # Clean up RRID format
        if id_value.upper().startswith('RRID:'):
            return f"{name} ({id_value})"
        elif id_value.startswith('rrid:'):
            return f"{name} (RRID:{id_value[5:]})"
        else:
            return f"{name} ({id_value})"

    return name


def generate_enum_schema(
    tool_type: str,
    enum_values: List[str],
    source_table: str,
    record_count: int
) -> Dict[str, Any]:
    """
    Generate a JSON Schema enum definition.

    Args:
        tool_type: Type of tool (e.g., 'animal_models')
        enum_values: List of enumeration values
        source_table: Synapse table ID
        record_count: Number of records

    Returns:
        JSON Schema enum dictionary
    """
    field_name = FIELD_MAPPINGS[tool_type]['name_field']

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{field_name} Enumeration (Auto-generated)",
        "description": f"Controlled vocabulary of NF {tool_type.replace('_', ' ')} from {source_table}",
        "type": "string",
        "enum": sorted(enum_values),
        "meta:sourceTable": source_table,
        "meta:lastUpdated": datetime.utcnow().isoformat() + 'Z',
        "meta:recordCount": record_count
    }


def generate_mappings(
    tool_type: str,
    data: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Generate attribute mappings for each tool.

    Args:
        tool_type: Type of tool (e.g., 'animal_models')
        data: List of tool records

    Returns:
        Dictionary mapping tool names to their attributes
    """
    mappings = {}
    config = FIELD_MAPPINGS[tool_type]
    name_field_key = config['name_field']
    id_field_key = config.get('id_field')

    for row in data:
        # Get the tool name
        name = get_field_value(row, config.get('name_column', 'resourceName'))
        if not name:
            continue

        # Get the ID for formatting
        id_value = get_field_value(row, config.get('id_column', id_field_key))

        # Format the name as it appears in the enum
        formatted_name = format_name_with_id(name, id_value)
        if not formatted_name:
            continue

        # Build attribute mapping
        attributes = {}
        for attr_name, attr_spec in config['attributes'].items():
            value = get_field_value(row, attr_spec)
            if value is not None:
                attributes[attr_name] = value

        # Only add if we have at least some attributes
        if attributes:
            mappings[formatted_name] = attributes

    return mappings


def process_tool_type(
    tool_type: str,
    data: List[Dict[str, Any]],
    source_table: str,
    output_dir: str
) -> Dict[str, Any]:
    """
    Process a single tool type and generate enum and mapping files.

    Args:
        tool_type: Type of tool (e.g., 'animal_models')
        data: List of tool records
        source_table: Synapse table ID
        output_dir: Output directory path

    Returns:
        Summary dictionary with stats
    """
    if not data:
        return {
            'tool_type': tool_type,
            'enum_count': 0,
            'mapping_count': 0,
            'status': 'no_data'
        }

    print(f"\nProcessing {tool_type}...")

    # Try to detect name and ID columns from the data
    config = FIELD_MAPPINGS[tool_type]
    name_candidates = ['resourceName', 'name', 'Name', 'antibodyName', 'reagentName', 'cellLineName']
    id_candidates = ['rrid', 'RRID', 'resourceID', 'antibodyID', 'reagentID', 'catalogNumber']

    # Find the actual column names in the data
    sample_row = data[0] if data else {}
    actual_name_col = None
    actual_id_col = None

    for candidate in name_candidates:
        if candidate in sample_row:
            actual_name_col = candidate
            break

    for candidate in id_candidates:
        if candidate in sample_row:
            actual_id_col = candidate
            break

    if not actual_name_col:
        print(f"  ✗ Could not find name column for {tool_type}")
        print(f"    Available columns: {list(sample_row.keys())}")
        return {
            'tool_type': tool_type,
            'enum_count': 0,
            'mapping_count': 0,
            'status': 'missing_name_column'
        }

    # Store the discovered columns in config
    config['name_column'] = actual_name_col
    config['id_column'] = actual_id_col

    # Generate enum values
    enum_values = []
    for row in data:
        name = get_field_value(row, actual_name_col)
        id_value = get_field_value(row, actual_id_col)
        formatted_name = format_name_with_id(name, id_value)
        if formatted_name:
            enum_values.append(formatted_name)

    # Remove duplicates while preserving order
    seen = set()
    unique_enum_values = []
    for val in enum_values:
        if val not in seen:
            seen.add(val)
            unique_enum_values.append(val)

    # Generate enum schema
    enum_schema = generate_enum_schema(
        tool_type,
        unique_enum_values,
        source_table,
        len(unique_enum_values)
    )

    # Generate mappings
    mappings = generate_mappings(tool_type, data)

    # Save enum schema
    enum_file = os.path.join(output_dir, 'enums', f'{config["name_field"]}_enum.json')
    os.makedirs(os.path.dirname(enum_file), exist_ok=True)
    with open(enum_file, 'w', encoding='utf-8') as f:
        json.dump(enum_schema, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Generated enum: {enum_file} ({len(unique_enum_values)} values)")

    # Save mappings
    mapping_file = os.path.join(output_dir, 'mappings', f'{tool_type}_mappings.json')
    os.makedirs(os.path.dirname(mapping_file), exist_ok=True)
    with open(mapping_file, 'w', encoding='utf-8') as f:
        json.dump(mappings, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Generated mappings: {mapping_file} ({len(mappings)} entries)")

    return {
        'tool_type': tool_type,
        'enum_count': len(unique_enum_values),
        'mapping_count': len(mappings),
        'status': 'success'
    }


def main():
    """Main function to generate tool schemas."""
    parser = argparse.ArgumentParser(
        description='Generate JSON Schema enums and mappings from research tools data'
    )
    parser.add_argument(
        '--input',
        default='auto-generated/raw/',
        help='Input directory with JSON files from fetch script'
    )
    parser.add_argument(
        '--output',
        default='auto-generated/',
        help='Output directory for generated schemas'
    )
    parser.add_argument(
        '--tool-types',
        default=None,
        help='Comma-separated list of tool types to process (default: all)'
    )

    args = parser.parse_args()

    # Determine which tool types to process
    if args.tool_types:
        tool_types = args.tool_types.split(',')
    else:
        tool_types = list(FIELD_MAPPINGS.keys())

    print("="*60)
    print("GENERATING TOOL SCHEMAS")
    print("="*60)

    # Load fetch metadata to get table IDs
    metadata_file = os.path.join(args.input, 'fetch_metadata.json')
    source_tables = {}
    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
            source_tables = {k: v['synapse_id'] for k, v in metadata.get('tables', {}).items()}

    # Process each tool type
    results = []
    for tool_type in tool_types:
        # Load data
        data_file = os.path.join(args.input, f'{tool_type}.json')
        if not os.path.exists(data_file):
            print(f"\n⚠ Skipping {tool_type}: {data_file} not found")
            continue

        with open(data_file, 'r') as f:
            data = json.load(f)

        # Get source table ID
        source_table = source_tables.get(tool_type, 'unknown')

        # Process the tool type
        result = process_tool_type(tool_type, data, source_table, args.output)
        results.append(result)

    # Generate summary files
    summary = {
        'generation_date': datetime.utcnow().isoformat() + 'Z',
        'tool_types': results,
        'total_enums': sum(r['enum_count'] for r in results),
        'total_mappings': sum(r['mapping_count'] for r in results)
    }

    # Save LAST_UPDATED.txt
    last_updated_file = os.path.join(args.output, 'LAST_UPDATED.txt')
    with open(last_updated_file, 'w') as f:
        f.write(f"Last Updated: {summary['generation_date']}\n")
        f.write(f"Total Enumerations: {summary['total_enums']}\n")
        f.write(f"Total Mappings: {summary['total_mappings']}\n\n")
        f.write("Source Tables:\n")
        for tool_type, table_id in source_tables.items():
            f.write(f"  {tool_type}: {table_id}\n")
    print(f"\n✓ Updated: {last_updated_file}")

    # Save generation metadata
    metadata_file = os.path.join(args.output, 'generation_metadata.json')
    with open(metadata_file, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"✓ Saved metadata: {metadata_file}")

    # Print summary
    print("\n" + "="*60)
    print("GENERATION SUMMARY")
    print("="*60)
    print(f"Generated: {summary['generation_date']}")
    print(f"Total enumerations: {summary['total_enums']}")
    print(f"Total mappings: {summary['total_mappings']}")
    print("\nBy tool type:")
    for result in results:
        status_icon = '✓' if result['status'] == 'success' else '✗'
        print(f"  {status_icon} {result['tool_type']:20} "
              f"{result['enum_count']:4} enums, {result['mapping_count']:4} mappings")
    print("="*60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
