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


def unbind_schema_from_folder(folder_id: str, syn) -> bool:
    """
    Unbind any existing JSON schema from a Synapse folder.

    Args:
        folder_id: Synapse folder ID
        syn: Authenticated Synapse client

    Returns:
        True if a schema was removed, False if none was bound
    """
    from synapseclient.services.json_schema import JsonSchemaService

    json_schema_service = JsonSchemaService(syn)
    try:
        json_schema_service.delete_json_schema_from_entity(synapse_id=folder_id)
        print("✓ Existing schema unbound from folder")
        return True
    except Exception as e:
        if "not found" in str(e).lower() or "no schema" in str(e).lower() or "404" in str(e):
            print("  No existing schema binding found (skipping unbind)")
            return False
        else:
            print(f"⚠ Warning: Could not unbind schema: {e}")
            return False


def check_existing_annotations(folder_id: str, schema_fields: set, syn) -> bool:
    """
    Warn if files in the folder already have annotations matching template fields.

    Checks up to 10 files to keep runtime reasonable. Ignores system fields
    (createdBy, modifiedOn, etc.) — only considers fields present in the schema.

    Args:
        folder_id: Synapse folder ID
        schema_fields: Field names from the schema template's 'properties'
        syn: Authenticated Synapse client

    Returns:
        True if pre-filled annotations were found, False otherwise
    """
    print(f"\nChecking for pre-existing annotations in folder {folder_id}...")
    files_with_annotations = []
    checked = 0

    for child in syn.getChildren(folder_id, includeTypes=["file"]):
        checked += 1
        annotations = syn.get_annotations(child["id"])
        filled = {k: v for k, v in annotations.items() if k in schema_fields and v not in (None, [], "")}
        if filled:
            files_with_annotations.append((child["name"], filled))
        if checked >= 10:
            break

    if not checked:
        print("  No files found in folder")
        return False

    if files_with_annotations:
        print(f"⚠ Warning: {len(files_with_annotations)} of {checked} checked file(s) already have template annotations:")
        for filename, fields in files_with_annotations[:3]:
            print(f"  - {filename}: {list(fields.keys())}")
        if len(files_with_annotations) > 3:
            print(f"  ... and {len(files_with_annotations) - 3} more")
        print("  Existing annotations will not be overwritten, but verify they are compatible with the new template.")
        return True

    print(f"  No pre-existing template annotations found ({checked} file(s) checked)")
    return False


def delete_existing_curation_task(folder_id: str, project_id: str, syn) -> bool:
    """
    Find and delete any existing curation task whose upload folder matches folder_id.

    Args:
        folder_id: Synapse folder ID to match against task_properties.upload_folder_id
        project_id: Synapse project ID to search within
        syn: Authenticated Synapse client (used for context; list() uses cached client)

    Returns:
        True if a task was deleted, False if none was found
    """
    from synapseclient.models.curation import CurationTask

    print(f"\nSearching for existing curation tasks for folder {folder_id}...")
    deleted = False
    for task in CurationTask.list(project_id=project_id):
        props = task.task_properties
        if props and getattr(props, "upload_folder_id", None) == folder_id:
            print(f"  Found task {task.task_id} (dataType: {task.data_type}) — deleting...")
            task.delete()
            print(f"  ✓ Deleted task {task.task_id}")
            deleted = True
    if not deleted:
        print("  No existing curation task found for this folder")
    return deleted


def bind_schema_to_folder(
    folder_id: str,
    schema_uri: str,
    syn,
    replace: bool = False
) -> bool:
    """
    Bind a JSON schema to a Synapse folder.

    Args:
        folder_id: Synapse folder ID
        schema_uri: JSON schema URI
        syn: Authenticated Synapse client
        replace: If True, unbind any existing schema before binding

    Returns:
        True if binding succeeded, False if already bound and replace=False
    """
    from synapseclient.services.json_schema import JsonSchemaService

    print(f"\nBinding schema to folder {folder_id}...")
    json_schema_service = JsonSchemaService(syn)

    if replace:
        unbind_schema_from_folder(folder_id, syn)

    try:
        json_schema_service.bind_json_schema_to_entity(
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
    replace: bool = False,
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
        replace: If True, delete any existing curation task for this folder and
                 rebind the schema before creating a new task (default: False)
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

    # Fetch schema content now if not already loaded (external URI case),
    # so schema fields are available for the annotation check below.
    if json_schema is None:
        print("  Fetching schema from URI...")
        import requests
        response = requests.get(schema_uri)
        if response.status_code == 200:
            json_schema = response.json()
        else:
            print(f"  ⚠ Could not fetch schema from URI (status {response.status_code})")
            json_schema = {}

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

    # Warn early if files already have annotations matching the template fields,
    # before any destructive action (schema unbind / task delete).
    schema_fields = set(json_schema.get("properties", {}).keys())
    if schema_fields:
        check_existing_annotations(upload_folder_id, schema_fields, syn)

    # If replacing, delete existing curation task first
    if replace:
        delete_existing_curation_task(upload_folder_id, project_id, syn)

    # Optionally bind schema to folder
    if bind_schema:
        bind_schema_to_folder(upload_folder_id, schema_uri, syn, replace=replace)

    # Create EntityView (file view) using the better implementation from json_schema_entity_view
    print(f"\nCreating file view for folder...")
    from synapseclient.models import Column, ColumnType, ViewTypeMask, EntityView

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
        '--replace',
        action='store_true',
        default=False,
        help=(
            'Replace mode: delete any existing curation task for this folder '
            'and rebind the schema before creating a new task. '
            'Use when changing the template for an already-configured folder.'
        )
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
            bind_schema=args.bind_schema,
            replace=args.replace
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
