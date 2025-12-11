#!/usr/bin/env python3
"""
Split materialized view into separate files by resource type.

This script takes the materialized view JSON and splits it into
separate files for each resource type (animal models, cell lines, etc.)
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any


RESOURCE_TYPE_MAPPING = {
    'Animal Model': 'animal_models',
    'Cell Line': 'cell_lines',
    'Antibody': 'antibodies',
    'Genetic Reagent': 'genetic_reagents',
    'Biobank': 'biobanks',
}


def split_materialized_view(input_file: str, output_dir: str) -> Dict[str, int]:
    """
    Split materialized view by resource type.

    Args:
        input_file: Path to materialized view JSON file
        output_dir: Output directory for split files

    Returns:
        Dictionary with counts by resource type
    """
    print(f"Loading materialized view from {input_file}...")

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"  ✓ Loaded {len(data)} records")

    # Group by resource type
    by_type = {tool_type: [] for tool_type in RESOURCE_TYPE_MAPPING.values()}

    for record in data:
        resource_type = record.get('resourceType')
        if resource_type in RESOURCE_TYPE_MAPPING:
            tool_type = RESOURCE_TYPE_MAPPING[resource_type]
            by_type[tool_type].append(record)
        else:
            print(f"  ⚠ Unknown resource type: {resource_type}")

    # Save split files
    os.makedirs(output_dir, exist_ok=True)
    counts = {}

    for tool_type, records in by_type.items():
        if records:
            output_file = os.path.join(output_dir, f'{tool_type}.json')
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2, ensure_ascii=False, default=str)
            counts[tool_type] = len(records)
            print(f"  ✓ Saved {len(records):4} {tool_type:20} → {output_file}")

    return counts


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description='Split materialized view by resource type'
    )
    parser.add_argument(
        '--input',
        default='auto-generated/raw/materialized_view.json',
        help='Input materialized view JSON file'
    )
    parser.add_argument(
        '--output',
        default='auto-generated/raw/',
        help='Output directory for split files'
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        return 1

    counts = split_materialized_view(args.input, args.output)

    print("\n" + "="*60)
    print("SPLIT SUMMARY")
    print("="*60)
    for tool_type, count in sorted(counts.items()):
        print(f"{tool_type:20} {count:5} records")
    print(f"{'TOTAL':20} {sum(counts.values()):5} records")
    print("="*60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
