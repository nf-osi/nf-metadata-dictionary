#!/usr/bin/env python3
"""
Check if JSON schemas with a specific version already exist in Synapse.

This script prevents duplicate schema registration by querying Synapse for
existing schema versions before attempting to register new ones.

Usage:
    python check-schema-versions.py --schema-dir <dir> --version <version>

Example:
    python check-schema-versions.py --schema-dir versioned-schemas --version 0.9.9
"""

import argparse
import json
import os
import sys
from pathlib import Path

import synapseclient


def check_schema_versions(schema_dir: Path, version: str) -> list:
    """
    Check if schemas with the given version already exist in Synapse.

    Args:
        schema_dir: Directory containing JSON schemas (base or versioned)
        version: Version string to check (e.g., "0.9.9")

    Returns:
        List of schema names that already exist with this version
    """
    # Initialize Synapse client
    syn = synapseclient.Synapse()
    auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')

    if not auth_token:
        print("❌ ERROR: SYNAPSE_AUTH_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    syn.login(authToken=auth_token)

    existing_schemas = []
    failed_checks = []

    for schema_file in schema_dir.glob('*.json'):
        with open(schema_file) as f:
            schema = json.load(f)
            schema_id = schema.get('$id', '')

            if not schema_id:
                print(f"⚠️  Warning: Schema file {schema_file.name} has no $id field", file=sys.stderr)
                continue

            # Parse organization and name from schema $id
            # The schema ID can be either:
            # 1. URL format: https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-templatename
            # 2. Direct format: org.synapse.nf-templatename or org.synapse.nf-templatename-version

            # Extract the final part if it's a URL
            if '://' in schema_id:
                # URL format - get the part after the last slash
                base_id = schema_id.split('/')[-1]
            else:
                # Direct format - use as-is
                base_id = schema_id

            # Remove version suffix if present (e.g., org.synapse.nf-template-1.0.0)
            # Version format is -MAJOR.MINOR.PATCH at the end
            parts = base_id.rsplit('-', 1)
            if len(parts) == 2 and parts[1].replace('.', '').isdigit():
                base_id = parts[0]  # Remove version suffix

            # Extract organization and name
            # Format: org.synapse.nf-schemaname
            # Organization: org.synapse.nf (everything before first hyphen)
            # Schema name: schemaname (everything after first hyphen)
            if '-' in base_id:
                org, name = base_id.split('-', 1)  # Split on first hyphen only
            else:
                print(f"⚠️  Warning: Could not parse schema ID (no hyphen): {schema_id}", file=sys.stderr)
                failed_checks.append(schema_file.name)
                continue

            # Debug output (can be removed once working)
            if os.environ.get('DEBUG'):
                print(f"  Checking {schema_file.name}: org={org}, name={name}", file=sys.stderr)

            try:
                # Query Synapse for existing versions
                request_body = {
                    'organizationName': org,
                    'schemaName': name
                }
                response = syn.restPOST(
                    '/schema/version/list',
                    body=json.dumps(request_body)
                )

                # Debug: show response
                if os.environ.get('DEBUG'):
                    print(f"  Response: {json.dumps(response, indent=2)[:500]}", file=sys.stderr)

                # Check if our version exists
                # The response contains a 'page' array with all registered versions of this schema
                page = response.get('page', response.get('results', []))
                if page:
                    if os.environ.get('DEBUG'):
                        print(f"  Found {len(page)} existing version(s)", file=sys.stderr)

                    for result in page:
                        # Check the semanticVersion field
                        result_version = result.get('semanticVersion')
                        if os.environ.get('DEBUG'):
                            print(f"    Checking version: {result_version} == {version}?", file=sys.stderr)

                        if result_version == version:
                            schema_full_name = f"{org}-{name}"
                            existing_schemas.append(schema_full_name)
                            print(f"⚠️  Found existing: {schema_full_name} (version {version})")

            except Exception as e:
                # Schema might not exist yet (404), which is fine - means no versions registered
                if 'not found' in str(e).lower() or '404' in str(e):
                    # Schema doesn't exist yet, so version definitely doesn't exist
                    continue
                else:
                    # Other errors (400, 500, etc.) mean we couldn't verify
                    schema_full_name = f"{org}-{name}"
                    failed_checks.append(schema_full_name)
                    print(f"❌ Could not verify {schema_full_name}: {e}", file=sys.stderr)

    return existing_schemas, failed_checks


def main():
    parser = argparse.ArgumentParser(
        description='Check if JSON schemas with a specific version already exist in Synapse'
    )
    parser.add_argument(
        '--schema-dir',
        required=True,
        type=Path,
        help='Directory containing versioned JSON schema files'
    )
    parser.add_argument(
        '--version',
        required=True,
        help='Version string to check (e.g., 0.9.9)'
    )

    args = parser.parse_args()

    if not args.schema_dir.exists():
        print(f"❌ ERROR: Schema directory not found: {args.schema_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Checking if schemas with version {args.version} already exist in Synapse...")

    existing_schemas, failed_checks = check_schema_versions(args.schema_dir, args.version)

    # Check for failures first
    if failed_checks:
        print(f"\n❌ ERROR: Could not verify the following schemas:")
        for schema in failed_checks:
            print(f"  - {schema}")
            # GitHub Actions annotation
            print(f"::error::Could not verify schema: {schema}")
        print(f"\nCannot safely proceed with registration when some schemas cannot be verified.")
        print("::error::Version check failed - some schemas could not be verified")
        sys.exit(1)

    # Check for existing versions
    if existing_schemas:
        print(f"\n❌ ERROR: The following schemas already exist in Synapse with version {args.version}:")
        for schema in existing_schemas:
            print(f"  - {schema}")
            # GitHub Actions annotation
            print(f"::error::Schema already exists with version {args.version}: {schema}")
        print(f"\nPlease use a different version number or remove existing schemas before proceeding.")
        print(f"::error::Version {args.version} already exists in Synapse - choose a different version number")
        sys.exit(1)

    # All checks passed
    print(f"✅ No existing schemas found with version {args.version}. Safe to proceed with registration.")
    print(f"::notice::Version {args.version} is available - proceeding with registration")
    sys.exit(0)


if __name__ == '__main__':
    main()
