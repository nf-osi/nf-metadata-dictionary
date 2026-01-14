#!/usr/bin/env python3
"""
Sync modelSystemName values from NFTC truth table.

This script fetches data from Synapse table syn26450069 and updates
the CellLineModel.yaml and AnimalModel.yaml enum files based on the
resourceType column. It also fetches resource links from syn51730943
and adds them as 'source' fields.
"""

import os
import sys
import yaml
from typing import Dict, List, Any, Set
import argparse


def fetch_tools_data(synapse_id: str = 'syn51730943', resource_types: List[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch resource data from NF Tools Central table for Antibody and Genetic Reagent.

    Args:
        synapse_id: Synapse table ID for NF Tools Central (default: syn51730943)
        resource_types: List of resource types to fetch (default: ['Antibody', 'Genetic Reagent'])

    Returns:
        Dict mapping resource_type to list of resources with full data
    """
    if resource_types is None:
        resource_types = ['Antibody', 'Genetic Reagent']

    try:
        import synapseclient
        from synapseclient import Synapse

        syn = Synapse()

        # Try to login
        try:
            if os.getenv('SYNAPSE_AUTH_TOKEN'):
                syn.login(authToken=os.getenv('SYNAPSE_AUTH_TOKEN'), silent=True)
            else:
                try:
                    syn.login(silent=True)
                except:
                    pass
        except Exception:
            pass

        results_by_type = {}

        for resource_type in resource_types:
            query = f"SELECT resourceName, resourceId, description, resourceType FROM {synapse_id} WHERE resourceType = '{resource_type}'"
            print(f"Fetching {resource_type} data from {synapse_id}...")

            try:
                results = syn.tableQuery(query)
                data = []

                for row in results:
                    # Handle different row formats
                    if hasattr(row, '_asdict'):
                        row_dict = row._asdict()
                    elif isinstance(row, dict):
                        row_dict = row
                    elif isinstance(row, (list, tuple)) and len(row) >= 6:
                        # Typical format: [ROW_ID, ROW_VERSION, resourceName, resourceId, description, resourceType]
                        row_dict = {
                            'resourceName': row[2],
                            'resourceId': row[3],
                            'description': row[4],
                            'resourceType': row[5]
                        }
                    else:
                        continue

                    # Only include rows with resourceName
                    if row_dict.get('resourceName'):
                        data.append(row_dict)

                results_by_type[resource_type] = data
                print(f"  → Found {len(data)} {resource_type} resources")

            except Exception as query_error:
                print(f"Warning: Could not fetch {resource_type}: {query_error}")
                results_by_type[resource_type] = []

        return results_by_type

    except Exception as e:
        print(f"Error fetching tools data from Synapse: {e}")
        return {rt: [] for rt in resource_types}


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


def fetch_tool_links(synapse_id: str = 'syn51730943') -> Dict[str, Dict[str, str]]:
    """
    Fetch tool links from NF Tools Central table.

    Args:
        synapse_id: Synapse table ID for NF Tools Central (default: syn51730943)

    Returns:
        Dict mapping resource_type to {resourceName: url}
    """
    try:
        import synapseclient
        from synapseclient import Synapse

        syn = Synapse()

        # Try to login - first with token, then silent, then anonymous
        try:
            if os.getenv('SYNAPSE_AUTH_TOKEN'):
                syn.login(authToken=os.getenv('SYNAPSE_AUTH_TOKEN'), silent=True)
            else:
                try:
                    syn.login(silent=True)
                except:
                    pass
        except Exception:
            pass

        # Query for all resources with resourceId
        query = f"SELECT resourceName, resourceId, resourceType FROM {synapse_id}"
        print(f"Fetching tool links from {synapse_id}...")

        try:
            results = syn.tableQuery(query)
        except Exception as query_error:
            print(f"Warning: Could not fetch tool links: {query_error}")
            return {'Cell Line': {}, 'Animal Model': {}, 'Antibody': {}, 'Genetic Reagent': {}}

        # Build URL mappings by resource type
        cell_line_urls = {}
        animal_model_urls = {}
        antibody_urls = {}
        genetic_reagent_urls = {}

        for row in results:
            # Handle different row formats
            if hasattr(row, '_asdict'):
                row_dict = row._asdict()
            elif isinstance(row, dict):
                row_dict = row
            elif isinstance(row, (list, tuple)) and len(row) >= 5:
                # Typical format: [ROW_ID, ROW_VERSION, resourceName, resourceId, resourceType]
                row_dict = {
                    'resourceName': row[2],
                    'resourceId': row[3],
                    'resourceType': row[4]
                }
            else:
                continue

            resource_name = row_dict.get('resourceName')
            resource_id = row_dict.get('resourceId')
            resource_type = row_dict.get('resourceType', '').lower() if row_dict.get('resourceType') else ''

            if resource_name and resource_id:
                url = f"https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId={resource_id}"

                if 'cell line' in resource_type:
                    cell_line_urls[resource_name] = url
                elif 'animal model' in resource_type or 'mouse' in resource_type:
                    animal_model_urls[resource_name] = url
                elif 'antibody' in resource_type:
                    antibody_urls[resource_name] = url
                elif 'genetic reagent' in resource_type:
                    genetic_reagent_urls[resource_name] = url

        print(f"  → Found {len(cell_line_urls)} cell line links")
        print(f"  → Found {len(animal_model_urls)} animal model links")
        print(f"  → Found {len(antibody_urls)} antibody links")
        print(f"  → Found {len(genetic_reagent_urls)} genetic reagent links")

        return {
            'Cell Line': cell_line_urls,
            'Animal Model': animal_model_urls,
            'Antibody': antibody_urls,
            'Genetic Reagent': genetic_reagent_urls
        }

    except Exception as e:
        print(f"Warning: Could not fetch tool links: {e}")
        return {'Cell Line': {}, 'Animal Model': {}, 'Antibody': {}, 'Genetic Reagent': {}}


def needs_yaml_quoting(name: str) -> bool:
    """
    Check if a string needs to be quoted as a YAML key.
    
    Args:
        name: String to check
        
    Returns:
        True if the string contains characters that require quoting in YAML
    """
    if not name:
        return False
    
    # Characters that typically require quoting in YAML keys
    special_chars = [':', '/', '+', '-', '[', ']', '{', '}', '"', "'", '\\', '*', '&', '!', '|', '>', '%', '@', '`']
    
    # Check if name starts with special characters or contains problematic ones
    if name[0] in ['-', '?', ':', '@', '`', '|', '>', '*', '&', '!', '%', '[', ']', '{', '}']:
        return True
    
    # Check for double colons specifically
    if '::' in name:
        return True
        
    # Check for other special characters that might cause issues
    for char in special_chars:
        if char in name:
            return True
            
    return False


def format_enum_entry(resource: Dict[str, Any], source_url: str = None) -> Dict[str, Any]:
    """
    Format a resource entry for YAML enum.

    Args:
        resource: Dictionary containing resource data
        source_url: Optional URL to add as source link

    Returns:
        Dictionary formatted for YAML enum entry
    """
    entry = {}

    # Use resourceName as the key
    original_name = resource.get('resourceName', '') or ''
    original_name = original_name.strip() if original_name else ''
    if not original_name:
        return None

    # Build the entry
    entry_data = {}

    # Use description from database if available and different from resource name
    description = resource.get('description', '') or ''
    description = description.strip() if description else ''

    # Only include description if it exists and is different from the resource name
    if description and description != original_name:
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

    # Add source link if available (changed from see_also to source per issue #789)
    if source_url:
        entry_data['source'] = source_url

    return {original_name: entry_data}


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
    
    # Custom YAML representer to quote keys with spaces or special characters
    def quoted_string_representer(dumper, data):
        if ' ' in data or '::' in data or '+' in data or '/' in data or '-' in data:
            return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')
        return dumper.represent_scalar('tag:yaml.org,2002:str', data)
    
    # Write to file with warning comment and proper quoting
    with open(file_path, 'w', encoding='utf-8') as f:
        # Add warning comment at the top
        f.write("# WARNING: This file is auto-generated from Synapse table syn26450069\n")
        f.write("# DO NOT EDIT DIRECTLY - changes will be overwritten\n") 
        f.write("# For manual entries, use the corresponding *Manual.yaml file\n")
        f.write("# Generated by utils/sync_model_systems.py\n\n")
        
        # Add custom representer for strings to ensure proper quoting
        yaml.add_representer(str, quoted_string_representer)
        
        # Custom YAML dumping to handle special characters in keys
        yaml.dump(enum_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=float('inf'))
    
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
    antibody_path = os.path.join(repo_root, 'modules', 'Experiment', 'Antibody.yaml')
    genetic_reagent_path = os.path.join(repo_root, 'modules', 'Experiment', 'GeneticReagent.yaml')
    
    print(f"Fetching data from Synapse table {args.synapse_id}...")

    # Fetch data from Synapse
    data = fetch_synapse_data(args.synapse_id)

    if not data:
        print("No data fetched. Exiting.")
        return 1

    print(f"Fetched {len(data)} records from Synapse")

    # Fetch tool links from NF Tools Central (syn51730943)
    print("\nFetching tool links from NF Tools Central...")
    tool_links = fetch_tool_links('syn51730943')
    cell_line_links = tool_links.get('Cell Line', {})
    animal_model_links = tool_links.get('Animal Model', {})
    antibody_links = tool_links.get('Antibody', {})
    genetic_reagent_links = tool_links.get('Genetic Reagent', {})
    
    # Load manual entries to avoid duplicates
    cell_line_manual_entries = load_manual_entries(cell_line_manual_path)
    animal_model_manual_entries = load_manual_entries(animal_model_manual_path)
    print(f"Found {len(cell_line_manual_entries)} manual cell line entries")
    print(f"Found {len(animal_model_manual_entries)} manual animal model entries")
    
    # Separate data by resource type and add source links
    cell_lines = []
    animal_models = []

    for resource in data:
        resource_type = resource.get('resourceType', '') or ''
        resource_type = resource_type.lower().strip() if resource_type else ''
        resource_name = resource.get('resourceName', '').strip() if resource.get('resourceName') else ''

        if 'cell line' in resource_type:
            # Get source link for this resource if available
            source_url = cell_line_links.get(resource_name)
            formatted = format_enum_entry(resource, source_url)
            if formatted:
                cell_lines.append(formatted)
        elif 'animal model' in resource_type or 'mouse' in resource_type:
            # Get source link for this resource if available
            source_url = animal_model_links.get(resource_name)
            formatted = format_enum_entry(resource, source_url)
            if formatted:
                animal_models.append(formatted)
    
    # Filter out duplicates with manual entries
    cell_lines = filter_duplicates(cell_lines, cell_line_manual_entries)
    animal_models = filter_duplicates(animal_models, animal_model_manual_entries)

    print(f"Found {len(cell_lines)} cell lines and {len(animal_models)} animal models")

    # Fetch Antibody and Genetic Reagent data from NF Tools Central (syn51730943)
    print("\nFetching Antibody and Genetic Reagent data from NF Tools Central...")
    tools_data = fetch_tools_data('syn51730943', ['Antibody', 'Genetic Reagent'])

    # Format Antibody entries with source links
    antibodies = []
    for resource in tools_data.get('Antibody', []):
        resource_name = resource.get('resourceName', '').strip() if resource.get('resourceName') else ''
        source_url = antibody_links.get(resource_name)
        formatted = format_enum_entry(resource, source_url)
        if formatted:
            antibodies.append(formatted)

    # Format Genetic Reagent entries with source links
    genetic_reagents = []
    for resource in tools_data.get('Genetic Reagent', []):
        resource_name = resource.get('resourceName', '').strip() if resource.get('resourceName') else ''
        source_url = genetic_reagent_links.get(resource_name)
        formatted = format_enum_entry(resource, source_url)
        if formatted:
            genetic_reagents.append(formatted)

    print(f"Found {len(antibodies)} antibodies and {len(genetic_reagents)} genetic reagents")

    if args.dry_run:
        print("DRY RUN - would update:")
        print(f"  {cell_line_path} with {len(cell_lines)} cell line entries")
        print(f"  {animal_model_path} with {len(animal_models)} animal model entries")
        print(f"  {antibody_path} with {len(antibodies)} antibody entries")
        print(f"  {genetic_reagent_path} with {len(genetic_reagents)} genetic reagent entries")
        return 0

    # Update the enum files
    if cell_lines:
        update_enum_file(cell_line_path, 'CellLineModel', cell_lines)

    if animal_models:
        update_enum_file(animal_model_path, 'AnimalModel', animal_models)

    if antibodies:
        update_enum_file(antibody_path, 'AntibodyEnum', antibodies)

    if genetic_reagents:
        update_enum_file(genetic_reagent_path, 'GeneticReagentEnum', genetic_reagents)

    print("Sync completed successfully!")
    return 0


if __name__ == '__main__':
    sys.exit(main())