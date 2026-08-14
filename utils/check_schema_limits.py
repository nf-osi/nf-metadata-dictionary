#!/usr/bin/env python3
"""
Validate schema against Synapse platform limits.

Checks against FILE VIEW configuration limits (stricter than JSON schema):
- STRING: 80 chars, LIST: 80 chars × 20 items (Synapse stores 4 bytes/char UTF-8)
- Row limit: 64KB

Both limits come from the FileView column configuration, so both are checked
against the same set of FileView-backed schemas (see fileview_backed_schemas).

Note: JSON schemas can have larger enums and longer strings for validation.
File views require stricter limits due to 64KB row size constraint.
Note: Synapse no longer enforces a 100-value limit on enums.
"""

import json
import traceback
import yaml
import sys
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple

# Configuration from json_schema_entity_view.py and create_curation_task.py
CONFIG = {
    'STRING_MAX_SIZE': 80,
    'LIST_MAX_SIZE': 80,
    'LIST_MAX_LENGTH': 20,   # Must match json_schema_entity_view.py; reduced from 40 to stay under 64KB
    'SYSTEM_OVERHEAD': 14554,  # System STRING cols × 4 + non-STRING × 8 + row overhead
    # Breakdown: (name 256 + description 1000 + etag 36 + path 1000 + type 20 + dataFileName 256 +
    #             dataFileMD5Hex 100 + dataFileConcreteType 65 + dataFileBucket 100 + dataFileKey 700) × 4
    #             + (16 non-STRING cols × 8) + 294 base = 14132 + 128 + 294 = 14554
    'ROW_LIMIT': 64000,
    'ROW_WARNING': 57600,
}

# Templates deriving from this class are provisioned as Synapse RecordSets via
# create_recordset_task.py rather than as FileViews, so FileView column limits
# do not govern them.
RECORDSET_CLASS = 'RecordSet'


class SchemaCheckError(RuntimeError):
    """The data model could not be checked, with a message fit for the report."""


class SchemaReadError(SchemaCheckError):
    """A module or schema file could not be read or parsed."""


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as err:
        raise SchemaReadError(f"Could not read LinkML module {path}: {err}") from err


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise SchemaReadError(f"Could not read JSON schema {path}: {err}") from err


def find_recordset_classes(module_files: List[Path]) -> Set[str]:
    """Collect the classes that derive from RECORDSET_CLASS, directly or transitively.

    The registered JSON schemas do not record `is_a`, so class ancestry is read
    from the LinkML modules that generate them - which stays correct as further
    RecordSet templates are added.
    """
    parents: Dict[str, Any] = {}
    for yaml_file in module_files:
        data = _load_yaml(yaml_file) or {}
        for name, class_def in (data.get('classes') or {}).items():
            parents[name] = (class_def or {}).get('is_a')

    def derives_from_recordset(name: str) -> bool:
        seen = set()
        while name and name not in seen:
            if name == RECORDSET_CLASS:
                return True
            seen.add(name)
            name = parents.get(name)
        return False

    return {name for name in parents if derives_from_recordset(name)}


def fileview_backed_schemas(schema_files: List[Path], recordset_classes: Set[str]) -> List[Path]:
    """Select the schemas whose values become Synapse FileView columns.

    Both the STRING/LIST character limits and the 64KB row limit come from the
    FileView column configuration, so both checks share this scope. Non-Template
    schemas (PortalDataset, Superdataset, etc.) are not used to create FileViews
    via create_curation_task.py, and RecordSet-backed Templates are provisioned
    via create_recordset_task.py, so neither is governed by those limits.
    """
    return [
        schema_file for schema_file in schema_files
        if schema_file.stem.endswith("Template") and schema_file.stem not in recordset_classes
    ]


def collect_inputs(modules_dir: Path, schemas_dir: Path) -> Tuple[List[Path], List[Path]]:
    """Resolve the modules and FileView-backed schemas to check, or fail loudly.

    A gate that inspects nothing must not report success, so a missing directory,
    an empty directory, or a scope that selects no schema is an error rather than
    a clean run over zero files.
    """
    for flag, path in (('--modules-dir', modules_dir), ('--schemas-dir', schemas_dir)):
        if not path.is_dir():
            raise SchemaCheckError(f"{flag} {path} is not a directory - nothing to validate")

    module_files = sorted(modules_dir.rglob("*.yaml"))
    if not module_files:
        raise SchemaCheckError(f"No LinkML modules found under {modules_dir} - nothing to validate")

    schema_files = sorted(schemas_dir.glob("*.json"))
    if not schema_files:
        raise SchemaCheckError(f"No JSON schemas found in {schemas_dir} - nothing to validate")

    fileview_schemas = fileview_backed_schemas(schema_files, find_recordset_classes(module_files))
    if not fileview_schemas:
        raise SchemaCheckError(
            f"None of the {len(schema_files)} schemas in {schemas_dir} are FileView-backed "
            f"Templates - nothing to validate against FileView limits"
        )

    return module_files, fileview_schemas


