#!/usr/bin/env python3
"""
Create a record-based metadata curation task in Synapse.

This script automatically:
- Creates a RecordSet with schema binding (optional)
- Creates a CurationTask for record-based metadata
- Creates a DataGrid interface for the RecordSet

Requirements:
  pip install git+https://github.com/Sage-Bionetworks/synapsePythonClient.git@develop
"""

import argparse
import json
import os
import sys
from pathlib import Path


def load_schema_uri(template_name_or_uri: str, schema_dir: str = "registered-json-schemas") -> str:
    """
    Load the schema URI from a registered JSON schema file or return external URI.

    Args:
        template_name_or_uri: Template name (e.g., 'ImagingAssayTemplate') or full schema URI
        schema_dir: Directory containing schema files (only used for local templates)

    Returns:
        Schema URI string in short format (e.g., 'org.synapse.nf-datalandscape-0.2.0')

    Raises:
        FileNotFoundError: If schema file doesn't exist
        KeyError: If $id field is missing from schema
    """
    # Check if it's a full URI
    if template_name_or_uri.startswith('http://') or template_name_or_uri.startswith('https://'):
        # Extract short-form ID from full URL
        # Example: https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-datalandscape-0.2.0
        # -> org.synapse.nf-datalandscape-0.2.0
        return template_name_or_uri.split('/')[-1]

    # Local template name - load from file
    repo_root = Path(__file__).parent.parent
    schema_file = repo_root / schema_dir / f"{template_name_or_uri}.json"

    if not schema_file.exists():
        raise FileNotFoundError(
            f"Schema file not found: {schema_file}\n"
            f"Available templates in {schema_dir}/:\n" +
            "\n".join(f"  - {f.stem}" for f in sorted((repo_root / schema_dir).glob("*.json")))
        )

    with open(schema_file, 'r') as f:
        schema = json.load(f)

    if "$id" not in schema:
        raise KeyError(f"Schema file {schema_file} is missing required '$id' field")

    # Extract short-form ID from $id field (which may be a full URL)
    schema_id = schema["$id"]
    if schema_id.startswith('http://') or schema_id.startswith('https://'):
        return schema_id.split('/')[-1]

    return schema_id


def create_recordset_task(
    folder_id: str,
    record_set_name: str,
    template: str,
    record_set_description: str = None,
    curation_task_name: str = None,
    upsert_keys: list = None,
    instructions: str = "Please add metadata records",
    bind_schema: bool = True,
    auth_token: str = None
) -> dict:
    """
    Create a record-based metadata curation task.

    Automatically creates RecordSet, CurationTask, and DataGrid.
    Project ID is derived from the folder.

    Args:
        folder_id: Synapse folder ID associated with the RecordSet
        record_set_name: Name/identifier for the RecordSet
        template: Template name (e.g., 'ImagingAssayTemplate') or full schema URI
        record_set_description: Description of the RecordSet's purpose (optional)
        curation_task_name: Name for the curation task (auto-generated if None)
        upsert_keys: List of field names that uniquely identify records (default: ['id'])
        instructions: Instructions for data contributors
        bind_schema: Whether to bind JSON schema to RecordSet (default: True)
        auth_token: Synapse authentication token (if None, reads from env)

    Returns:
        Dictionary with recordset_id, task_id, data_grid_id, schema_uri, and project_id
    """
    from synapseclient import Synapse

    # Get auth token
    if auth_token is None:
        auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')
        if not auth_token:
            raise ValueError(
                "No authentication token provided. "
                "Set SYNAPSE_AUTH_TOKEN environment variable or pass auth_token parameter"
            )

    # Initialize Synapse client
    syn = Synapse()
    syn.login(authToken=auth_token)

    # Get folder to derive project ID
    print(f"Getting folder information: {folder_id}")
    folder = syn.get(folder_id, downloadFile=False)

    # Try to get project ID - may need to traverse hierarchy
    project_id = None
    if hasattr(folder, 'properties') and folder.properties:
        project_id = folder.properties.get('projectId')

    # If not in properties, traverse parent hierarchy to find project
    if not project_id:
        print("  Project ID not in folder properties, traversing hierarchy...")
        current = folder
        while current.get('concreteType') != 'org.sagebionetworks.repo.model.Project':
            parent_id = current.get('parentId')
            if not parent_id:
                raise ValueError(f"Could not find project for folder {folder_id}")
            current = syn.get(parent_id, downloadFile=False)
        project_id = current.id

    print(f"  Project: {project_id}")

    # Load schema URI
    print(f"\nLoading schema: {template}")
    schema_uri = load_schema_uri(template)
    print(f"  Schema URI: {schema_uri}")

    # Set defaults
    if record_set_description is None:
        record_set_description = f"RecordSet for {record_set_name}"

    if curation_task_name is None:
        curation_task_name = record_set_name

    print(f"\nCreating record-based metadata task...")
    print(f"  Project: {project_id}")
    print(f"  Folder: {folder_id}")
    print(f"  RecordSet Name: {record_set_name}")
    print(f"  Task Name: {curation_task_name}")
    print(f"  Upsert Keys: {upsert_keys if upsert_keys else 'Not specified'}")
    print(f"  Bind Schema: {bind_schema}")

    # Import the helper function from synapseclient
    try:
        from synapseclient.extensions.curator import create_record_based_metadata_task
    except ImportError:
        raise ImportError(
            "The create_record_based_metadata_task function is not available. "
            "Please ensure you have the latest develop branch of synapsePythonClient:\n"
            "  pip install git+https://github.com/Sage-Bionetworks/synapsePythonClient.git@develop"
        )

    # Create the record-based metadata task
    # Build kwargs to conditionally include upsert_keys
    task_kwargs = {
        'synapse_client': syn,
        'project_id': project_id,
        'folder_id': folder_id,
        'record_set_name': record_set_name,
        'record_set_description': record_set_description,
        'curation_task_name': curation_task_name,
        'instructions': instructions,
        'schema_uri': schema_uri,
        'bind_schema_to_record_set': bind_schema
    }

    # Only include upsert_keys if provided
    if upsert_keys is not None:
        task_kwargs['upsert_keys'] = upsert_keys

    record_set, curation_task, data_grid = create_record_based_metadata_task(**task_kwargs)

    print(f"\n✓ Record-based curation task created successfully!")
    print(f"  RecordSet ID: {record_set.id}")
    print(f"  Task ID: {curation_task.task_id}")
    print(f"  DataGrid Session ID: {data_grid.session_id}")

    return {
        "recordset_id": record_set.id,
        "task_id": curation_task.task_id,
        "data_grid_session_id": data_grid.session_id,
        "schema_uri": schema_uri,
        "project_id": project_id,
        "folder_id": folder_id,
        "record_set_name": record_set_name
    }


