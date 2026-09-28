#!/usr/bin/env python3
"""
Validate schema against Synapse platform limits.

Checks against FILE VIEW configuration limits (stricter than JSON schema):
- STRING: 80 chars, LIST: 80 chars × 20 items (Synapse stores 4 bytes/char UTF-8)
- Row limit: 64KB (only checked for Template schemas used in FileViews)

Note: JSON schemas can have larger enums and longer strings for validation.
File views require stricter limits due to 64KB row size constraint.
Note: Synapse no longer enforces a 100-value limit on enums.
"""

import json
import yaml
import sys
from pathlib import Path
from typing import Dict, List, Any

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


def check_enum_sizes(modules_dir: Path) -> Dict[str, List]:
    """Count enum sizes (informational only; no limit is enforced)."""
    enum_counts = {}

    for yaml_file in modules_dir.rglob("*.yaml"):
        try:
            data = yaml.safe_load(yaml_file.read_text())
            if data and 'enums' in data:
                for name, enum_data in data['enums'].items():
                    if 'permissible_values' in enum_data:
                        count = len(enum_data['permissible_values'])
                        enum_counts[name] = {
                            'file': str(yaml_file.relative_to(modules_dir.parent)),
                            'count': count,
                        }
        except:
            pass

    return {
        'total': len(enum_counts),
        'largest': sorted(enum_counts.values(), key=lambda x: x['count'], reverse=True)[:5],
    }


def check_string_lengths(schemas_dir: Path) -> Dict[str, Any]:
    """Check enum value string lengths.

    Over-limit values are a warning tier, not an error -- see the exit codes in main().
    Because they never gate a PR, the report is the only channel by which anyone learns
    about one, so the offenders are carried through by identity (schema, property, value)
    rather than merely counted.  Values are de-duplicated: the same label reached from
    three templates is one problem in the model, not three.
    """
    list_lengths, string_lengths = [], []
    over_limit: Dict[str, Dict[str, Any]] = {}

    for schema_file in sorted(schemas_dir.glob("*.json")):
        try:
            schema = json.loads(schema_file.read_text())
            for prop_name, prop_def in schema.get("properties", {}).items():
                prop_type = prop_def.get("type", "string")
                if isinstance(prop_type, list):
                    prop_type = next((t for t in prop_type if t != "null"), "string")

                enum_values = []
                if prop_type == "array" and "items" in prop_def:
                    enum_values = prop_def["items"].get("enum", [])
                    target, kind, limit = list_lengths, "LIST", CONFIG['LIST_MAX_SIZE']
                elif "enum" in prop_def:
                    enum_values = prop_def["enum"]
                    target, kind, limit = string_lengths, "STRING", CONFIG['STRING_MAX_SIZE']
                else:
                    continue

                for v in enum_values:
                    value = str(v)
                    target.append(len(value))
                    if len(value) > limit:
                        entry = over_limit.setdefault(value, {
                            'value': value,
                            'chars': len(value),
                            'kind': kind,
                            'limit': limit,
                            'usages': [],
                        })
                        entry['usages'].append(f"{schema_file.stem}.{prop_name}")
        except Exception:
            pass

    return {
        'list_max': max(list_lengths, default=0),
        'string_max': max(string_lengths, default=0),
        'list_exceeds': sum(1 for l in list_lengths if l > CONFIG['LIST_MAX_SIZE']),
        'string_exceeds': sum(1 for l in string_lengths if l > CONFIG['STRING_MAX_SIZE']),
        # Distinct offending values, widest overflow first.
        'over_limit': sorted(over_limit.values(), key=lambda e: -e['chars']),
    }


def check_row_sizes(schemas_dir: Path) -> Dict[str, Any]:
    """Calculate row sizes for Template schemas (those used as Synapse FileView columns).

    Row size formula: Synapse stores STRING columns as UTF-8 (max 4 bytes/char), so:
      row_size = (string_cols × STRING_MAX_SIZE + list_cols × LIST_MAX_SIZE × LIST_MAX_LENGTH) × 4
                 + SYSTEM_OVERHEAD
    Only schemas ending in 'Template' are checked, as non-Template schemas (PortalDataset,
    Superdataset, etc.) are not used to create FileViews via create_curation_task.py.
    """
    schemas = []

    for schema_file in schemas_dir.glob("*.json"):
        if not schema_file.stem.endswith("Template"):
            continue
        try:
            schema = json.loads(schema_file.read_text())
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
        except:
            pass

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
        f"- Limits: {CONFIG['ROW_LIMIT']:,} bytes/row (Template schemas only)",
        "",
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

    over = string_data.get('over_limit') or []
    if over:
        lines.append(f"### ⚠️  {len(over)} value(s) exceed limits (warning -- does not block merge)")
        lines.append("")
        lines.append("| Chars | Over by | Type | Value | Used by |")
        lines.append("|-------|---------|------|-------|---------|")
        for e in over:
            usages = ", ".join(f"`{u}`" for u in e['usages'])
            lines.append(
                f"| {e['chars']} | +{e['chars'] - e['limit']} | {e['kind']} | "
                f"{e['value']} | {usages} |"
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
        f"- Schemas: {len(row_data['schemas'])} total, {len(row_data['exceeds'])} exceed, {len(row_data['approaching'])} approaching",
    ])

    # Warnings come from any check, not row sizes alone: a string-length overflow is a
    # real finding even though it deliberately does not gate (see exit codes in main()).
    warnings = []
    if row_data['approaching']:
        warnings.append(f"{len(row_data['approaching'])} schema(s) approaching the row-size limit")
    if string_data['string_exceeds'] or string_data['list_exceeds']:
        warnings.append(f"{len(string_data.get('over_limit') or [])} value(s) over the string-length limit")

    if row_data['exceeds']:
        lines.append("\n❌ **VALIDATION FAILED** - Critical issues found")
    elif warnings:
        lines.append("\n⚠️  **WARNINGS** - " + "; ".join(warnings))
    else:
        lines.append("\n✅ **ALL CHECKS PASSED**")

    return '\n'.join(lines)


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
    enum_data = check_enum_sizes(Path(args.modules_dir))
    string_data = check_string_lengths(Path(args.schemas_dir))
    row_data = check_row_sizes(Path(args.schemas_dir))

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

    # Exit codes under --strict:
    #   1 = error   -- row size over the 64KB limit; a file view built on this schema breaks.
    #   2 = warning -- surfaced in the report but deliberately does NOT gate a PR.
    #   0 = clean.
    # String/list length overflow is a warning by decision, not an oversight: the values
    # that trip it are standardized vocabulary terms (e.g. WHO CNS5 diagnoses) where
    # abbreviating to fit an 80-char column would lose fidelity.  Callers must treat
    # exit 2 as passing.
    if args.strict:
        if row_data['exceeds']:
            sys.exit(1)
        elif (row_data['approaching']
              or string_data['string_exceeds']
              or string_data['list_exceeds']):
            sys.exit(2)

    sys.exit(0)


if __name__ == '__main__':
    main()
