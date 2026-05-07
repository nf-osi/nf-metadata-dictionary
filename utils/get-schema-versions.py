#!/usr/bin/env python3
"""
Retrieve and summarize the latest semantic version for all JSON schemas slated for release.

Uses only Python standard library - no extra pip installs required.
No credentials needed; the Synapse schema version list endpoint is public.

Usage:
    python get-schema-versions.py --schema-dir registered-json-schemas [--exclude file1.json ...]

Output:
    Text summary of each schema's latest registered version in Synapse.
    Schemas not yet registered are listed separately.
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path


SYNAPSE_API = "https://repo-prod.prod.sagebase.org/repo/v1"


def parse_version(version_str: str) -> tuple:
    """Parse a semantic version string into a comparable tuple."""
    try:
        return tuple(int(x) for x in version_str.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def get_all_versions(org: str, name: str) -> list:
    """Return all registered semantic versions for a schema from Synapse."""
    url = f"{SYNAPSE_API}/schema/version/list"
    payload = json.dumps({"organizationName": org, "schemaName": name}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        page = data.get("page", data.get("results", []))
        return [r["semanticVersion"] for r in page if r.get("semanticVersion")]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # Schema not registered yet
        raise


def parse_schema_id(schema_file: Path):
    """Parse org and name from a JSON schema file's $id field.

    Returns (org, name) tuple or None if parsing fails.
    """
    with open(schema_file) as f:
        schema = json.load(f)

    schema_id = schema.get("$id", "")
    if not schema_id:
        return None

    # Strip URL prefix if present
    if "://" in schema_id:
        base_id = schema_id.split("/")[-1]
    else:
        base_id = schema_id

    # Remove version suffix if present (e.g. org.synapse.nf-template-1.0.0)
    parts = base_id.rsplit("-", 1)
    if len(parts) == 2 and parts[1].replace(".", "").isdigit():
        base_id = parts[0]

    if "-" not in base_id:
        return None

    org, name = base_id.split("-", 1)
    return org, name


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve latest schema versions from Synapse for release evaluation"
    )
    parser.add_argument(
        "--schema-dir",
        required=True,
        type=Path,
        help="Directory containing JSON schema files",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Schema filenames to exclude (e.g. --exclude Superdataset.json)",
    )
    args = parser.parse_args()

    if not args.schema_dir.exists():
        print(f"ERROR: Schema directory not found: {args.schema_dir}", file=sys.stderr)
        sys.exit(1)

    exclude_set = set(args.exclude)
    schema_files = sorted(args.schema_dir.glob("*.json"))

    registered = []   # (full_name, latest_version, version_count)
    unregistered = [] # full_name
    errors = []       # full_name

    for schema_file in schema_files:
        if schema_file.name in exclude_set:
            continue

        parsed = parse_schema_id(schema_file)
        if parsed is None:
            print(f"Warning: could not parse $id from {schema_file.name}", file=sys.stderr)
            continue

        org, name = parsed
        full_name = f"{org}-{name}"

        try:
            versions = get_all_versions(org, name)
            if versions:
                latest = max(versions, key=parse_version)
                registered.append((full_name, latest, len(versions)))
            else:
                unregistered.append(full_name)
        except Exception as e:
            print(f"Warning: could not check {full_name}: {e}", file=sys.stderr)
            errors.append(full_name)

    # Build summary
    lines = ["Schema versions currently registered in Synapse:", ""]

    for full_name, latest, count in registered:
        lines.append(f"  {full_name}: {latest} ({count} version(s) total)")

    if unregistered:
        lines.append("")
        lines.append("Not yet registered (new schemas):")
        for full_name in unregistered:
            lines.append(f"  {full_name}")

    if errors:
        lines.append("")
        lines.append("Could not retrieve (errors):")
        for full_name in errors:
            lines.append(f"  {full_name}")

    lines.append("")
    lines.append(
        f"Summary: {len(registered)} registered, {len(unregistered)} new, {len(errors)} errors"
    )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
