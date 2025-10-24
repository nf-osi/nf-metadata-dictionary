#!/usr/bin/env python3
"""
Create a file-based metadata curation task in Synapse.

This script automatically:
- Binds JSON schema to the upload folder (optional, default: True)
- Creates EntityView (file view) for the upload folder
- Creates CurationTask with specified datatype and instructions

The dataType is auto-generated from the template name and folder ID.
The project ID is derived from the folder.

Requirements:
  pip install git+https://github.com/Sage-Bionetworks/synapsePythonClient.git@develop
"""

import argparse
import json
import os
import sys
from pathlib import Path


def load_schema_uri(template_name_or_uri: str, schema_dir: str = "registered-json-schemas") -> tuple[str, dict]:
    """
    Load the schema URI and schema content from a registered JSON schema file or external URI.

    Args:
        template_name_or_uri: Template name (e.g., 'ImagingAssayTemplate') or full schema URI
        schema_dir: Directory containing schema files (only used for local templates)

    Returns:
        Tuple of (schema_uri, schema_dict)

    Raises:
        FileNotFoundError: If schema file doesn't exist
        KeyError: If $id field is missing from schema
    """
    # Check if it's a full URI
    if template_name_or_uri.startswith('http://') or template_name_or_uri.startswith('https://'):
        # External URI provided - use it directly and fetch schema if needed
        return template_name_or_uri, None  # Schema content not available for external URIs

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

    return schema["$id"], schema


def generate_datatype(template_name: str, folder_id: str) -> str:
    """
    Generate a unique dataType identifier.

    Args:
        template_name: Name of the template (e.g., 'ImagingAssayTemplate')
        folder_id: Synapse folder ID (e.g., 'syn12345678')

    Returns:
        Generated dataType string (e.g., 'ImagingAssay-syn12345678')
    """
    # Remove "Template" suffix if present
    base_name = template_name.removesuffix("Template")
    return f"{base_name}-{folder_id}"


def bind_schema_to_folder(
    folder_id: str,
    schema_uri: str,
    syn
) -> bool:
    """
    Bind a JSON schema to a Synapse folder.

    Args:
        folder_id: Synapse folder ID
        schema_uri: JSON schema URI
        syn: Authenticated Synapse client

    Returns:
        True if binding succeeded, False if already bound
    """
    from synapseclient.services.json_schema import JsonSchemaService

    print(f"\nBinding schema to folder {folder_id}...")
    json_schema_service = JsonSchemaService(syn)

    try:
        # Note: parameter names are synapse_id and json_schema_uri
        binding = json_schema_service.bind_json_schema_to_entity(
            synapse_id=folder_id,
            json_schema_uri=schema_uri
        )
        print("✓ Schema bound successfully")
        return True
    except Exception as e:
        if "already" in str(e).lower() or "bound" in str(e).lower():
            print(f"⚠ Schema already bound to folder (skipping)")
            return False
        else:
            print(f"⚠ Warning: Could not bind schema: {e}")
            return False


def create_curation_task(
    upload_folder_id: str,
    template: str,
    instructions: str = "Please add metadata for your files",
    bind_schema: bool = True,
    auth_token: str = None
) -> dict:
    """
    Create a file-based metadata curation task.

    Automatically creates EntityView and CurationTask.
    Project ID is derived from the folder.
    Optionally binds JSON schema to the folder.

    Args:
        upload_folder_id: Synapse folder ID for uploads
        template: Template name (e.g., 'ImagingAssayTemplate')
        instructions: Instructions for data contributors
        bind_schema: Whether to bind JSON schema to folder (default: True)
        auth_token: Synapse authentication token (if None, reads from env)

    Returns:
        Dictionary with task_id, fileview_id, data_type, schema_uri, and project_id
    """
    from synapseclient import Synapse
    from synapseclient.models.curation import (
        CurationTask,
        FileBasedMetadataTaskProperties
    )

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
    print(f"Getting folder information: {upload_folder_id}")
    folder = syn.get(upload_folder_id, downloadFile=False)

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
                raise ValueError(f"Could not find project for folder {upload_folder_id}")
            current = syn.get(parent_id, downloadFile=False)
        project_id = current.id

    print(f"  Project: {project_id}")

    # Load schema URI and content
    print(f"\nLoading schema: {template}")
    schema_uri, json_schema = load_schema_uri(template)
    print(f"  Schema URI: {schema_uri}")

    # Determine template name for dataType generation
    # If full URI provided, extract template name or use a default
    if template.startswith('http://') or template.startswith('https://'):
        # Extract template name from URI if possible
        # e.g., sage.schemas.v2571-nf.ChIPSeqTemplate.schema-9.14.0 -> ChIPSeqTemplate
        uri_parts = schema_uri.split('/')[-1].split('.')
        template_name = next((part for part in uri_parts if 'Template' in part), template.replace('https://', '').replace('http://', '').split('/')[0])
    else:
        template_name = template

    # Generate dataType
    data_type = generate_datatype(template_name, upload_folder_id)
    print(f"  Generated dataType: {data_type}")

    # Optionally bind schema to folder
    if bind_schema:
        bind_schema_to_folder(upload_folder_id, schema_uri, syn)

    # Create EntityView (file view) using the better implementation from json_schema_entity_view
    print(f"\nCreating file view for folder...")
    from synapseclient.models import Column, ColumnType, ViewTypeMask, EntityView

    # Fetch the schema if we don't have it yet
    if json_schema is None:
        print("  Fetching schema from URI...")
        import requests
        response = requests.get(schema_uri)
        if response.status_code == 200:
            json_schema = response.json()
        else:
            print(f"  ⚠ Could not fetch schema, using local template if available...")
            try:
                _, json_schema = load_schema_uri(template_name)
            except FileNotFoundError:
                print("  ⚠ No schema available - creating view with default columns only")
                json_schema = {}

    # Create columns from schema using the helper function
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from json_schema_entity_view import _create_columns_from_json_schema

    try:
        columns = _create_columns_from_json_schema(json_schema)
        print(f"  Adding {len(columns)} columns from schema")
    except ValueError as e:
        print(f"  ⚠ Schema has no properties: {e}")
        columns = []

    # Add essential columns first: id and name only
    essential_columns = [
        Column(name="id", column_type=ColumnType.ENTITYID),
        Column(name="name", column_type=ColumnType.STRING, maximum_size=256),
    ]

    # Combine essential columns with schema columns
    all_columns = essential_columns + columns

    # Create the entity view using the new models API
    file_view = EntityView(
        name=f"{data_type}_FileView",
        parent_id=project_id,
        scope_ids=[upload_folder_id],
        view_type_mask=ViewTypeMask.FILE,
        columns=all_columns,
    ).store(synapse_client=syn)

    print(f"  File View ID: {file_view.id}")

    # Create file-based metadata task
    print(f"\nCreating file-based metadata task...")
    print(f"  Folder: {upload_folder_id}")
    print(f"  Data type: {data_type}")

    task = CurationTask(
        project_id=project_id,
        data_type=data_type,
        instructions=instructions,
        task_properties=FileBasedMetadataTaskProperties(
            upload_folder_id=upload_folder_id,
            file_view_id=file_view.id
        )
    )

    # Store the task (use store() method, not create())
    task = task.store()

    print(f"\n✓ Curation task created successfully!")
    print(f"  Task ID: {task.task_id}")

    return {
        "task_id": task.task_id,
        "fileview_id": file_view.id,
        "data_type": data_type,
        "schema_uri": schema_uri,
        "project_id": project_id
    }


