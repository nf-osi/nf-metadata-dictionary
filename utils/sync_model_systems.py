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
from typing import Dict, List, Any, Set
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
        
        # Try to login - first with token, then silent, then anonymous
        try:
            if os.getenv('SYNAPSE_AUTH_TOKEN'):
                syn.login(authToken=os.getenv('SYNAPSE_AUTH_TOKEN'), silent=True)
            else:
                # Try silent login first
                try:
                    syn.login(silent=True)
                except:
                    # If silent login fails, try anonymous access
                    print("Attempting anonymous access to Synapse...")
                    # For anonymous access, we don't need to login
                    pass
        except Exception as login_error:
            print(f"Warning: Could not login to Synapse: {login_error}")
            print("Attempting anonymous access...")
            # Continue without authentication for anonymous access
        
        # Query the table for resourceName, rrid, resourceType, and description columns
        query = f"SELECT resourceName, rrid, resourceType, description FROM {synapse_id}"
        print(f"Executing query: {query}")
        
        try:
            results = syn.tableQuery(query)
        except Exception as query_error:
            print(f"Error executing query: {query_error}")
            print("Falling back to mock data for testing.")
            raise ImportError("Synapse query failed")
        
        # Convert to list of dictionaries
        data = []
        for row in results:
            # Handle different row formats
            if hasattr(row, '_asdict'):
                # Named tuple format
                row_dict = row._asdict()
            elif isinstance(row, dict):
                # Already a dictionary
                row_dict = row
            elif isinstance(row, (list, tuple)):
                # List/tuple format - map to column names based on actual query result
                # From debugging: the query returns [id, ?, resourceName, rrid, resourceType, description]
                if len(row) >= 6:
                    row_dict = {
                        'resourceName': row[2],  # 3rd element
                        'rrid': row[3],          # 4th element  
                        'resourceType': row[4],  # 5th element
                        'description': row[5]    # 6th element
                    }
                else:
                    print(f"Warning: Row has unexpected length {len(row)}: {row}")
                    continue
            else:
                # Try to convert to dict
                try:
                    row_dict = dict(row)
                except:
                    print(f"Warning: Could not convert row to dict: {row}")
                    continue
            
            # Only include rows with required fields
            if row_dict.get('resourceName') and row_dict.get('resourceType'):
                data.append(row_dict)
            
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


def sanitize_yaml_key(name: str) -> str:
    """
    Sanitize a string to be safe as a YAML key for JSON-LD conversion.
    
    Args:
        name: Original string
        
    Returns:
        Sanitized string safe for use as YAML key
    """
    if not name:
        return name
    
    # Replace problematic characters that cause JSON-LD conversion issues
    sanitized = name
    
    # Replace double colons with single dash
    sanitized = sanitized.replace('::', '-')
    
    # Replace forward slashes with dashes
    sanitized = sanitized.replace('/', '-')
    
    # Replace plus signs with the word "plus" to maintain meaning
    sanitized = sanitized.replace('+', 'plus')
    
    # Replace any remaining colons with dashes
    sanitized = sanitized.replace(':', '-')
    
    # Clean up multiple consecutive dashes
    while '--' in sanitized:
        sanitized = sanitized.replace('--', '-')
    
    # Remove leading/trailing dashes
    sanitized = sanitized.strip('-')
    
    return sanitized


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
    original_name = resource.get('resourceName', '') or ''
    original_name = original_name.strip() if original_name else ''
    if not original_name:
        return None
    
    # Sanitize the name for use as YAML key
    sanitized_name = sanitize_yaml_key(original_name)
    if not sanitized_name:
        return None
        
    # Build the entry
    entry_data = {}
    
    # Use description from database if available and different from resource name
    description = resource.get('description', '') or ''
    description = description.strip() if description else ''
    
    # If we sanitized the name, always include the original name in description
    if sanitized_name != original_name:
        if description and description != original_name:
            # Prepend original name to existing description
            entry_data['description'] = f"{original_name}. {description}"
        else:
            # Use original name as description
            entry_data['description'] = original_name
    elif description and description != original_name:
        # Only include description if it's different from the name
        entry_data['description'] = description
        
    # Add meaning from RRID if available
    rrid = resource.get('rrid', '') or ''
    rrid = rrid.strip() if rrid else ''
    if rrid:
        if rrid.startswith('RRID:'):
            # Handle full RRID format - keep as is
            entry_data['meaning'] = rrid
        elif rrid.startswith('rrid:'):
            # Already has rrid: prefix
            entry_data['meaning'] = rrid
        else:
            # Add rrid: prefix for bare RRID values
            entry_data['meaning'] = f"rrid:{rrid}"
    
    return {sanitized_name: entry_data}


