#!/usr/bin/env python3
"""
Create a file-based metadata curation task in Synapse.

This script automatically:
- Binds JSON schema to the upload folder (optional, default: True)
- Creates EntityView (file view) for the upload folder
- Creates CurationTask with specified datatype and instructions

The task display name is enforced as "{folder name} ({folder ID})" per our
team's task naming convention.
The project ID is derived from the folder.

Requirements:
  synapseclient>=4.12.0 (needs synapseclient.extensions.curator.utils.project_id_from_entity_id,
  not available in earlier releases)
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
        Tuple of (schema_uri, schema_dict), schema_uri normalized to short form

    Raises:
        FileNotFoundError: If schema file doesn't exist
        KeyError: If $id field is missing from schema
    """
    # Check if it's a full URI
    if template_name_or_uri.startswith('http://') or template_name_or_uri.startswith('https://'):
        # External URI provided - normalize to short form; schema content is fetched
        # separately by the caller using the original full URI
        return template_name_or_uri.split('/')[-1], None

    # Local template name - load from file (case-insensitive: 'microscopyassaytemplate'
    # matches 'MicroscopyAssayTemplate.json' just like the properly-cased name would)
    repo_root = Path(__file__).parent.parent
    schema_file = repo_root / schema_dir / f"{template_name_or_uri}.json"

    if not schema_file.exists():
        match = next(
            (f for f in (repo_root / schema_dir).glob("*.json")
             if f.stem.lower() == template_name_or_uri.lower()),
            None
        )
        if match is None:
            raise FileNotFoundError(
                f"Schema file not found: {schema_file}\n"
                f"Available templates in {schema_dir}/:\n" +
                "\n".join(f"  - {f.stem}" for f in sorted((repo_root / schema_dir).glob("*.json")))
            )
        schema_file = match

    with open(schema_file, 'r') as f:
        schema = json.load(f)

    if "$id" not in schema:
        raise KeyError(f"Schema file {schema_file} is missing required '$id' field")

    schema_id = schema["$id"]
    if schema_id.startswith('http://') or schema_id.startswith('https://'):
        schema_id = schema_id.split('/')[-1]

    return schema_id, schema


def generate_task_name(folder_name: str, folder_id: str) -> str:
    """
    Synapse raw API uses param `dataType` for setting task display name, which is rather confusing.
    This generates the CurationTask's `dataType`, enforcing our current task naming convention 
    that simply uses the dataset folder name - ultimately we should use whatever format is most understandable to folks. 
    It is easiest to identify tasks by the folder they're curating.

    Args:
        folder_name: Name of the upload folder (e.g., 'RNA-seq for Cohort 1')
        folder_id: Synapse folder ID (e.g., 'syn12345678')

    Returns:
        Generated dataType string (e.g., 'RNA-seq for Cohort 1 (syn12345678)')
    """
    return f"{folder_name} ({folder_id})"


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


def resolve_principal_id(identifier: str, syn) -> str:
    """
    Resolve a username, email, team name, or numeric ID to a Synapse principal ID.

    Tries a user profile lookup first, then falls back to a team lookup.

    Args:
        identifier: Username, email, team name, or numeric user/team ID
        syn: Authenticated Synapse client

    Returns:
        The resolved principal ID as a string

    Raises:
        ValueError: If identifier does not resolve to a user or team
    """
    try:
        profile = syn.getUserProfile(identifier)
        return str(profile.ownerId)
    except Exception:
        pass

    try:
        team = syn.getTeam(identifier)
        return str(team.id)
    except Exception:
        pass

    raise ValueError(
        f"Could not resolve '{identifier}' to a Synapse user or team. "
        "Provide a username, email, team name, or numeric principal ID."
    )


# Access types a data contributor needs on the upload folder to actually complete
# the task: READ/CREATE to add new files, UPDATE to edit annotations on them.
REQUIRED_ASSIGNEE_ACCESS = {"READ", "CREATE", "UPDATE"}


