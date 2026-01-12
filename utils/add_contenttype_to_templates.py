#!/usr/bin/env python3
"""
Add contentType='dataset' conditional to all template schemas for DCA compatibility.

This fixes issue #788 by ensuring folders with bound assay templates remain visible
in the Data Curator App, which requires folders to have contentType='dataset'.
"""

import json
from pathlib import Path

# The conditional to add (same as in Superdataset.json)
CONTENTTYPE_CONDITIONAL = {
    "if": {
        "properties": {
            "concreteType": {
                "const": "org.sagebionetworks.repo.model.Folder"
            }
        },
        "not": {
            "properties": {
                "name": {
                    "const": "Raw Data"
                }
            }
        }
    },
    "then": {
        "properties": {
            "contentType": {
                "const": "dataset"
            }
        }
    }
}


def add_contenttype_to_schema(schema_path: Path) -> bool:
    """
    Add contentType conditional to a schema if it doesn't already have it.

    Args:
        schema_path: Path to the JSON schema file

    Returns:
        True if the schema was modified, False if it already had the conditional
    """
    with open(schema_path, 'r') as f:
        schema = json.load(f)

    # Check if schema already has contentType in allOf or at root level
    if 'allOf' in schema:
        for item in schema['allOf']:
            if 'then' in item and 'properties' in item['then']:
                if 'contentType' in item['then']['properties']:
                    print(f"  ✓ {schema_path.name} already has contentType")
                    return False

    if 'if' in schema and 'then' in schema:
        if 'properties' in schema['then'] and 'contentType' in schema['then']['properties']:
            print(f"  ✓ {schema_path.name} already has contentType at root level")
            return False

    # Add the conditional
    if 'allOf' in schema:
        # Add to existing allOf array
        schema['allOf'].append(CONTENTTYPE_CONDITIONAL)
        print(f"  ✓ Added contentType to {schema_path.name} (in allOf)")
    else:
        # Create allOf array if it doesn't exist
        schema['allOf'] = [CONTENTTYPE_CONDITIONAL]
        print(f"  ✓ Added contentType to {schema_path.name} (created allOf)")

    # Write back with pretty formatting
    with open(schema_path, 'w') as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        f.write('\n')  # Add trailing newline

    return True


def main():
    repo_root = Path(__file__).parent.parent
    schema_dir = repo_root / 'registered-json-schemas'

    # Process all Template.json files
    template_files = sorted(schema_dir.glob('*Template.json'))

    print(f"Processing {len(template_files)} template schemas...")
    print()

    modified_count = 0
    skipped_count = 0

    for schema_file in template_files:
        if add_contenttype_to_schema(schema_file):
            modified_count += 1
        else:
            skipped_count += 1

    print()
    print(f"Summary:")
    print(f"  Modified: {modified_count}")
    print(f"  Skipped:  {skipped_count}")
    print(f"  Total:    {len(template_files)}")


if __name__ == "__main__":
    main()
