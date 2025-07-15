#!/usr/bin/env python3
"""
Sync modelSystemName values from NFTC truth table.

This script fetches data from Synapse table syn26450069 and updates
the CellLineModel.yaml and AnimalModel.yaml enum files based on the
resourceType column.
"""

import os
import sys
import yaml
from typing import Dict, List, Any
import argparse


def fetch_synapse_data(synapse_id: str) -> List[Dict[str, Any]]:
    """
    Fetch data from Synapse table.
    
    Args:
        synapse_id: Synapse table ID (e.g., syn26450069)
        
    Returns:
        List of dictionaries containing table data
    """
    try:
        import synapseclient
        from synapseclient import Synapse
        
        # Initialize Synapse client
        syn = Synapse()
        syn.login(silent=True)
        
        # Query the table
        query = f"SELECT * FROM {synapse_id}"
        results = syn.tableQuery(query)
        
        # Convert to list of dictionaries
        data = []
        for row in results:
            data.append(dict(row))
            
        return data
        
    except ImportError:
        print("Warning: synapseclient not available. Using mock data for testing.")
        # Return mock data for testing when synapseclient is not available
        return [
            {
                'resourceName': 'Test Cell Line 1',
                'rrid': 'CVCL_0001',
                'resourceType': 'cell line',
                'description': 'Test cell line description'
            },
            {
                'resourceName': 'Test Mouse Model 1', 
                'rrid': 'MGI:0001',
                'resourceType': 'animal model',
                'description': 'Test mouse model description'
            }
        ]
    except Exception as e:
        print(f"Error fetching data from Synapse: {e}")
        return []


def format_enum_entry(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a resource entry for YAML enum.
    
    Args:
        resource: Dictionary containing resource data
        
    Returns:
        Dictionary formatted for YAML enum entry
    """
    entry = {}
    
    # Use resourceName as the key
    name = resource.get('resourceName', '').strip()
    if not name:
        return None
        
    # Build the entry
    entry_data = {}
    
    # Add description if available
    description = resource.get('description', '').strip()
    if description:
        entry_data['description'] = description
    else:
        entry_data['description'] = f"{name}"
        
    # Add source/meaning from RRID if available
    rrid = resource.get('rrid', '').strip()
    if rrid:
        if rrid.startswith('CVCL_'):
            entry_data['source'] = f"https://web.expasy.org/cellosaurus/{rrid}"
        elif rrid.startswith('MGI:'):
            entry_data['source'] = f"http://www.informatics.jax.org/accession/{rrid}"
        else:
            entry_data['source'] = rrid
    
    return {name: entry_data}


def update_enum_file(file_path: str, enum_name: str, entries: List[Dict[str, Any]]) -> None:
    """
    Update an enum YAML file with new entries.
    
    Args:
        file_path: Path to the YAML file
        enum_name: Name of the enum (e.g., 'CellLineModel', 'AnimalModel')  
        entries: List of formatted enum entries
    """
    # Combine all entries into one dictionary
    combined_entries = {}
    for entry in entries:
        if entry:
            combined_entries.update(entry)
    
    # Sort entries by key name
    sorted_entries = dict(sorted(combined_entries.items()))
    
    # Create the YAML structure
    enum_data = {
        'enums': {
            enum_name: {
                'permissible_values': sorted_entries
            }
        }
    }
    
    # Write to file
    with open(file_path, 'w', encoding='utf-8') as f:
        yaml.dump(enum_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    print(f"Updated {file_path} with {len(sorted_entries)} entries")


def main():
    """Main function to sync model system data."""
    parser = argparse.ArgumentParser(description='Sync model system names from Synapse table')
    parser.add_argument('--synapse-id', default='syn26450069', 
                       help='Synapse table ID (default: syn26450069)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Print what would be done without making changes')
    
    args = parser.parse_args()
    
    # Get the repository root directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    
    # Define file paths
    cell_line_path = os.path.join(repo_root, 'modules', 'Sample', 'CellLineModel.yaml')
    animal_model_path = os.path.join(repo_root, 'modules', 'Sample', 'AnimalModel.yaml')
    
    print(f"Fetching data from Synapse table {args.synapse_id}...")
    
    # Fetch data from Synapse
    data = fetch_synapse_data(args.synapse_id)
    
    if not data:
        print("No data fetched. Exiting.")
        return 1
    
    print(f"Fetched {len(data)} records from Synapse")
    
    # Separate data by resource type
    cell_lines = []
    animal_models = []
    
    for resource in data:
        resource_type = resource.get('resourceType', '').lower().strip()
        
        if 'cell line' in resource_type:
            formatted = format_enum_entry(resource)
            if formatted:
                cell_lines.append(formatted)
        elif 'animal model' in resource_type or 'mouse' in resource_type:
            formatted = format_enum_entry(resource)
            if formatted:
                animal_models.append(formatted)
    
    print(f"Found {len(cell_lines)} cell lines and {len(animal_models)} animal models")
    
    if args.dry_run:
        print("DRY RUN - would update:")
        print(f"  {cell_line_path} with {len(cell_lines)} cell line entries")
        print(f"  {animal_model_path} with {len(animal_models)} animal model entries")
        return 0
    
    # Update the enum files
    if cell_lines:
        update_enum_file(cell_line_path, 'CellLineModel', cell_lines)
    
    if animal_models:
        update_enum_file(animal_model_path, 'AnimalModel', animal_models)
    
    print("Sync completed successfully!")
    return 0


if __name__ == '__main__':
    sys.exit(main())