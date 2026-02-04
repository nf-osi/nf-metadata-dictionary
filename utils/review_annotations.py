#!/usr/bin/env python3
"""
Review Synapse file annotations from materialized view and suggest additions to schema.

This script:
1. Queries Synapse materialized view syn52702673 for file annotations
2. Loads the current schema enum values
3. Identifies free-text values that don't match existing enum permissible values
4. Generates suggestions for new enum values
5. Suggests portal search filters based on annotation patterns
6. Outputs suggestions in a format suitable for PR creation

Usage:
    python review_annotations.py [--output OUTPUT_FILE] [--dry-run] [--limit LIMIT]
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml

try:
    import synapseclient
    from synapseclient import Synapse
except ImportError:
    print("Error: synapseclient not installed. Install with: pip install synapseclient")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
MATERIALIZED_VIEW_ID = "syn52702673"
SCHEMA_DIR = Path(__file__).parent.parent / "modules"
DIST_SCHEMA = Path(__file__).parent.parent / "dist" / "NF.yaml"

# Fields that should allow custom values (from issue #804)
CUSTOM_VALUE_FIELDS = ['platform']

# Minimum frequency threshold for suggesting new enum values
MIN_FREQUENCY = 2

# Minimum frequency for suggesting search filters
MIN_FILTER_FREQUENCY = 5


def load_schema_enums() -> Dict[str, Dict[str, Set[str]]]:
    """
    Load all enum permissible values from the schema.

    Returns:
        Dictionary mapping enum names to their permissible values and aliases
    """
    enums = {}

    # Load from all module YAML files
    for yaml_file in SCHEMA_DIR.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)

            if not data or 'enums' not in data:
                continue

            for enum_name, enum_data in data['enums'].items():
                if 'permissible_values' not in enum_data:
                    continue

                values = set()
                aliases = set()

                for value, value_data in enum_data['permissible_values'].items():
                    values.add(value)

                    # Also collect aliases
                    if value_data and isinstance(value_data, dict) and 'aliases' in value_data:
                        if isinstance(value_data['aliases'], list):
                            aliases.update(value_data['aliases'])
                        elif isinstance(value_data['aliases'], str):
                            aliases.add(value_data['aliases'])

                enums[enum_name] = {
                    'values': values,
                    'aliases': aliases,
                    'all': values | aliases
                }

        except Exception as e:
            logger.warning(f"Error loading {yaml_file}: {e}")

    logger.info(f"Loaded {len(enums)} enums from schema")
    return enums


def load_slot_to_enum_mapping() -> Dict[str, List[str]]:
    """
    Load mapping of slot names to their enum types.

    Returns:
        Dictionary mapping slot names to list of enum names
    """
    slot_enum_map = defaultdict(list)

    # Load props.yaml which defines slots
    props_file = SCHEMA_DIR / "props.yaml"
    if props_file.exists():
        with open(props_file, 'r') as f:
            data = yaml.safe_load(f)

        if data and 'slots' in data:
            for slot_name, slot_data in data['slots'].items():
                if not slot_data:
                    continue

                # Check for direct range
                if 'range' in slot_data and slot_data['range'].endswith('Enum'):
                    slot_enum_map[slot_name].append(slot_data['range'])

                # Check for any_of ranges
                if 'any_of' in slot_data and isinstance(slot_data['any_of'], list):
                    for constraint in slot_data['any_of']:
                        if 'range' in constraint and constraint['range'].endswith('Enum'):
                            slot_enum_map[slot_name].append(constraint['range'])

    logger.info(f"Mapped {len(slot_enum_map)} slots to enum types")
    return dict(slot_enum_map)


def query_synapse_annotations(syn: Synapse, limit: int = None) -> List[Dict]:
    """
    Query Synapse materialized view for file annotations.

    Args:
        syn: Synapse client
        limit: Optional limit on number of rows to retrieve

    Returns:
        List of annotation records
    """
    logger.info(f"Querying Synapse view {MATERIALIZED_VIEW_ID}...")

    query = f"SELECT * FROM {MATERIALIZED_VIEW_ID}"
    if limit:
        query += f" LIMIT {limit}"

    try:
        results = syn.tableQuery(query)
        df = results.asDataFrame()

        logger.info(f"Retrieved {len(df)} records with {len(df.columns)} columns")
        logger.info(f"Columns: {', '.join(df.columns.tolist()[:10])}...")

        # Convert to list of dicts
        records = df.to_dict('records')
        return records

    except Exception as e:
        logger.error(f"Error querying Synapse: {e}")
        raise


def analyze_annotations(
    records: List[Dict],
    enums: Dict[str, Dict[str, Set[str]]],
    slot_enum_map: Dict[str, List[str]]
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
    """
    Analyze annotations to find free-text values not in schema.

    Args:
        records: List of annotation records from Synapse
        enums: Schema enum definitions
        slot_enum_map: Mapping of slots to enum types

    Returns:
        Tuple of (suggestions_by_field, filter_suggestions)
        - suggestions_by_field: {field_name: {value: count}}
        - filter_suggestions: {field_name: count of unique values}
    """
    suggestions = defaultdict(lambda: defaultdict(int))
    filter_candidates = defaultdict(set)

    if not records:
        logger.warning("No records to analyze")
        return {}, {}

    # Get all column names from first record
    columns = list(records[0].keys())

    for record in records:
        for field, value in record.items():
            # Skip null/empty values
            if value is None or value == '':
                continue

            # Convert to string and clean
            value_str = str(value).strip()
            if not value_str:
                continue

            # Track for potential filters
            filter_candidates[field].add(value_str)

            # Check if this field maps to an enum
            if field in slot_enum_map:
                enum_names = slot_enum_map[field]

                # Check if value is in any of the mapped enums
                value_in_enum = False
                for enum_name in enum_names:
                    if enum_name in enums:
                        if value_str in enums[enum_name]['all']:
                            value_in_enum = True
                            break

                # If not in enum, add as suggestion
                if not value_in_enum:
                    suggestions[field][value_str] += 1

    # Filter suggestions by minimum frequency
    filtered_suggestions = {}
    for field, values in suggestions.items():
        filtered_values = {v: c for v, c in values.items() if c >= MIN_FREQUENCY}
        if filtered_values:
            filtered_suggestions[field] = filtered_values

    # Identify filter candidates (fields with diverse values)
    filter_suggestions = {}
    for field, values in filter_candidates.items():
        unique_count = len(values)
        if unique_count >= MIN_FILTER_FREQUENCY:
            filter_suggestions[field] = unique_count

    logger.info(f"Found {len(filtered_suggestions)} fields with suggested additions")
    logger.info(f"Found {len(filter_suggestions)} fields as potential filters")

    return filtered_suggestions, filter_suggestions


def find_enum_yaml_file(enum_name: str, schema_dir: Path) -> Path:
    """
    Find the YAML file containing a specific enum.

    Args:
        enum_name: Name of the enum to find
        schema_dir: Base schema directory

    Returns:
        Path to the YAML file containing the enum
    """
    for yaml_file in schema_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)

            if data and 'enums' in data and enum_name in data['enums']:
                return yaml_file
        except Exception as e:
            logger.debug(f"Error checking {yaml_file}: {e}")
            continue

    raise FileNotFoundError(f"Could not find YAML file for enum: {enum_name}")


def add_values_to_yaml(
    suggestions: Dict[str, Dict[str, int]],
    slot_enum_map: Dict[str, List[str]],
    schema_dir: Path,
    min_frequency: int = MIN_FREQUENCY
) -> Dict[str, int]:
    """
    Add suggested values to the appropriate YAML enum files.

    Args:
        suggestions: Field suggestions with counts
        slot_enum_map: Mapping of slots to enum types
        schema_dir: Base schema directory
        min_frequency: Minimum frequency to add value

    Returns:
        Dictionary with count of values added per file
    """
    files_modified = defaultdict(int)

    for field, values in suggestions.items():
        # Get enum types for this field
        if field not in slot_enum_map:
            logger.warning(f"Field '{field}' not found in slot-to-enum mapping, skipping")
            continue

        enum_types = slot_enum_map[field]
        if not enum_types:
            logger.warning(f"No enum types for field '{field}', skipping")
            continue

        # For fields with multiple enums, prefer non-"Other" enums
        # Otherwise use the first enum
        target_enum = None
        for enum_type in enum_types:
            if not enum_type.startswith('Other'):
                target_enum = enum_type
                break

        if not target_enum:
            target_enum = enum_types[0]

        logger.info(f"Adding values for field '{field}' to enum '{target_enum}'")

        try:
            # Find the YAML file
            yaml_file = find_enum_yaml_file(target_enum, schema_dir)
            logger.info(f"  Found enum in: {yaml_file.relative_to(schema_dir.parent)}")

            # Load YAML file
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)

            # Get existing enum
            if 'enums' not in data or target_enum not in data['enums']:
                logger.warning(f"  Enum '{target_enum}' not found in {yaml_file}, skipping")
                continue

            enum_data = data['enums'][target_enum]

            # Ensure permissible_values exists
            if 'permissible_values' not in enum_data:
                enum_data['permissible_values'] = {}

            # Add new values
            values_added = 0
            for value, count in values.items():
                if count < min_frequency:
                    continue

                # Skip if already exists
                if value in enum_data['permissible_values']:
                    logger.debug(f"  Value '{value}' already exists, skipping")
                    continue

                # Add the value with basic metadata
                enum_data['permissible_values'][value] = {
                    'description': f"Added from annotation review (used {count} times)"
                }
                values_added += 1
                logger.info(f"  Added: '{value}' (frequency: {count})")

            if values_added > 0:
                # Write back to file
                with open(yaml_file, 'w') as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

                files_modified[str(yaml_file.relative_to(schema_dir.parent))] += values_added
                logger.info(f"  ✅ Added {values_added} values to {yaml_file.name}")
            else:
                logger.info(f"  No new values to add (all already exist or below threshold)")

        except FileNotFoundError as e:
            logger.warning(f"  {e}")
            continue
        except Exception as e:
            logger.error(f"  Error processing field '{field}': {e}")
            continue

    return dict(files_modified)


def format_suggestions_as_markdown(
    suggestions: Dict[str, Dict[str, int]],
    filters: Dict[str, int],
    files_modified: Dict[str, int] = None
) -> str:
    """
    Format suggestions as markdown for PR description.

    Args:
        suggestions: Field suggestions with counts
        filters: Filter candidates with unique value counts
        files_modified: Dictionary of files modified with count of values added

    Returns:
        Markdown formatted string
    """
    md = ["# Annotation Review - Schema Updates from Synapse Annotations\n"]
    md.append("This PR contains automatic updates to the metadata dictionary based on ")
    md.append(f"analysis of file annotations in Synapse view {MATERIALIZED_VIEW_ID}.\n")

    if files_modified:
        md.append("\n## Files Modified\n")
        md.append(f"**{len(files_modified)} enum file(s) updated** with values from annotations:\n\n")
        for file_path, count in sorted(files_modified.items()):
            md.append(f"- `{file_path}` - Added {count} value(s)\n")
        md.append("\n")

    if suggestions:
        md.append("## Suggested Enum Value Additions\n")
        md.append("The following values appear in annotations but are not currently ")
        md.append("in the schema enum definitions. Values shown with frequency counts.\n")

        for field in sorted(suggestions.keys()):
            values = suggestions[field]
            md.append(f"\n### Field: `{field}`\n")

            # Sort by frequency (descending)
            sorted_values = sorted(values.items(), key=lambda x: x[1], reverse=True)

            for value, count in sorted_values[:20]:  # Limit to top 20
                md.append(f"- `{value}` (used {count} times)\n")

            if len(sorted_values) > 20:
                md.append(f"\n*...and {len(sorted_values) - 20} more*\n")
    else:
        md.append("## No New Enum Values Suggested\n")
        md.append("All annotation values match existing schema definitions.\n")

    if filters:
        md.append("\n## Suggested Portal Search Filters\n")
        md.append("The following fields have diverse values and could be useful as ")
        md.append("portal search filters:\n")

        # Sort by unique value count (descending)
        sorted_filters = sorted(filters.items(), key=lambda x: x[1], reverse=True)

        for field, count in sorted_filters:
            md.append(f"- `{field}` ({count} unique values)\n")

    md.append("\n---\n")
    md.append("*Generated by automated annotation review workflow*\n")

    return ''.join(md)


def save_suggestions_to_file(
    suggestions: Dict[str, Dict[str, int]],
    filters: Dict[str, int],
    output_file: Path
) -> None:
    """
    Save suggestions to JSON file for potential automated processing.

    Args:
        suggestions: Field suggestions with counts
        filters: Filter candidates
        output_file: Path to output file
    """
    data = {
        'suggestions': suggestions,
        'filters': filters,
        'materialized_view': MATERIALIZED_VIEW_ID
    }

    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved suggestions to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Review Synapse annotations and suggest schema additions'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('annotation_suggestions.json'),
        help='Output file for suggestions (JSON format)'
    )
    parser.add_argument(
        '--markdown',
        type=Path,
        default=Path('annotation_suggestions.md'),
        help='Output file for markdown summary'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print suggestions without modifying files'
    )
    parser.add_argument(
        '--no-edit',
        action='store_true',
        help='Do not edit YAML files, only generate suggestions'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of records to query (for testing)'
    )

    args = parser.parse_args()

    # Check for Synapse authentication
    auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')
    if not auth_token:
        logger.error("SYNAPSE_AUTH_TOKEN environment variable not set")
        sys.exit(1)

    try:
        # Initialize Synapse client
        syn = Synapse()
        syn.login(authToken=auth_token)
        logger.info("Logged into Synapse")

        # Load schema
        logger.info("Loading schema enums...")
        enums = load_schema_enums()
        slot_enum_map = load_slot_to_enum_mapping()

        # Query annotations
        records = query_synapse_annotations(syn, limit=args.limit)

        # Analyze annotations
        logger.info("Analyzing annotations...")
        suggestions, filters = analyze_annotations(records, enums, slot_enum_map)

        # Add values to YAML files (unless --no-edit or --dry-run)
        files_modified = {}
        if not args.dry_run and not args.no_edit and suggestions:
            logger.info("Adding suggested values to YAML files...")
            files_modified = add_values_to_yaml(
                suggestions,
                slot_enum_map,
                SCHEMA_DIR,
                MIN_FREQUENCY
            )
            logger.info(f"Modified {len(files_modified)} file(s)")
        elif args.no_edit:
            logger.info("Skipping YAML edits (--no-edit flag)")
        elif args.dry_run:
            logger.info("Skipping YAML edits (--dry-run mode)")

        # Format as markdown
        markdown = format_suggestions_as_markdown(suggestions, filters, files_modified)

        if args.dry_run:
            logger.info("Dry run - printing results:")
            print("\n" + "="*80)
            print(markdown)
            print("="*80)
        else:
            # Save files
            save_suggestions_to_file(suggestions, filters, args.output)

            with open(args.markdown, 'w') as f:
                f.write(markdown)
            logger.info(f"Saved markdown to {args.markdown}")

        # Summary
        total_suggestions = sum(len(v) for v in suggestions.values())
        total_added = sum(files_modified.values()) if files_modified else 0
        logger.info(f"\nSummary:")
        logger.info(f"  - {len(suggestions)} fields with suggested additions")
        logger.info(f"  - {total_suggestions} total value suggestions")
        logger.info(f"  - {total_added} values added to YAML files")
        logger.info(f"  - {len(files_modified)} files modified")
        logger.info(f"  - {len(filters)} potential search filters")

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
