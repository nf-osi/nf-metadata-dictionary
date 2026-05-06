#!/usr/bin/env python3
"""
Swap the JSON schema binding on a Synapse entity.

Unbinds the current schema (if any) and binds a new one.
Accepts a registered schema ID (e.g. org.synapse.nf-wgstemplate-0.0.123)
or a full Synapse schema URI.

Usage:
  SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/swap_schema.py \\
    --entity-id syn12345678 \\
    --schema-id org.synapse.nf-wgstemplate-0.0.20260506015001
"""

import argparse
import os
import sys

SYNAPSE_SCHEMA_BASE = "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/"


def schema_uri(schema_id: str) -> str:
    """Return the full Synapse schema URI for a schema ID or passthrough if already a URL."""
    if schema_id.startswith("http://") or schema_id.startswith("https://"):
        return schema_id
    return SYNAPSE_SCHEMA_BASE + schema_id


def main():
    parser = argparse.ArgumentParser(description="Swap JSON schema binding on a Synapse entity")
    parser.add_argument("--entity-id", required=True, help="Synapse entity ID (e.g. syn12345678)")
    parser.add_argument(
        "--schema-id",
        required=True,
        help="Registered schema ID (e.g. org.synapse.nf-wgstemplate-0.0.123) or full schema URI",
    )
    args = parser.parse_args()

    auth_token = os.environ.get("SYNAPSE_AUTH_TOKEN")
    if not auth_token:
        print("Error: SYNAPSE_AUTH_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)

    import synapseclient
    from synapseclient.services.json_schema import JsonSchemaService

    syn = synapseclient.Synapse()
    syn.login(authToken=auth_token)
    svc = JsonSchemaService(syn)

    uri = schema_uri(args.schema_id)
    print(f"Entity : {args.entity_id}")
    print(f"Schema : {uri}")

    # Unbind existing schema
    print("\nUnbinding existing schema...")
    try:
        svc.delete_json_schema_from_entity(synapse_id=args.entity_id)
        print("  ✓ Existing schema unbound")
    except Exception as e:
        if any(k in str(e).lower() for k in ("not found", "no schema", "404")):
            print("  No existing schema binding (skipping)")
        else:
            print(f"  Warning: {e}")

    # Bind new schema
    print("\nBinding new schema...")
    try:
        svc.bind_json_schema_to_entity(synapse_id=args.entity_id, json_schema_uri=uri)
        print(f"  ✓ Bound: {uri}")
    except Exception as e:
        print(f"  ✗ Failed to bind schema: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