def main():
    parser = argparse.ArgumentParser(
        description="Create a record-based metadata curation task in Synapse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create recordset task with schema binding (default)
  python create_recordset_task.py \\
    --folder-id syn87654321 \\
    --recordset-name "YIA_Smith_2025" \\
    --template DataLandscape

  # Create task with custom parameters and upsert keys
  python create_recordset_task.py \\
    --folder-id syn87654321 \\
    --recordset-name "DDI_Doe_2026" \\
    --template DataLandscape \\
    --description "Data sharing plan" \\
    --task-name "DataLandscape_Curation" \\
    --upsert-keys study name \\
    --instructions "Please fill out Data Landscape records"

  # Skip schema binding
  python create_recordset_task.py \\
    --folder-id syn87654321 \\
    --recordset-name "Allaway_2025" \\
    --template DataLandscape \\
    --no-bind-schema

  # Use external schema URI
  python create_recordset_task.py \\
    --folder-id syn87654321 \\
    --recordset-name "Publication" \\
    --template $URI

Environment Variables:
  SYNAPSE_AUTH_TOKEN    Synapse authentication token (required)

Notes:
  - Project ID is automatically derived from the folder
  - RecordSet is a structured data container for (meta)data records
  - Upsert keys define which fields uniquely identify each record
  - Schema binding validates records against the JSON schema
  - DataGrid provides a UI for editing records
        """
    )

    parser.add_argument(
        '--folder-id',
        required=True,
        help='Synapse folder ID associated with the RecordSet (e.g., syn87654321)'
    )

    parser.add_argument(
        '--recordset-name',
        required=True,
        help='Name/identifier for the RecordSet (e.g., "MyDataRecords")'
    )

    parser.add_argument(
        '--template',
        required=True,
        help='Template name (e.g., ImagingAssayTemplate) or full schema URI'
    )

    parser.add_argument(
        '--description',
        default=None,
        help='Description of the RecordSet purpose (auto-generated if not provided)'
    )

    parser.add_argument(
        '--task-name',
        default=None,
        help='Name for the curation task (auto-generated if not provided)'
    )

    parser.add_argument(
        '--upsert-keys',
        nargs='+',
        default=None,
        help='Field names that uniquely identify records'
    )

    parser.add_argument(
        '--instructions',
        default='Please update records',
        help='Instructions for data contributors'
    )

    parser.add_argument(
        '--bind-schema',
        action='store_true',
        default=True,
        help='Bind JSON schema to RecordSet (default: True)'
    )

    parser.add_argument(
        '--no-bind-schema',
        action='store_false',
        dest='bind_schema',
        help='Skip binding JSON schema to RecordSet'
    )

    parser.add_argument(
        '--output-format',
        choices=['json', 'github'],
        default='json',
        help='Output format: json for testing, github for GitHub Actions (default: json)'
    )

    args = parser.parse_args()

    try:
        result = create_recordset_task(
            folder_id=args.folder_id,
            record_set_name=args.recordset_name,
            template=args.template,
            record_set_description=args.description,
            curation_task_name=args.task_name,
            upsert_keys=args.upsert_keys,
            instructions=args.instructions,
            bind_schema=args.bind_schema
        )

        if args.output_format == 'github':
            # Output for GitHub Actions
            github_output = os.environ.get('GITHUB_OUTPUT')
            if github_output:
                with open(github_output, 'a') as f:
                    f.write(f"recordset_id={result['recordset_id']}\n")
                    f.write(f"task_id={result['task_id']}\n")
                    f.write(f"data_grid_session_id={result['data_grid_session_id']}\n")
                    f.write(f"schema_uri={result['schema_uri']}\n")
                    f.write(f"project_id={result['project_id']}\n")
                    f.write(f"folder_id={result['folder_id']}\n")
                    f.write(f"record_set_name={result['record_set_name']}\n")
            else:
                print("\nGitHub Actions outputs:")
                for key, value in result.items():
                    print(f"{key}={value}")
        else:
            # JSON output for testing
            print("\nResult:")
            print(json.dumps(result, indent=2))

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