def check_assignee_permissions(folder_id: str, principal_id: str, syn) -> bool:
    """
    Check (without modifying) whether an assignee has sufficient permissions on the
    upload folder to complete a curation task. Checks the folder's benefactor, so
    permissions inherited from the parent project/folder are taken into account.

    Args:
        folder_id: Synapse folder ID the task uploads to
        principal_id: Principal ID (user or team) to check
        syn: Authenticated Synapse client

    Returns:
        True if the assignee has all of READ, CREATE, and UPDATE access; False otherwise
    """
    from synapseclient.models import Folder

    print(f"\nChecking permissions for principal {principal_id} on folder {folder_id}...")
    access_types = set(
        Folder(id=folder_id).get_acl(principal_id=int(principal_id), synapse_client=syn)
    )
    missing = REQUIRED_ASSIGNEE_ACCESS - access_types

    if missing:
        print(
            f"⚠ Warning: assignee {principal_id} is missing permissions on {folder_id}: "
            f"{sorted(missing)} (has: {sorted(access_types) or 'none'})"
        )
        print(
            "  This script does not grant permissions — the assignee may not be able to "
            "upload files or annotate them until folder sharing settings are updated."
        )
        return False

    print(f"  ✓ Assignee has required permissions: {sorted(access_types)}")
    return True


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


def bind_schema_to_folder(folder_id: str, schema_uri: str, syn) -> bool:
    """
    Bind a JSON schema to a Synapse folder.

    Binding is a PUT (replace) on the Synapse side, so rebinding a folder that
    already has a schema simply overwrites the existing binding — no unbind step
    is needed first, even when switching to a different template.

    Args:
        folder_id: Synapse folder ID
        schema_uri: JSON schema URI
        syn: Authenticated Synapse client

    Returns:
        True if binding succeeded, False otherwise
    """
    from synapseclient.models import Folder

    print(f"\nBinding schema to folder {folder_id}...")
    try:
        Folder(id=folder_id).bind_schema(json_schema_uri=schema_uri, synapse_client=syn)
        print("✓ Schema bound successfully")
        return True
    except Exception as e:
        print(f"⚠ Warning: Could not bind schema: {e}")
        return False


