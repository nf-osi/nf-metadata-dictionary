#!/usr/bin/env python3
"""
Create enum YAML files for Antibody and Genetic Reagent resources.

Usage:
    python scripts/create_antibody_reagent_enums.py
"""

import synapseclient
import pandas as pd
import yaml
from typing import Dict

def query_resources(syn, resource_type: str) -> pd.DataFrame:
    """Query syn51730943 for resources of a given type."""
    table_id = 'syn51730943'
    query = f"SELECT * FROM {table_id} WHERE resourceType = '{resource_type}'"
    print(f"Querying '{resource_type}' resources...")
    results = syn.tableQuery(query)
    df = results.asDataFrame()
    print(f"  → Found {len(df)} resources")
    return df

def build_enum_data(df: pd.DataFrame, resource_type: str) -> dict:
    """Build enum data structure from DataFrame."""
    enum_name = resource_type.replace(' ', '') + 'Enum'

    permissible_values = {}
    for _, row in df.iterrows():
        resource_name = row.get('resourceName')
        resource_id = row.get('resourceId')
        description = row.get('description', '')

        if not resource_name or pd.isna(resource_name):
            continue

        value_data = {}

        # Add description if available
        if description and not pd.isna(description):
            value_data['description'] = str(description)

        # Add see_also link
        if resource_id and not pd.isna(resource_id):
            url = f"https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId={resource_id}"
            value_data['see_also'] = [url]

        permissible_values[resource_name] = value_data if value_data else None

    return {
        'enums': {
            enum_name: {
                'permissible_values': permissible_values
            }
        }
    }

def write_yaml_file(data: dict, file_path: str):
    """Write data to YAML file."""
    with open(file_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"  ✓ Written to {file_path}")

def main():
    print("=" * 70)
    print("Creating Antibody and Genetic Reagent enum files")
    print("=" * 70)

    # Connect to Synapse
    syn = synapseclient.Synapse()
    print("✓ Connected to Synapse (anonymous)\n")

    # Create Antibody enum
    print("\n1. Creating Antibody enum...")
    antibody_df = query_resources(syn, 'Antibody')
    antibody_data = build_enum_data(antibody_df, 'Antibody')
    write_yaml_file(antibody_data, 'modules/Experiment/Antibody.yaml')

    # Create Genetic Reagent enum
    print("\n2. Creating Genetic Reagent enum...")
    reagent_df = query_resources(syn, 'Genetic Reagent')
    reagent_data = build_enum_data(reagent_df, 'GeneticReagent')
    write_yaml_file(reagent_data, 'modules/Experiment/GeneticReagent.yaml')

    # Summary
    print("\n" + "=" * 70)
    print("Summary:")
    print(f"  - Created AntibodyEnum with {len(antibody_data['enums']['AntibodyEnum']['permissible_values'])} values")
    print(f"  - Created GeneticReagentEnum with {len(reagent_data['enums']['GeneticReagentEnum']['permissible_values'])} values")
    print(f"  - Total: {len(antibody_data['enums']['AntibodyEnum']['permissible_values']) + len(reagent_data['enums']['GeneticReagentEnum']['permissible_values'])} resources with see_also links")
    print("=" * 70)

if __name__ == '__main__':
    main()
