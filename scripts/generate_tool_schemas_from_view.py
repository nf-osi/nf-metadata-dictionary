#!/usr/bin/env python3
"""
Generate JSON Schema enums and mappings from the materialized view.

This script is optimized for the materialized view structure which combines
all research tool information from the relational database.
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime


# Map materialized view resourceType to our tool types
RESOURCE_TYPE_MAPPING = {
    'Animal Model': {
        'tool_type': 'animal_models',
        'name_field': 'modelSystemName',
        'id_field': 'rrid',
        'attributes': {
            'species': lambda r: r.get('species', [None])[0] if r.get('species') else None,
            'organism': lambda r: (r.get('species', [None])[0] or '').split()[0] if r.get('species') and r.get('species')[0] else None,
            'genotype': lambda r: r.get('strainNomenclature') if r.get('strainNomenclature') else r.get('backgroundStrain'),
            'backgroundStrain': 'backgroundStrain',
            'RRID': 'rrid',
            'modelSystemType': lambda r: 'animal',
            'geneticModification': lambda r: ', '.join(r.get('animalModelGeneticDisorder', [])) if r.get('animalModelGeneticDisorder') else None,
            'manifestation': lambda r: ', '.join(r.get('animalModelOfManifestation', [])) if r.get('animalModelOfManifestation') else None,
            'institution': 'institution',
        }
    },
    'Cell Line': {
        'tool_type': 'cell_lines',
        'name_field': 'cellLineName',
        'id_field': 'rrid',
        'attributes': {
            'species': lambda r: r.get('species', [None])[0] if r.get('species') else None,
            'tissue': lambda r: ', '.join(r.get('specimenTissueType', [])) if r.get('specimenTissueType') else None,
            'organ': lambda r: r.get('organ'),
            'cellType': lambda r: r.get('cellLineCategory'),
            'disease': lambda r: ', '.join(r.get('cellLineGeneticDisorder', [])) if r.get('cellLineGeneticDisorder') else None,
            'RRID': 'rrid',
            'STRProfile': lambda r: r.get('strProfile'),
            'modelSystemType': lambda r: 'cell line',
            'manifestation': lambda r: ', '.join(r.get('cellLineManifestation', [])) if r.get('cellLineManifestation') else None,
            'category': lambda r: r.get('cellLineCategory'),
            'institution': 'institution',
        }
    },
    'Antibody': {
        'tool_type': 'antibodies',
        'name_field': 'antibodyName',
        'id_field': 'rrid',
        'attributes': {
            'targetProtein': 'targetAntigen',
            'hostOrganism': 'hostOrganism',
            'reactiveSpecies': lambda r: ', '.join(r.get('reactiveSpecies', [])) if r.get('reactiveSpecies') else None,
            'RRID': 'rrid',
            'institution': 'institution',
        }
    },
    'Genetic Reagent': {
        'tool_type': 'genetic_reagents',
        'name_field': 'reagentName',
        'id_field': 'rrid',
        'attributes': {
            'reagentType': lambda r: ', '.join(r.get('vectorType', [])) if r.get('vectorType') else None,
            'targetGene': lambda r: r.get('insertName'),
            'insertSpecies': lambda r: ', '.join(r.get('insertSpecies', [])) if r.get('insertSpecies') else None,
            'RRID': 'rrid',
            'institution': 'institution',
        }
    },
    'Biobank': {
        'tool_type': 'biobanks',
        'name_field': 'biobank',
        'id_field': 'biobankName',
        'attributes': {
            'sampleType': lambda r: ', '.join(r.get('specimenType', [])) if r.get('specimenType') else None,
            'tissue': lambda r: ', '.join(r.get('specimenTissueType', [])) if r.get('specimenTissueType') else None,
            'specimenFormat': lambda r: ', '.join(r.get('specimenFormat', [])) if r.get('specimenFormat') else None,
            'preparation': lambda r: ', '.join(r.get('specimenPreparationMethod', [])) if r.get('specimenPreparationMethod') else None,
            'institution': 'institution',
            'biobankURL': 'biobankURL',
        }
    }
}


def normalize_value(value: Any) -> Optional[Any]:
    """Normalize a value for JSON output."""
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if not value or value.lower() in ['nan', 'none', 'null', 'n/a', '', 'unknown']:
            return None
        return value

    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return None
        normalized = [normalize_value(v) for v in value]
        normalized = [v for v in normalized if v is not None]
        return normalized if normalized else None

    return value


def get_field_value(row: Dict[str, Any], field_spec: Any) -> Optional[Any]:
    """Get a field value using a field specification."""
    if callable(field_spec):
        return normalize_value(field_spec(row))
    elif isinstance(field_spec, str):
        return normalize_value(row.get(field_spec))
    return None


def format_name_with_id(name: str, id_value: Optional[str]) -> str:
    """Format a tool name with its ID."""
    if not name:
        return None

    if id_value and id_value != name:
        # Check if ID is already in the name
        if id_value in name or f"({id_value})" in name:
            return name
        # Format with ID
        if id_value.upper().startswith('RRID:'):
            return f"{name} ({id_value})"
        elif id_value.startswith('rrid:'):
            return f"{name} (RRID:{id_value[5:]})"
        else:
            return f"{name} ({id_value})"

    return name


def process_materialized_view(
    data: List[Dict[str, Any]],
    source_table: str,
    output_dir: str
) -> Dict[str, Any]:
    """Process materialized view and generate all enum and mapping files."""

    print(f"\nProcessing {len(data)} records from materialized view...")

    # Group by resource type
    by_type = {}
    for record in data:
        resource_type = record.get('resourceType')
        if resource_type in RESOURCE_TYPE_MAPPING:
            if resource_type not in by_type:
                by_type[resource_type] = []
            by_type[resource_type].append(record)

    results = []

    # Process each resource type
    for resource_type, records in by_type.items():
        config = RESOURCE_TYPE_MAPPING[resource_type]
        tool_type = config['tool_type']
        name_field = config['name_field']
        id_field = config['id_field']

        print(f"\n{resource_type} ({len(records)} records)...")

        # Generate enum values and mappings
        enum_values = []
        mappings = {}

        for row in records:
            # Get the tool name
            name = get_field_value(row, 'resourceName')
            if not name:
                continue

            # Get the ID
            id_value = get_field_value(row, id_field)

            # Format the name
            formatted_name = format_name_with_id(name, id_value)
            if not formatted_name:
                continue

            enum_values.append(formatted_name)

            # Build attribute mapping
            attributes = {}
            for attr_name, attr_spec in config['attributes'].items():
                value = get_field_value(row, attr_spec)
                if value is not None:
                    attributes[attr_name] = value

            # Add description if available
            description = get_field_value(row, 'description')
            if description and description != name:
                attributes['description'] = description

            # Only add if we have attributes
            if attributes:
                mappings[formatted_name] = attributes

        # Remove duplicates from enum
        seen = set()
        unique_enum_values = []
        for val in enum_values:
            if val not in seen:
                seen.add(val)
                unique_enum_values.append(val)

        # Generate enum schema
        enum_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": f"{name_field} Enumeration (Auto-generated)",
            "description": f"Controlled vocabulary of NF {resource_type.lower()}s from {source_table}",
            "type": "string",
            "enum": sorted(unique_enum_values),
            "meta:sourceTable": source_table,
            "meta:lastUpdated": datetime.now().isoformat() + 'Z',
            "meta:recordCount": len(unique_enum_values)
        }

        # Save enum
        enum_file = os.path.join(output_dir, 'enums', f'{name_field}_enum.json')
        os.makedirs(os.path.dirname(enum_file), exist_ok=True)
        with open(enum_file, 'w', encoding='utf-8') as f:
            json.dump(enum_schema, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Enum: {len(unique_enum_values)} values → {enum_file}")

        # Save mappings
        mapping_file = os.path.join(output_dir, 'mappings', f'{tool_type}_mappings.json')
        os.makedirs(os.path.dirname(mapping_file), exist_ok=True)
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(mappings, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Mappings: {len(mappings)} entries → {mapping_file}")

        results.append({
            'resource_type': resource_type,
            'tool_type': tool_type,
            'enum_count': len(unique_enum_values),
            'mapping_count': len(mappings),
            'status': 'success'
        })

    return results


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description='Generate JSON Schema enums and mappings from materialized view'
    )
    parser.add_argument(
        '--input',
        default='auto-generated/raw/materialized_view.json',
        help='Input materialized view JSON file'
    )
    parser.add_argument(
        '--output',
        default='auto-generated/',
        help='Output directory for generated schemas'
    )
    parser.add_argument(
        '--source-table',
        default='syn51730943',
        help='Source Synapse table ID for metadata'
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        print("Run fetch_synapse_tools.py with --use-materialized-view first")
        return 1

    print("="*60)
    print("GENERATING TOOL SCHEMAS FROM MATERIALIZED VIEW")
    print("="*60)

    # Load data
    with open(args.input, 'r') as f:
        data = json.load(f)

    # Process
    results = process_materialized_view(data, args.source_table, args.output)

    # Generate summary files
    summary = {
        'generation_date': datetime.now().isoformat() + 'Z',
        'source_table': args.source_table,
        'tool_types': results,
        'total_enums': sum(r['enum_count'] for r in results),
        'total_mappings': sum(r['mapping_count'] for r in results)
    }

    # Save LAST_UPDATED.txt
    last_updated_file = os.path.join(args.output, 'LAST_UPDATED.txt')
    with open(last_updated_file, 'w') as f:
        f.write(f"Last Updated: {summary['generation_date']}\n")
        f.write(f"Source Table: {args.source_table}\n")
        f.write(f"Total Enumerations: {summary['total_enums']}\n")
        f.write(f"Total Mappings: {summary['total_mappings']}\n\n")
        f.write("By Tool Type:\n")
        for result in results:
            f.write(f"  {result['resource_type']:20} {result['enum_count']:4} enums, {result['mapping_count']:4} mappings\n")
    print(f"\n✓ Updated: {last_updated_file}")

    # Save metadata
    metadata_file = os.path.join(args.output, 'generation_metadata.json')
    with open(metadata_file, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"✓ Saved: {metadata_file}")

    # Print summary
    print("\n" + "="*60)
    print("GENERATION SUMMARY")
    print("="*60)
    print(f"Generated: {summary['generation_date']}")
    print(f"Source: {args.source_table}")
    print(f"Total enumerations: {summary['total_enums']}")
    print(f"Total mappings: {summary['total_mappings']}")
    print("\nBy tool type:")
    for result in results:
        print(f"  ✓ {result['resource_type']:20} {result['enum_count']:4} enums, {result['mapping_count']:4} mappings")
    print("="*60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