def check_enum_sizes(module_files: List[Path], root: Path) -> Dict[str, List]:
    """Count enum sizes (informational only; no limit is enforced)."""
    enum_counts = {}

    for yaml_file in module_files:
        data = _load_yaml(yaml_file)
        if data and 'enums' in data:
            for name, enum_data in data['enums'].items():
                if 'permissible_values' in enum_data:
                    count = len(enum_data['permissible_values'])
                    enum_counts[name] = {
                        'file': str(yaml_file.relative_to(root)),
                        'count': count,
                    }

    return {
        'total': len(enum_counts),
        'largest': sorted(enum_counts.values(), key=lambda x: x['count'], reverse=True)[:5],
    }


def check_string_lengths(schema_files: List[Path]) -> Dict[str, Any]:
    """Check enum value string lengths against the FileView column limits."""
    list_lengths, string_lengths, exceeds = [], [], []

    for schema_file in schema_files:
        schema = _load_json(schema_file)
        for prop_name, prop_def in schema.get("properties", {}).items():
            prop_type = prop_def.get("type", "string")
            if isinstance(prop_type, list):
                prop_type = next((t for t in prop_type if t != "null"), "string")

            if prop_type == "array" and "items" in prop_def:
                enum_values = prop_def["items"].get("enum", [])
                kind, limit, target = 'LIST', CONFIG['LIST_MAX_SIZE'], list_lengths
            elif "enum" in prop_def:
                enum_values = prop_def["enum"]
                kind, limit, target = 'STRING', CONFIG['STRING_MAX_SIZE'], string_lengths
            else:
                continue

            for value in enum_values:
                length = len(str(value))
                target.append(length)
                if length > limit:
                    exceeds.append({
                        'schema': schema_file.stem,
                        'property': prop_name,
                        'kind': kind,
                        'value': str(value),
                        'length': length,
                        'limit': limit,
                    })

    return {
        'list_max': max(list_lengths, default=0),
        'string_max': max(string_lengths, default=0),
        'exceeds': exceeds,
    }


def check_row_sizes(schema_files: List[Path]) -> Dict[str, Any]:
    """Calculate Synapse FileView row sizes for the given schemas.

    Row size formula: Synapse stores STRING columns as UTF-8 (max 4 bytes/char), so:
      row_size = (string_cols × STRING_MAX_SIZE + list_cols × LIST_MAX_SIZE × LIST_MAX_LENGTH) × 4
                 + SYSTEM_OVERHEAD
    """
    schemas = []

    for schema_file in schema_files:
        schema = _load_json(schema_file)
        string_count = list_count = 0

        for prop_def in schema.get("properties", {}).values():
            prop_type = prop_def.get("type", "string")
            if isinstance(prop_type, list):
                prop_type = next((t for t in prop_type if t != "null"), "string")

            if prop_type == "array":
                list_count += 1
            elif prop_type == "string":
                string_count += 1

        row_size = (
            (string_count * CONFIG['STRING_MAX_SIZE'] +
             list_count * CONFIG['LIST_MAX_SIZE'] * CONFIG['LIST_MAX_LENGTH']) * 4 +
            CONFIG['SYSTEM_OVERHEAD']
        )

        schemas.append({
            'name': schema_file.stem,
            'fields': f"{string_count}/{list_count}",
            'row_size': row_size,
            'percent': round(row_size / CONFIG['ROW_LIMIT'] * 100, 1),
            'headroom': CONFIG['ROW_LIMIT'] - row_size,
        })

    schemas.sort(key=lambda x: x['row_size'], reverse=True)
    exceeds = [s for s in schemas if s['row_size'] > CONFIG['ROW_LIMIT']]
    approaching = [s for s in schemas if CONFIG['ROW_WARNING'] < s['row_size'] <= CONFIG['ROW_LIMIT']]

    return {
        'schemas': schemas,
        'exceeds': exceeds,
        'approaching': approaching,
        'largest': schemas[0] if schemas else None,
    }


