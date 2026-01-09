"""Create entity views from JSON Schema URIs

This module creates Synapse entity views based on JSON Schema URIs.
Unlike the schematic version, this allows schema URIs without semantic versions.
"""

from typing import Any, Optional
import os
import requests
from synapseclient import Synapse
from synapseclient.models import Column, ColumnType, ViewTypeMask, EntityView

TYPE_DICT = {
    "string": ColumnType.STRING,
    "number": ColumnType.DOUBLE,
    "integer": ColumnType.INTEGER,
    "boolean": ColumnType.BOOLEAN,
}

LIST_TYPE_DICT = {
    "string": ColumnType.STRING_LIST,
    "integer": ColumnType.INTEGER_LIST,
    "boolean": ColumnType.BOOLEAN_LIST,
}


def create_entity_view_from_schema_uri(
    syn: Synapse,
    schema_uri: str,
    parent_id: str,
    scope_ids: list[str],
    entity_view_name: str = "JSON Schema view",
    bind_schema: bool = True,
) -> str:
    """
    Creates a Synapse entity view based on a JSON Schema URI.
    Optionally binds the schema to the entities in scope_ids.

    The schema URI format is: org-schemaName (version not specified, uses latest)
    Example: "nf.nfosi-BehavioralAssay"

    Args:
        syn: A Synapse object that's been logged in
        schema_uri: The URI of the JSON schema (format: org-schemaName, no version)
        parent_id: The parent entity ID where the view will be created
        scope_ids: List of entity IDs to include in the view scope
        entity_view_name: The name the created entity view will have
        bind_schema: Whether to bind the schema to entities in scope_ids (default: True)

    Returns:
        The Synapse id of the created entity view
    """
    # Parse the schema URI - split on first "-" only
    parts = schema_uri.split("-", 1)

    if len(parts) != 2:
        raise ValueError(
            f"Invalid schema URI format: {schema_uri}. "
            "Expected format: 'org-schemaName' (e.g., 'nf.nfosi-BehavioralAssay')"
        )

    org_name = parts[0]
    schema_name = parts[1]

    # Fetch schema directly from public API (gets latest version)
    schema_url = f"https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/{org_name}-{schema_name}"
    response = requests.get(schema_url)

    if response.status_code != 200:
        raise ValueError(
            f"Failed to fetch schema from {schema_url}. "
            f"Status: {response.status_code}, Error: {response.text}"
        )

    # The response IS the JSON schema directly
    json_schema = response.json()

    # Extract version from the $id field if present
    schema_id = json_schema.get("$id", "")
    # $id format: https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org-schemaName-version
    # We need the full URI including version for binding
    if schema_id:
        # Extract the org-schemaName-version from the URL
        full_schema_uri = schema_id.split("/")[-1]
    else:
        # Fallback if no $id
        full_schema_uri = f"{org_name}-{schema_name}"

    # Bind schema to entities in scope_ids if requested
    if bind_schema:
        js_service = syn.service("json_schema")
        for entity_id in scope_ids:
            js_service.bind_json_schema(full_schema_uri, entity_id)

    # Get the schema body and create columns
    columns = _create_columns_from_json_schema(json_schema)

    # Add only essential columns: id and name
    # Note: EntityView automatically adds these, but we specify them explicitly
    # to ensure they're in the correct order
    essential_columns = [
        Column(name="id", column_type=ColumnType.ENTITYID),
        Column(name="name", column_type=ColumnType.STRING, maximum_size=256),
    ]

    # Combine essential columns with schema columns
    all_columns = essential_columns + columns

    # Create the entity view
    view = EntityView(
        name=entity_view_name,
        parent_id=parent_id,
        scope_ids=scope_ids,
        view_type_mask=ViewTypeMask.FILE,
        columns=all_columns,
    ).store(synapse_client=syn)

    return view.id


def _create_columns_from_json_schema(json_schema: dict[str, Any]) -> list[Column]:
    """Creates a list of Synapse Columns based on the JSON Schema type

    Arguments:
        json_schema: The JSON Schema in dict form

    Raises:
        ValueError: If the JSON Schema has no properties
        ValueError: If the JSON Schema properties is not a dict

    Returns:
        A list of Synapse columns based on the JSON Schema
    """
    properties = json_schema.get("properties")
    if properties is None:
        raise ValueError("The JSON Schema is missing a 'properties' field.")
    if not isinstance(properties, dict):
        raise ValueError(
            "The 'properties' field in the JSON Schema must be a dictionary."
        )
    columns = []
    for name, prop_schema in properties.items():
        column_type = _get_column_type_from_js_property(prop_schema)

        # Extract limits from JSON schema if they exist
        maximum_size = _get_max_length_from_js_property(prop_schema)
        maximum_list_length = _get_max_items_from_js_property(prop_schema)

        # Build column kwargs, only including limits if they exist
        column_kwargs = {
            "name": name,
            "column_type": column_type,
        }
        if maximum_size is not None:
            column_kwargs["maximum_size"] = maximum_size
        if maximum_list_length is not None:
            column_kwargs["maximum_list_length"] = maximum_list_length

        column = Column(**column_kwargs)
        columns.append(column)
    return columns


