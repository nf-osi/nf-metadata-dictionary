#!/usr/bin/env python3
"""
Integrate auto-generated tool mappings with registered JSON schemas.

This script:
1. Updates registered JSON schemas to use auto-generated enums
2. Creates integration files for schematic/DCA to implement auto-fill
3. Generates lookup tables for easy field population
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any
from pathlib import Path


# Mapping of schema files to tool types and their fields
SCHEMA_INTEGRATIONS = {
    'AnimalIndividualTemplate.json': {
        'primary_field': 'modelSystemName',
        'enum_source': 'auto-generated/enums/modelSystemName_enum.json',
        'mapping_source': 'auto-generated/mappings/animal_models_mappings.json',
        'auto_fields': {
            'species': 'species',
            'genotype': 'genotype',
            'backgroundStrain': 'backgroundStrain',
        }
    },
    'BiospecimenTemplate.json': {
        'primary_field': 'modelSystemName',
        'enum_source': 'auto-generated/enums/cellLineName_enum.json',
        'mapping_source': 'auto-generated/mappings/cell_lines_mappings.json',
        'auto_fields': {
            'species': 'species',
            'tissue': 'tissue',
            'organ': 'organ',
        }
    }
}


def load_json_file(file_path: str) -> Dict[str, Any]:
    """Load JSON file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json_file(file_path: str, data: Dict[str, Any]) -> None:
    """Save JSON file with pretty formatting."""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_schema_with_enum(
    schema_file: str,
    enum_file: str,
    field_name: str,
    backup: bool = True
) -> bool:
    """
    Update a registered schema to use auto-generated enum.

    Args:
        schema_file: Path to registered schema JSON file
        enum_file: Path to auto-generated enum file
        field_name: Name of the field to update
        backup: Whether to create a backup

    Returns:
        True if updated, False otherwise
    """
    if not os.path.exists(schema_file):
        print(f"  ✗ Schema file not found: {schema_file}")
        return False

    if not os.path.exists(enum_file):
        print(f"  ✗ Enum file not found: {enum_file}")
        return False

    # Load files
    schema = load_json_file(schema_file)
    enum_data = load_json_file(enum_file)

    # Backup if requested
    if backup:
        backup_file = f"{schema_file}.bak"
        save_json_file(backup_file, schema)

    # Find and update the field
    if 'properties' in schema and field_name in schema['properties']:
        field_def = schema['properties'][field_name]

        # Check if field has items (array type)
        if 'items' in field_def and 'enum' in field_def['items']:
            old_count = len(field_def['items']['enum'])
            field_def['items']['enum'] = enum_data['enum']
            new_count = len(field_def['items']['enum'])

            # Add metadata comment
            field_def['items']['x-auto-generated'] = {
                'source': enum_file,
                'lastUpdated': enum_data.get('meta:lastUpdated'),
                'sourceTable': enum_data.get('meta:sourceTable')
            }

            print(f"  ✓ Updated {field_name} enum: {old_count} → {new_count} values")

        elif 'enum' in field_def:
            old_count = len(field_def['enum'])
            field_def['enum'] = enum_data['enum']
            new_count = len(field_def['enum'])

            # Add metadata comment
            field_def['x-auto-generated'] = {
                'source': enum_file,
                'lastUpdated': enum_data.get('meta:lastUpdated'),
                'sourceTable': enum_data.get('meta:sourceTable')
            }

            print(f"  ✓ Updated {field_name} enum: {old_count} → {new_count} values")
        else:
            print(f"  ⚠ Field {field_name} doesn't have enum definition")
            return False

        # Save updated schema
        save_json_file(schema_file, schema)
        return True
    else:
        print(f"  ✗ Field {field_name} not found in schema properties")
        return False


