#!/usr/bin/env python3
"""
Validate schema against Synapse platform limits.

Checks enum sizes, string lengths, and row sizes with current configuration:
- STRING: 80 chars, LIST: 80 chars × 40 items, name: 256 chars
- Row limit: 64KB, Enum limit: 100 values
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
    'LIST_MAX_LENGTH': 40,
    'NAME_MAX_SIZE': 256,
    'SYSTEM_OVERHEAD': 3500,
    'ENUM_LIMIT': 100,
    'ROW_LIMIT': 64000,
    'ENUM_WARNING': 80,
    'ROW_WARNING': 57600,
}


def check_enum_sizes(modules_dir: Path) -> Dict[str, List]:
    """Check enum sizes against 100-value limit."""
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
                            'remaining': CONFIG['ENUM_LIMIT'] - count
                        }
        except:
            pass

    exceeds = [e for e in enum_counts.values() if e['count'] > CONFIG['ENUM_LIMIT']]
    approaching = [e for e in enum_counts.values() if CONFIG['ENUM_WARNING'] <= e['count'] <= CONFIG['ENUM_LIMIT']]

    return {
        'exceeds': sorted(exceeds, key=lambda x: x['count'], reverse=True),
        'approaching': sorted(approaching, key=lambda x: x['count'], reverse=True),
        'total': len(enum_counts)
    }


def check_string_lengths(schemas_dir: Path) -> Dict[str, Any]:
    """Check enum value string lengths."""
    list_lengths, string_lengths = [], []

    for schema_file in schemas_dir.glob("*.json"):
        try:
            schema = json.loads(schema_file.read_text())
            for prop_def in schema.get("properties", {}).values():
                prop_type = prop_def.get("type", "string")
                if isinstance(prop_type, list):
                    prop_type = next((t for t in prop_type if t != "null"), "string")

                enum_values = []
                if prop_type == "array" and "items" in prop_def:
                    enum_values = prop_def["items"].get("enum", [])
                    target = list_lengths
                elif "enum" in prop_def:
                    enum_values = prop_def["enum"]
                    target = string_lengths
                else:
                    continue

                target.extend(len(str(v)) for v in enum_values)
        except:
            pass

    return {
        'list_max': max(list_lengths, default=0),
        'string_max': max(string_lengths, default=0),
        'list_exceeds': sum(1 for l in list_lengths if l > CONFIG['LIST_MAX_SIZE']),
        'string_exceeds': sum(1 for l in string_lengths if l > CONFIG['STRING_MAX_SIZE']),
    }


def check_row_sizes(schemas_dir: Path) -> Dict[str, Any]:
    """Calculate row sizes for all schemas."""
    schemas = []

    for schema_file in schemas_dir.glob("*.json"):
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
                string_count * CONFIG['STRING_MAX_SIZE'] +
                list_count * CONFIG['LIST_MAX_SIZE'] * CONFIG['LIST_MAX_LENGTH'] +
                CONFIG['NAME_MAX_SIZE'] +
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
        "## Configuration",
        f"- STRING: {CONFIG['STRING_MAX_SIZE']} chars, LIST: {CONFIG['LIST_MAX_SIZE']} chars × {CONFIG['LIST_MAX_LENGTH']} items, name: {CONFIG['NAME_MAX_SIZE']} chars",
        f"- Limits: {CONFIG['ROW_LIMIT']:,} bytes/row, {CONFIG['ENUM_LIMIT']} values/enum",
        ""
    ])

    # Enums
    lines.append("## Enum Sizes")
    if enum_data['exceeds']:
        lines.append(f"### ❌ {len(enum_data['exceeds'])} enums exceed limit")
        for e in enum_data['exceeds'][:10]:
            lines.append(f"- {e['count']} values (exceeds by {e['count'] - CONFIG['ENUM_LIMIT']}): `{e['file']}`")
    else:
        lines.append("### ✅ All enums within limit")

    if enum_data['approaching']:
        lines.append(f"### ⚠️  {len(enum_data['approaching'])} approaching limit")
    lines.append("")

    # String lengths
    lines.extend([
        "## String Lengths",
        f"- List max: {string_data['list_max']} chars (limit: {CONFIG['LIST_MAX_SIZE']})",
        f"- String max: {string_data['string_max']} chars (limit: {CONFIG['STRING_MAX_SIZE']})",
    ])

    if string_data['list_exceeds'] or string_data['string_exceeds']:
        lines.append(f"### ⚠️  {string_data['list_exceeds'] + string_data['string_exceeds']} values exceed limits")
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
        f"- Enums: {enum_data['total']} total, {len(enum_data['exceeds'])} exceed, {len(enum_data['approaching'])} approaching",
        f"- Schemas: {len(row_data['schemas'])} total, {len(row_data['exceeds'])} exceed, {len(row_data['approaching'])} approaching",
    ])

    if enum_data['exceeds'] or row_data['exceeds']:
        lines.append("\n❌ **VALIDATION FAILED** - Critical issues found")
    elif enum_data['approaching'] or row_data['approaching']:
        lines.append("\n⚠️  **WARNINGS** - Some limits approaching")
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

    # Exit codes
    if args.strict:
        if enum_data['exceeds'] or row_data['exceeds']:
            sys.exit(1)
        elif enum_data['approaching'] or row_data['approaching']:
            sys.exit(2)

    sys.exit(0)


if __name__ == '__main__':
    main()
