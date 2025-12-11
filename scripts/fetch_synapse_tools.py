#!/usr/bin/env python3
"""
Fetch research tools data from Synapse tables.

This script fetches data from multiple Synapse research tool tables
(animal models, cell lines, antibodies, genetic reagents, biobanks)
and saves them as JSON files for processing.
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any
from datetime import datetime


# Default Synapse table IDs for NF research tools
DEFAULT_TABLES = {
    'animal_models': 'syn26486808',
    'cell_lines': 'syn26486823',
    'antibodies': 'syn26486811',
    'genetic_reagents': 'syn26486832',
    'biobanks': 'syn26486821',
    'materialized_view': 'syn51730943'
}


def fetch_synapse_table(syn, table_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all data from a Synapse table.

    Args:
        syn: Synapse client instance
        table_id: Synapse table ID

    Returns:
        List of dictionaries containing table data
    """
    print(f"Fetching data from {table_id}...")

    try:
        # Query all columns from the table
        query = f"SELECT * FROM {table_id}"
        results = syn.tableQuery(query)

        # Convert to list of dictionaries
        data = []
        df = results.asDataFrame()

        # Convert DataFrame to list of dicts, handling NaN values
        for _, row in df.iterrows():
            row_dict = {}
            for col, val in row.items():
                # Skip ROW_ID, ROW_VERSION, ROW_ETAG if present
                if col in ['ROW_ID', 'ROW_VERSION', 'ROW_ETAG']:
                    continue
                # Handle NaN and None values
                if val is None or (isinstance(val, float) and str(val) == 'nan'):
                    row_dict[col] = None
                else:
                    row_dict[col] = val
            data.append(row_dict)

        print(f"  ✓ Fetched {len(data)} records from {table_id}")
        return data

    except Exception as e:
        print(f"  ✗ Error fetching data from {table_id}: {e}")
        return []


def save_json(data: Any, file_path: str) -> None:
    """
    Save data to JSON file with pretty formatting.

    Args:
        data: Data to save
        file_path: Path to output JSON file
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    print(f"  ✓ Saved to {file_path}")


def main():
    """Main function to fetch research tools data from Synapse."""
    parser = argparse.ArgumentParser(
        description='Fetch NF research tools data from Synapse tables',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--tables',
        default=','.join(DEFAULT_TABLES.values()),
        help='Comma-separated list of Synapse table IDs to fetch'
    )
    parser.add_argument(
        '--output',
        default='auto-generated/raw/',
        help='Output directory for JSON files (default: auto-generated/raw/)'
    )
    parser.add_argument(
        '--use-materialized-view',
        action='store_true',
        help='Use the materialized view instead of individual tables'
    )

    args = parser.parse_args()

    try:
        import synapseclient
        import pandas as pd
    except ImportError:
        print("Error: Required packages not installed.")
        print("Please install: pip install synapseclient pandas")
        return 1

    # Initialize Synapse client
    print("Initializing Synapse client...")
    syn = synapseclient.Synapse()

    # Try to login
    try:
        if os.getenv('SYNAPSE_AUTH_TOKEN'):
            syn.login(authToken=os.getenv('SYNAPSE_AUTH_TOKEN'), silent=True)
            print("  ✓ Logged in with SYNAPSE_AUTH_TOKEN")
        else:
            syn.login(silent=True)
            print("  ✓ Logged in with cached credentials")
    except Exception as e:
        print(f"  ✗ Login failed: {e}")
        print("  → Attempting anonymous access...")

    # Determine which tables to fetch
    if args.use_materialized_view:
        print("\nUsing materialized view...")
        tables_to_fetch = {'materialized_view': DEFAULT_TABLES['materialized_view']}
    else:
        print("\nFetching from individual tables...")
        table_ids = args.tables.split(',')
        tables_to_fetch = {
            'animal_models': table_ids[0] if len(table_ids) > 0 else DEFAULT_TABLES['animal_models'],
            'cell_lines': table_ids[1] if len(table_ids) > 1 else DEFAULT_TABLES['cell_lines'],
            'antibodies': table_ids[2] if len(table_ids) > 2 else DEFAULT_TABLES['antibodies'],
            'genetic_reagents': table_ids[3] if len(table_ids) > 3 else DEFAULT_TABLES['genetic_reagents'],
            'biobanks': table_ids[4] if len(table_ids) > 4 else DEFAULT_TABLES['biobanks'],
        }

    # Fetch data from each table
    all_data = {}
    metadata = {
        'fetch_date': datetime.utcnow().isoformat() + 'Z',
        'tables': {},
        'total_records': 0
    }

    for tool_type, table_id in tables_to_fetch.items():
        data = fetch_synapse_table(syn, table_id)
        all_data[tool_type] = data

        # Save individual table data
        output_file = os.path.join(args.output, f'{tool_type}.json')
        save_json(data, output_file)

        # Update metadata
        metadata['tables'][tool_type] = {
            'synapse_id': table_id,
            'record_count': len(data)
        }
        metadata['total_records'] += len(data)

    # Save metadata
    metadata_file = os.path.join(args.output, 'fetch_metadata.json')
    save_json(metadata, metadata_file)

    # Print summary
    print("\n" + "="*60)
    print("FETCH SUMMARY")
    print("="*60)
    print(f"Fetch date: {metadata['fetch_date']}")
    print(f"Total records: {metadata['total_records']}")
    print("\nRecords by type:")
    for tool_type, info in metadata['tables'].items():
        print(f"  {tool_type:20} {info['record_count']:5} records ({info['synapse_id']})")
    print("="*60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