def create_autofill_config(
    schema_configs: Dict[str, Dict],
    output_file: str
) -> None:
    """
    Create auto-fill configuration file for schematic/DCA.

    This file tells the frontend application which fields should be
    auto-populated when a tool is selected.

    Args:
        schema_configs: Dictionary of schema integration configurations
        output_file: Path to output configuration file
    """
    autofill_config = {
        "$schema": "auto-generated/schemas/autofill-config-schema.json",
        "version": "1.0.0",
        "description": "Configuration for auto-filling metadata fields based on research tool selection",
        "rules": []
    }

    for schema_file, config in schema_configs.items():
        if not os.path.exists(config['mapping_source']):
            continue

        rule = {
            "schema": schema_file,
            "triggerField": config['primary_field'],
            "mappingSource": config['mapping_source'],
            "autoFields": config['auto_fields'],
            "behavior": "suggest",  # or "force" to override user input
            "description": f"Auto-fill fields when {config['primary_field']} is selected"
        }
        autofill_config['rules'].append(rule)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    save_json_file(output_file, autofill_config)
    print(f"\n✓ Created auto-fill config: {output_file}")


def create_lookup_service(
    mapping_files: Dict[str, str],
    output_file: str
) -> None:
    """
    Create a unified lookup service for easy access to all mappings.

    This is a convenience file that combines all mappings into a single
    structure for quick lookups.

    Args:
        mapping_files: Dictionary of tool type to mapping file path
        output_file: Path to output lookup service file
    """
    lookup = {
        "$schema": "auto-generated/schemas/lookup-service-schema.json",
        "version": "1.0.0",
        "description": "Unified lookup service for research tool metadata",
        "tools": {}
    }

    for tool_type, mapping_file in mapping_files.items():
        if os.path.exists(mapping_file):
            mappings = load_json_file(mapping_file)
            lookup['tools'][tool_type] = {
                "count": len(mappings),
                "mappings": mappings
            }

    # Add lookup function documentation
    lookup['usage'] = {
        "example": "lookup.tools['animal_models'].mappings['B6.129(Cg)-Nf1tm1Par/J']",
        "description": "Access tool metadata by tool type and name"
    }

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    save_json_file(output_file, lookup)
    print(f"✓ Created lookup service: {output_file}")