def _get_column_type_from_js_property(js_property: dict[str, Any]) -> ColumnType:
    """
    Gets the Synapse column type from a JSON Schema property.
    The JSON Schema should be valid but that should not be assumed.
    If the type can not be determined ColumnType.STRING will be returned.

    Args:
        js_property: A JSON Schema property in dict form.

    Returns:
        A Synapse ColumnType based on the JSON Schema type
    """
    # Enums are always strings in Synapse tables
    if "enum" in js_property:
        return ColumnType.STRING
    if "type" in js_property:
        if js_property["type"] == "array":
            return _get_list_column_type_from_js_property(js_property)
        return TYPE_DICT.get(js_property["type"], ColumnType.STRING)
    # A oneOf list usually indicates that the type could be one or more different things
    if "oneOf" in js_property and isinstance(js_property["oneOf"], list):
        return _get_column_type_from_js_one_of_list(js_property["oneOf"])
    return ColumnType.STRING


def _get_column_type_from_js_one_of_list(js_one_of_list: list[Any]) -> ColumnType:
    """
    Gets the Synapse column type from a JSON Schema oneOf list.
    Items in the oneOf list should be dicts, but that should not be assumed.

    Args:
        js_one_of_list: A list of items to check for type

    Returns:
        A Synapse ColumnType based on the JSON Schema type
    """
    # items in a oneOf list should be dicts
    items = [item for item in js_one_of_list if isinstance(item, dict)]
    # Enums are always strings in Synapse tables
    if [item for item in items if "enum" in item]:
        return ColumnType.STRING
    # For Synapse ColumnType we can ignore null types in JSON Schemas
    type_items = [item for item in items if "type" in item if item["type"] != "null"]
    if len(type_items) == 1:
        type_item = type_items[0]
        if type_item["type"] == "array":
            return _get_list_column_type_from_js_property(type_item)
        return TYPE_DICT.get(type_item["type"], ColumnType.STRING)
    return ColumnType.STRING


def _get_list_column_type_from_js_property(js_property: dict[str, Any]) -> ColumnType:
    """
    Gets the Synapse column type from a JSON Schema array property

    Args:
        js_property: A JSON Schema property in dict form.

    Returns:
        A Synapse ColumnType based on the JSON Schema type
    """
    if "items" in js_property and isinstance(js_property["items"], dict):
        # Enums are always strings in Synapse tables
        if "enum" in js_property["items"]:
            return ColumnType.STRING_LIST
        if "type" in js_property["items"]:
            return LIST_TYPE_DICT.get(
                js_property["items"]["type"], ColumnType.STRING_LIST
            )

    return ColumnType.STRING_LIST


def _get_max_length_from_js_property(js_property: dict[str, Any]) -> Optional[int]:
    """
    Extracts maxLength from a JSON Schema property if it exists.

    Args:
        js_property: A JSON Schema property in dict form.

    Returns:
        The maxLength value if present, otherwise None.
    """
    # Direct maxLength on the property
    if "maxLength" in js_property:
        return js_property["maxLength"]

    # Check in oneOf list (for nullable types)
    if "oneOf" in js_property and isinstance(js_property["oneOf"], list):
        for item in js_property["oneOf"]:
            if isinstance(item, dict) and "maxLength" in item:
                return item["maxLength"]

    return None


def _get_max_items_from_js_property(js_property: dict[str, Any]) -> Optional[int]:
    """
    Extracts maxItems from a JSON Schema property if it exists.

    Args:
        js_property: A JSON Schema property in dict form.

    Returns:
        The maxItems value if present, otherwise None.
    """
    # Direct maxItems on the property (for array types)
    if "maxItems" in js_property:
        return js_property["maxItems"]

    # Check in oneOf list (for nullable array types)
    if "oneOf" in js_property and isinstance(js_property["oneOf"], list):
        for item in js_property["oneOf"]:
            if isinstance(item, dict) and "maxItems" in item:
                return item["maxItems"]

    return None


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 4:
        print("Usage: python json_schema_entity_view.py <schema_uri> <parent_id> <scope_id> [view_name]")
        print("Example: python json_schema_entity_view.py nf.nfosi-BehavioralAssay syn28499308 syn28499308 'Behavioral Assay View'")
        sys.exit(1)

    schema_uri = sys.argv[1]
    parent_id = sys.argv[2]
    scope_id = sys.argv[3]
    view_name = sys.argv[4] if len(sys.argv) > 4 else "JSON Schema view"

    # Initialize Synapse client
    syn = Synapse()
    auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')
    if not auth_token:
        raise ValueError("SYNAPSE_AUTH_TOKEN environment variable is required")
    syn.login(authToken=auth_token)

    # Create entity view
    view_id = create_entity_view_from_schema_uri(
        syn=syn,
        schema_uri=schema_uri,
        parent_id=parent_id,
        scope_ids=[scope_id],
        entity_view_name=view_name,
    )

    print(f"✅ Created entity view: {view_id}")
