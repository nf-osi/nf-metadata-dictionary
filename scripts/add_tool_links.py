#!/usr/bin/env python3
"""
Add see_also links to schema enum values for NF Tools Central resources.

This script queries syn51730943 to get resource IDs and updates the schema YAML files
to include see_also links pointing to the NF Tools Central detail pages.

Usage:
    export SYNAPSE_AUTH_TOKEN=your_token
    python scripts/add_tool_links.py [--dry-run]
"""

import synapseclient
import pandas as pd
import os
import yaml
import argparse
from typing import Dict, List, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# Resource ID column name in syn51730943
# Run scripts/explore_tools_table.py to find the correct column name
RESOURCE_ID_COLUMN = 'resourceId'  # Change this if the column name is different

# Resource type configuration
RESOURCE_CONFIG = {
    'Cell Line': {
        'table_id': 'syn51730943',
        'resource_type': 'Cell Line',
        'yaml_file': 'modules/Sample/CellLineModel.yaml',
        'enum_name': 'CellLineEnum'
    },
    'Animal Model': {
        'table_id': 'syn51730943',
        'resource_type': 'Animal Model',
        'yaml_file': 'modules/Sample/AnimalModel.yaml',
        'enum_name': 'AnimalModel'
    }
    # Note: Antibody and other resource types don't have enums - they use free-text fields
    # For these, consider creating a separate JSON mapping file
}


def get_synapse_client():
    """Initialize and return Synapse client."""
    auth_token = os.getenv('SYNAPSE_AUTH_TOKEN')

    syn = synapseclient.Synapse()

    if auth_token:
        # Authenticate with token if available
        syn.login(authToken=auth_token, silent=True)
        logger.info("✓ Connected to Synapse (authenticated)")
    else:
        # Try anonymous access for public tables like syn51730943
        logger.info("⚠ No SYNAPSE_AUTH_TOKEN found - attempting anonymous access")
        logger.info("✓ Connected to Synapse (anonymous)")

    return syn


def query_tools_table(syn: synapseclient.Synapse, resource_type: str) -> pd.DataFrame:
    """
    Query syn51730943 for all resources of a given type.

    Args:
        syn: Synapse client
        resource_type: Resource type to query (e.g., 'Cell Line', 'Animal Model')

    Returns:
        DataFrame with resource data including resourceId
    """
    table_id = 'syn51730943'
    query = f"SELECT * FROM {table_id} WHERE resourceType = '{resource_type}'"

    logger.info(f"Querying '{resource_type}' resources from {table_id}...")
    results = syn.tableQuery(query)
    df = results.asDataFrame()
    logger.info(f"  → Found {len(df)} '{resource_type}' resources")

    return df


def build_nf_portal_url(resource_id: str) -> str:
    """
    Build NF Tools Central detail page URL.

    Args:
        resource_id: Resource ID (UUID or ROW_ID)

    Returns:
        URL to NF Tools Central detail page
    """
    return f"https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId={resource_id}"


def get_resource_mappings(syn: synapseclient.Synapse) -> Dict[str, Dict[str, str]]:
    """
    Query all resource types and build name -> URL mappings.

    Returns:
        Dict mapping resource_type to {resourceName: url}
    """
    mappings = {}

    for resource_key, config in RESOURCE_CONFIG.items():
        resource_type = config['resource_type']
        df = query_tools_table(syn, resource_type)

        # Build URL mapping
        resource_urls = {}
        for _, row in df.iterrows():
            resource_name = row.get('resourceName')

            # Get resource ID from configured column
            resource_id = None
            if RESOURCE_ID_COLUMN in row and pd.notna(row[RESOURCE_ID_COLUMN]):
                resource_id = row[RESOURCE_ID_COLUMN]
            # Fallback to ROW_ID if resourceId column not found
            elif 'ROW_ID' in row and pd.notna(row['ROW_ID']):
                resource_id = str(row['ROW_ID'])
                logger.warning(f"  Using ROW_ID for {resource_name} - check RESOURCE_ID_COLUMN setting")

            if resource_name and resource_id:
                url = build_nf_portal_url(resource_id)
                resource_urls[resource_name] = url
                logger.debug(f"  {resource_name} -> {url}")

        logger.info(f"  → Mapped {len(resource_urls)} '{resource_type}' resources to URLs")
        mappings[resource_key] = resource_urls

    return mappings