def create_curation_task(
    upload_folder_id: str,
    template: str,
    instructions: str = "Please add metadata for your files",
    bind_schema: bool = True,
    replace: bool = False,
    assignee: str = None,
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
        assignee: Username, email, team name, or numeric principal ID to assign the
                  task to (optional). If provided, the assignee's existing permissions
                  on the upload folder are checked and a warning is printed if they're
                  insufficient — this script never modifies folder sharing settings.
        auth_token: Synapse authentication token (if None, reads from env)

    Returns:
        Dictionary with task_id, fileview_id, data_type, schema_uri, and project_id
    """
    from synapseclient import Synapse
    from synapseclient.extensions.curator.utils import project_id_from_entity_id
    from synapseclient.models import Folder
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

    print(f"Getting folder information: {upload_folder_id}")
    folder_name = Folder(id=upload_folder_id).get(synapse_client=syn).name
    project_id = project_id_from_entity_id(upload_folder_id, synapse_client=syn)

    print(f"  Folder: {folder_name}")
    print(f"  Project: {project_id}")

    # Resolve assignee and check (but do not modify) their folder permissions
    assignee_principal_id = None
    if assignee:
        print(f"\nResolving assignee: {assignee}")
        assignee_principal_id = resolve_principal_id(assignee, syn)
        print(f"  Principal ID: {assignee_principal_id}")
        check_assignee_permissions(upload_folder_id, assignee_principal_id, syn)

    # Load schema URI and content
    print(f"\nLoading schema: {template}")
    schema_uri, json_schema = load_schema_uri(template)
    print(f"  Schema URI: {schema_uri}")

    # Fetch schema content now if not already loaded (external URI case),
    # so schema fields are available for the annotation check below.
    # Uses the original full URI (`template`), since schema_uri is now the short form.
    if json_schema is None:
        print("  Fetching schema from URI...")
        import requests
        response = requests.get(template)
        if response.status_code == 200:
            json_schema = response.json()
        else:
            print(f"  ⚠ Could not fetch schema from URI (status {response.status_code})")
            json_schema = {}

    # Generate dataType
    data_type = generate_task_name(folder_name, upload_folder_id)
    print(f"  Generated dataType: {data_type}")

    # Warn early if files already have annotations matching the template fields,
    # before any destructive action (task delete / schema rebind).
    schema_fields = set(json_schema.get("properties", {}).keys())
    if schema_fields:
        check_existing_annotations(upload_folder_id, schema_fields, syn)

    # If replacing, delete existing curation task first
    if replace:
        delete_existing_curation_task(upload_folder_id, project_id, syn)

    # Optionally bind schema to folder
    if bind_schema:
        bind_schema_to_folder(upload_folder_id, schema_uri, syn)

    # Create EntityView (file view) using the better implementation from json_schema_entity_view.
    # Columns are deliberately sized (STRING max 80 chars, lists capped at 20 items) to stay
    # within Synapse's 64KB file view row limit -- see utils/check_schema_limits.py.
    print(f"\nCreating file view for folder...")
    from synapseclient.models import ViewTypeMask, EntityView

    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from json_schema_entity_view import _create_columns_from_json_schema

    try:
        columns = _create_columns_from_json_schema(json_schema)
        print(f"  Adding {len(columns)} columns from schema")
    except ValueError as e:
        print(f"  ⚠ Schema has no properties: {e}")
        columns = []

    # Default columns (id, name, etc.) are added automatically; create with just the
    # schema-derived columns, then move id/name to the front for readability.
    file_view = EntityView(
        name=f"{data_type}_FileView",
        parent_id=project_id,
        scope_ids=[upload_folder_id],
        view_type_mask=ViewTypeMask.FILE,
        columns=columns,
    ).store(synapse_client=syn)
    file_view.reorder_column(name="name", index=0)
    file_view.reorder_column(name="id", index=0)
    file_view = file_view.store(synapse_client=syn)

    print(f"  File View ID: {file_view.id}")

    # Create file-based metadata task
    print(f"\nCreating file-based metadata task...")
    print(f"  Folder: {upload_folder_id}")
    print(f"  Data type: {data_type}")
    if assignee_principal_id:
        print(f"  Assignee: {assignee_principal_id}")

    task = CurationTask(
        project_id=project_id,
        data_type=data_type,
        instructions=instructions,
        assignee_principal_id=assignee_principal_id,
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
        "project_id": project_id,
        "assignee_principal_id": assignee_principal_id
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

  # Assign the task to a user or team
  python create_curation_task.py \\
    --folder-id syn12345678 \\
    --template ImagingAssayTemplate \\
    --assignee jsmith

Environment Variables:
  SYNAPSE_AUTH_TOKEN    Synapse authentication token (required)

Notes:
  - Project ID is automatically derived from the folder
  - DataType (task name) is enforced as "{folder_name} ({folder_id})" per team convention, not configurable
  - Schema binding is enabled by default (use --no-bind-schema to skip)
  - Schema URI is loaded from registered-json-schemas/ directory
  - --assignee only checks the assignee's existing folder permissions and warns
    if insufficient; it never changes folder sharing settings
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
        help='Template name, case-insensitive (e.g., ImagingAssayTemplate or imagingassaytemplate) or full schema URI (e.g., https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/sage.schemas.v2571-nf.ChIPSeqTemplate.schema-9.14.0)'
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
        '--assignee',
        default=None,
        help=(
            'Username, email, team name, or numeric principal ID to assign the task to. '
            'Existing folder permissions for the assignee are checked and a warning is '
            'printed if insufficient; this script never modifies folder sharing settings.'
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
            replace=args.replace,
            assignee=args.assignee
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
                    f.write(f"assignee_principal_id={result['assignee_principal_id'] or ''}\n")
            else:
                print("\nGitHub Actions outputs:")
                print(f"task_id={result['task_id']}")
                print(f"fileview_id={result['fileview_id']}")
                print(f"data_type={result['data_type']}")
                print(f"schema_uri={result['schema_uri']}")
                print(f"assignee_principal_id={result['assignee_principal_id'] or ''}")
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