def format_markdown(enum_data, string_data, row_data) -> str:
    """Generate markdown report."""
    lines = ["# Schema Limits Report", ""]

    # Config
    lines.extend([
        "## File View Configuration (Synapse Platform Limits)",
        f"- STRING: {CONFIG['STRING_MAX_SIZE']} chars × 4 bytes (UTF-8), LIST: {CONFIG['LIST_MAX_SIZE']} chars × {CONFIG['LIST_MAX_LENGTH']} items × 4 bytes",
        f"- Limits: {CONFIG['ROW_LIMIT']:,} bytes/row",
        "",
        "_Note: checked for FileView-backed Templates only; RecordSet-backed Templates and non-Template schemas do not become FileView columns._",
        "_Note: Synapse stores VARCHAR as UTF-8 (max 4 bytes/char). Row size = (string + list fields) × 4 + system overhead._",
        "_Note: Synapse no longer enforces a per-enum value count limit._",
        ""
    ])

    # Enums (informational)
    lines.append("## Enum Sizes (informational)")
    lines.append(f"### {enum_data['total']} enums found (no limit enforced)")
    if enum_data['largest']:
        lines.append("Top 5 largest:")
        for e in enum_data['largest']:
            lines.append(f"- {e['count']} values: `{e['file']}`")
    lines.append("")

    # String lengths
    lines.extend([
        "## String Lengths",
        f"- List max: {string_data['list_max']} chars (limit: {CONFIG['LIST_MAX_SIZE']})",
        f"- String max: {string_data['string_max']} chars (limit: {CONFIG['STRING_MAX_SIZE']})",
    ])

    string_violations = string_data['exceeds']
    if string_violations:
        lines.append(f"### ❌ {len(string_violations)} values exceed limits")
        for v in string_violations:
            lines.append(
                f"- {v['schema']}.{v['property']}: {v['length']} chars "
                f"(+{v['length'] - v['limit']} over {v['kind']} limit) `{v['value']}`"
            )
    else:
        lines.append("### ✅ All values within limits")
    lines.append("")

    # Row sizes
    lines.append("## Row Sizes")
    if row_data['exceeds']:
        lines.append(f"### ❌ {len(row_data['exceeds'])} schemas exceed 64KB")
        for s in row_data['exceeds']:
            lines.append(f"- {s['name']}: {s['row_size']:,} bytes (+{s['row_size'] - CONFIG['ROW_LIMIT']:,} over)")
    else:
        lines.append("### ✅ All schemas within 64KB limit")

    lines.extend([
        "",
        "### Top 10 Largest",
        "| Schema | S/L Fields | Row Size | % | Headroom |",
        "|--------|------------|----------|---|----------|"
    ])

    for s in row_data['schemas'][:10]:
        status = "❌" if s['row_size'] > CONFIG['ROW_LIMIT'] else "⚠️" if s['row_size'] > CONFIG['ROW_WARNING'] else "✅"
        lines.append(f"| {status} {s['name']} | {s['fields']} | {s['row_size']:,} | {s['percent']}% | {s['headroom']:,} |")

    # Summary
    lines.extend([
        "",
        "## Summary",
        f"- Enums: {enum_data['total']} total (no limit enforced)",
        f"- Schemas: {len(row_data['schemas'])} FileView-backed, {len(row_data['exceeds'])} exceed, {len(row_data['approaching'])} approaching",
        f"- Values over STRING/LIST limits: {len(string_violations)}",
    ])

    if row_data['exceeds'] or string_violations:
        lines.append("\n❌ **VALIDATION FAILED** - Critical issues found")
    elif row_data['approaching']:
        lines.append("\n⚠️  **WARNINGS** - Some limits approaching")
    else:
        lines.append("\n✅ **ALL CHECKS PASSED**")

    return '\n'.join(lines)


def _fail(output: str, detail: str) -> None:
    """Record the failure in the report and exit non-zero.

    The report is always written: the PR comment step runs with `if: always()`
    and needs a message file to post, so a failure must be diagnosable there.
    """
    message = f"# Schema Limits Report\n\n❌ **VALIDATION FAILED** - {detail}\n"
    if output:
        Path(output).write_text(message)
    print(f"ERROR: {detail}", file=sys.stderr)
    sys.exit(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Validate schema against Synapse limits')
    parser.add_argument('--modules-dir', default='modules', help='Modules directory')
    parser.add_argument('--schemas-dir', default='registered-json-schemas', help='Schemas directory')
    parser.add_argument('--output', help='Output file (default: stdout)')
    parser.add_argument('--format', choices=['markdown', 'json'], default='markdown')
    parser.add_argument('--strict', action='store_true', help='Exit with error if limits exceeded')
    args = parser.parse_args()

    # Run checks
    modules_dir = Path(args.modules_dir)
    try:
        module_files, fileview_schemas = collect_inputs(modules_dir, Path(args.schemas_dir))
        enum_data = check_enum_sizes(module_files, modules_dir.parent)
        string_data = check_string_lengths(fileview_schemas)
        row_data = check_row_sizes(fileview_schemas)
    except SchemaCheckError as err:
        _fail(args.output, str(err))
    except Exception:
        _fail(args.output, f"unexpected error reading the data model:\n\n```\n{traceback.format_exc()}```")

    # Format output
    if args.format == 'json':
        output = json.dumps({
            'config': CONFIG,
            'enums': enum_data,
            'strings': string_data,
            'rows': row_data,
        }, indent=2)
    else:
        output = format_markdown(enum_data, string_data, row_data)

    # Write
    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}")
    else:
        print(output)

    # Exit codes
    if args.strict:
        if row_data['exceeds'] or string_data['exceeds']:
            sys.exit(1)
        elif row_data['approaching']:
            sys.exit(2)

    sys.exit(0)


if __name__ == '__main__':
    main()