def load_yaml_safe(file_path: str) -> Tuple[dict, str]:
    """
    Load YAML file preserving comments and structure.

    Returns:
        (parsed_data, raw_content)
    """
    with open(file_path, 'r') as f:
        content = f.read()

    data = yaml.safe_load(content)
    return data, content


def update_yaml_enum(file_path: str, enum_name: str, url_mapping: Dict[str, str], dry_run: bool = False) -> int:
    """
    Update YAML file to add see_also links to enum values.

    Args:
        file_path: Path to YAML file
        enum_name: Name of enum to update (if None, updates first enum found)
        url_mapping: Dict mapping enum value names to URLs
        dry_run: If True, don't write changes

    Returns:
        Number of values updated
    """
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return 0

    logger.info(f"Processing {file_path}...")

    # Load YAML
    data, raw_content = load_yaml_safe(file_path)

    # Find the enum
    if 'enums' not in data:
        logger.warning(f"  No enums found in {file_path}")
        return 0

    # Get the target enum (first one if enum_name not specified)
    target_enum = None
    if enum_name and enum_name in data['enums']:
        target_enum = data['enums'][enum_name]
    elif len(data['enums']) == 1:
        target_enum = list(data['enums'].values())[0]
    else:
        logger.warning(f"  Enum '{enum_name}' not found in {file_path}")
        return 0

    if not target_enum or 'permissible_values' not in target_enum:
        logger.warning(f"  No permissible_values found")
        return 0

    # Update permissible values
    updated_count = 0
    for value_name, value_data in target_enum['permissible_values'].items():
        if value_name in url_mapping:
            # Check if see_also already exists
            if value_data is None:
                target_enum['permissible_values'][value_name] = {}
                value_data = target_enum['permissible_values'][value_name]

            if not isinstance(value_data, dict):
                logger.warning(f"  Skipping {value_name} - value_data is not a dict")
                continue

            url = url_mapping[value_name]

            # Add or update see_also
            if 'see_also' not in value_data:
                value_data['see_also'] = [url]
                updated_count += 1
                logger.info(f"  ✓ Added see_also to '{value_name}'")
            elif url not in value_data['see_also']:
                if not isinstance(value_data['see_also'], list):
                    value_data['see_also'] = [value_data['see_also']]
                value_data['see_also'].append(url)
                updated_count += 1
                logger.info(f"  ✓ Updated see_also for '{value_name}'")
            else:
                logger.debug(f"  - '{value_name}' already has this URL")

    # Write back to file
    if updated_count > 0 and not dry_run:
        with open(file_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        logger.info(f"  → Updated {updated_count} values in {file_path}")
    elif dry_run:
        logger.info(f"  → [DRY RUN] Would update {updated_count} values")

    return updated_count


def main():
    parser = argparse.ArgumentParser(description='Add see_also links to schema enums')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without writing')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("Adding NF Tools Central links to schema enums")
    logger.info("=" * 70)

    # Connect to Synapse
    syn = get_synapse_client()

    # Get resource mappings
    logger.info("\nQuerying resource data from syn51730943...")
    mappings = get_resource_mappings(syn)

    # Update YAML files
    logger.info("\nUpdating YAML files...")
    total_updated = 0

    for resource_key, config in RESOURCE_CONFIG.items():
        yaml_file = config.get('yaml_file')
        if not yaml_file:
            logger.info(f"Skipping {resource_key} - no YAML file configured")
            continue

        enum_name = config.get('enum_name')
        url_mapping = mappings.get(resource_key, {})

        if not url_mapping:
            logger.warning(f"No URL mappings for {resource_key}")
            continue

        count = update_yaml_enum(yaml_file, enum_name, url_mapping, dry_run=args.dry_run)
        total_updated += count

    # Summary
    logger.info("\n" + "=" * 70)
    if args.dry_run:
        logger.info(f"DRY RUN: Would update {total_updated} enum values")
    else:
        logger.info(f"✓ Successfully updated {total_updated} enum values")
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