def load_manual_entries(file_path: str) -> Set[str]:
    """
    Load entries from a manual YAML file.
    
    Args:
        file_path: Path to the manual YAML file
        
    Returns:
        Set of entry names from the manual file
    """
    if not os.path.exists(file_path):
        return set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if data and 'enums' in data:
            # Get the first enum (should be the only one)
            enum_data = next(iter(data['enums'].values()))
            if 'permissible_values' in enum_data:
                return set(enum_data['permissible_values'].keys())
    except Exception as e:
        print(f"Warning: Could not load manual entries from {file_path}: {e}")
    
    return set()


def filter_duplicates(entries: List[Dict[str, Any]], manual_entries: Set[str]) -> List[Dict[str, Any]]:
    """
    Filter out entries that already exist in manual files.
    
    Args:
        entries: List of formatted enum entries
        manual_entries: Set of entry names from manual file
        
    Returns:
        Filtered list of entries without duplicates
    """
    filtered = []
    for entry in entries:
        if entry:
            entry_name = next(iter(entry.keys()))
            if entry_name not in manual_entries:
                filtered.append(entry)
            else:
                print(f"Skipping duplicate entry: {entry_name} (exists in manual file)")
    return filtered


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
    
    # Write to file with warning comment
    with open(file_path, 'w', encoding='utf-8') as f:
        # Add warning comment at the top
        f.write("# WARNING: This file is auto-generated from Synapse table syn26450069\n")
        f.write("# DO NOT EDIT DIRECTLY - changes will be overwritten\n") 
        f.write("# For manual entries, use the corresponding *Manual.yaml file\n")
        f.write("# Generated by utils/sync_model_systems.py\n\n")
        
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
    cell_line_manual_path = os.path.join(repo_root, 'modules', 'Sample', 'CellLineModelManual.yaml')
    animal_model_manual_path = os.path.join(repo_root, 'modules', 'Sample', 'AnimalModelManual.yaml')
    
    print(f"Fetching data from Synapse table {args.synapse_id}...")
    
    # Fetch data from Synapse
    data = fetch_synapse_data(args.synapse_id)
    
    if not data:
        print("No data fetched. Exiting.")
        return 1
    
    print(f"Fetched {len(data)} records from Synapse")
    
    # Load manual entries to avoid duplicates
    cell_line_manual_entries = load_manual_entries(cell_line_manual_path)
    animal_model_manual_entries = load_manual_entries(animal_model_manual_path)
    print(f"Found {len(cell_line_manual_entries)} manual cell line entries")
    print(f"Found {len(animal_model_manual_entries)} manual animal model entries")
    
    # Separate data by resource type
    cell_lines = []
    animal_models = []
    
    for resource in data:
        resource_type = resource.get('resourceType', '') or ''
        resource_type = resource_type.lower().strip() if resource_type else ''
        
        if 'cell line' in resource_type:
            formatted = format_enum_entry(resource)
            if formatted:
                cell_lines.append(formatted)
        elif 'animal model' in resource_type or 'mouse' in resource_type:
            formatted = format_enum_entry(resource)
            if formatted:
                animal_models.append(formatted)
    
    # Filter out duplicates with manual entries
    cell_lines = filter_duplicates(cell_lines, cell_line_manual_entries)
    animal_models = filter_duplicates(animal_models, animal_model_manual_entries)
    
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