def create_schematic_integration_docs(output_file: str) -> None:
    """Create documentation for integrating with schematic."""

    docs = """# Schematic Integration Guide

## Overview

This guide explains how to integrate auto-generated research tool enums and mappings
with schematic for automatic field population.

## Integration Steps

### 1. Reference Auto-Generated Enums

The registered JSON schemas have been updated to use auto-generated enums.
These are automatically updated weekly via GitHub Actions.

### 2. Implement Auto-Fill in Schematic

Use the auto-fill configuration file to implement field population:

```python
import json

# Load auto-fill config
with open('auto-generated/autofill-config.json') as f:
    autofill_config = json.load(f)

# Load lookup service
with open('auto-generated/lookup-service.json') as f:
    lookup_service = json.load(f)

# Example: Auto-fill when modelSystemName is selected
def autofill_fields(schema_name, trigger_field, selected_value):
    # Find applicable rule
    for rule in autofill_config['rules']:
        if rule['schema'] == schema_name and rule['triggerField'] == trigger_field:
            # Get tool type from mapping source
            tool_type = rule['mappingSource'].split('/')[-1].replace('_mappings.json', '')

            # Lookup the tool's attributes
            if tool_type in lookup_service['tools']:
                mappings = lookup_service['tools'][tool_type]['mappings']
                if selected_value in mappings:
                    attributes = mappings[selected_value]

                    # Auto-fill fields
                    auto_values = {}
                    for schema_field, mapping_field in rule['autoFields'].items():
                        if mapping_field in attributes:
                            auto_values[schema_field] = attributes[mapping_field]

                    return auto_values

    return {}

# Usage example
selected_model = "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
auto_values = autofill_fields(
    'AnimalIndividualTemplate.json',
    'modelSystemName',
    selected_model
)
# Returns: {'species': 'Mus musculus', 'genotype': '...', 'backgroundStrain': '...'}
```

### 3. Update DCA Configuration

For Data Curator App integration:

```javascript
// In DCA config
{
  "autoFill": {
    "enabled": true,
    "configFile": "auto-generated/autofill-config.json",
    "lookupService": "auto-generated/lookup-service.json",
    "behavior": "suggest" // or "force"
  }
}
```

### 4. Validation

When validating metadata, ensure that auto-filled values match the mappings:

```python
def validate_autofilled_fields(schema_name, data):
    # If modelSystemName is set, validate other fields match mappings
    if 'modelSystemName' in data:
        expected = autofill_fields(schema_name, 'modelSystemName', data['modelSystemName'])

        for field, expected_value in expected.items():
            if field in data and data[field] != expected_value:
                warnings.append(f"Field {field} doesn't match expected value for {data['modelSystemName']}")
```

## Files Generated

- `auto-generated/autofill-config.json` - Configuration for auto-fill rules
- `auto-generated/lookup-service.json` - Unified lookup for all tool metadata
- `auto-generated/enums/*.json` - JSON Schema enumerations
- `auto-generated/mappings/*.json` - Tool attribute mappings

## Behavior Options

### Suggest (Recommended)
- Auto-fills empty fields
- Doesn't override user-entered values
- Shows suggestions/warnings for mismatches

### Force
- Always overwrites with mapped values
- Prevents user from entering conflicting data
- Use with caution

## Testing

Test auto-fill functionality:

```bash
# Run schematic with auto-fill enabled
schematic model \
  --config config.yml \
  --autofill auto-generated/autofill-config.json \
  validate \
  --manifest test_manifest.csv
```

## Questions?

See `auto-generated/README.md` for more information.
"""

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(docs)
    print(f"✓ Created schematic integration docs: {output_file}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description='Integrate auto-generated tool mappings with registered schemas'
    )
    parser.add_argument(
        '--schemas-dir',
        default='registered-json-schemas',
        help='Directory containing registered JSON schemas'
    )
    parser.add_argument(
        '--auto-generated-dir',
        default='auto-generated',
        help='Directory containing auto-generated enums and mappings'
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        default=True,
        help='Create backups of modified schemas'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()

    print("="*60)
    print("INTEGRATING TOOL MAPPINGS WITH SCHEMAS")
    print("="*60)

    if args.dry_run:
        print("\n[DRY RUN MODE - No files will be modified]\n")

    # Update registered schemas with auto-generated enums
    print("\n1. Updating registered schemas...")
    updated_count = 0

    for schema_file, config in SCHEMA_INTEGRATIONS.items():
        schema_path = os.path.join(args.schemas_dir, schema_file)
        enum_path = config['enum_source']

        print(f"\n{schema_file}:")

        if args.dry_run:
            if os.path.exists(schema_path) and os.path.exists(enum_path):
                enum_data = load_json_file(enum_path)
                print(f"  Would update {config['primary_field']} with {len(enum_data['enum'])} values")
                updated_count += 1
        else:
            if update_schema_with_enum(
                schema_path,
                enum_path,
                config['primary_field'],
                args.backup
            ):
                updated_count += 1

    print(f"\n  → Updated {updated_count} schema(s)")

    # Create auto-fill configuration
    if not args.dry_run:
        print("\n2. Creating auto-fill configuration...")
        create_autofill_config(
            SCHEMA_INTEGRATIONS,
            os.path.join(args.auto_generated_dir, 'autofill-config.json')
        )

        # Create lookup service
        print("\n3. Creating lookup service...")
        mapping_files = {
            'animal_models': 'auto-generated/mappings/animal_models_mappings.json',
            'cell_lines': 'auto-generated/mappings/cell_lines_mappings.json',
            'antibodies': 'auto-generated/mappings/antibodies_mappings.json',
            'genetic_reagents': 'auto-generated/mappings/genetic_reagents_mappings.json',
            'biobanks': 'auto-generated/mappings/biobanks_mappings.json',
        }
        create_lookup_service(
            mapping_files,
            os.path.join(args.auto_generated_dir, 'lookup-service.json')
        )

        # Create integration documentation
        print("\n4. Creating integration documentation...")
        create_schematic_integration_docs(
            os.path.join(args.auto_generated_dir, 'SCHEMATIC_INTEGRATION.md')
        )

    print("\n" + "="*60)
    print("INTEGRATION COMPLETE")
    print("="*60)

    if not args.dry_run:
        print("\nNext steps:")
        print("1. Review updated registered schemas")
        print("2. Read auto-generated/SCHEMATIC_INTEGRATION.md")
        print("3. Implement auto-fill in schematic/DCA")
        print("4. Test with sample manifests")

    print("="*60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