def main():
    parser = argparse.ArgumentParser(
        description="Create a file-based metadata curation task in Synapse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create task with schema binding (default)
  python create_curation_task.py \\
    --folder-id syn12345678 \\
    --template ImagingAssayTemplate

  # Create task with custom instructions
  python create_curation_task.py \\
    --folder-id syn12345678 \\
    --template RNASeqTemplate \\
    --instructions "Please upload RNA-seq data with complete metadata"

  # Skip schema binding
  python create_curation_task.py \\
    --folder-id syn12345678 \\
    --template BiospecimenTemplate \\
    --no-bind-schema

  # Use external schema URI
  python create_curation_task.py \\
    --folder-id syn12345678 \\
    --template https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/sage.schemas.v2571-nf.ChIPSeqTemplate.schema-9.14.0

Environment Variables:
  SYNAPSE_AUTH_TOKEN    Synapse authentication token (required)

Notes:
  - Project ID is automatically derived from the folder
  - DataType is auto-generated as: {template_base}-{folder_id}
  - Schema binding is enabled by default (use --no-bind-schema to skip)
  - Schema URI is loaded from registered-json-schemas/ directory
        """
    )

    parser.add_argument(
        '--folder-id',
        required=True,
        help='Upload folder Synapse ID (e.g., syn12345678)'
    )

    parser.add_argument(
        '--template',
        required=True,
        help='Template name (e.g., ImagingAssayTemplate) or full schema URI (e.g., https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/sage.schemas.v2571-nf.ChIPSeqTemplate.schema-9.14.0)'
    )

    parser.add_argument(
        '--instructions',
        default='Please add metadata for your files',
        help='Instructions for data contributors (default: "Please add metadata for your files")'
    )

    parser.add_argument(
        '--bind-schema',
        action='store_true',
        default=True,
        help='Bind JSON schema to folder (default: True)'
    )

    parser.add_argument(
        '--no-bind-schema',
        action='store_false',
        dest='bind_schema',
        help='Skip binding JSON schema to folder'
    )

    parser.add_argument(
        '--output-format',
        choices=['json', 'github'],
        default='json',
        help='Output format: json for testing, github for GitHub Actions (default: json)'
    )

    args = parser.parse_args()

    try:
        result = create_curation_task(
            upload_folder_id=args.folder_id,
            template=args.template,
            instructions=args.instructions,
            bind_schema=args.bind_schema
        )

        if args.output_format == 'github':
            # Output for GitHub Actions
            github_output = os.environ.get('GITHUB_OUTPUT')
            if github_output:
                with open(github_output, 'a') as f:
                    f.write(f"task_id={result['task_id']}\n")
                    f.write(f"fileview_id={result['fileview_id']}\n")
                    f.write(f"data_type={result['data_type']}\n")
                    f.write(f"schema_uri={result['schema_uri']}\n")
            else:
                print("\nGitHub Actions outputs:")
                print(f"task_id={result['task_id']}")
                print(f"fileview_id={result['fileview_id']}")
                print(f"data_type={result['data_type']}")
                print(f"schema_uri={result['schema_uri']}")
        else:
            # JSON output for testing
            print("\nResult:")
            print(json.dumps(result, indent=2))

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
