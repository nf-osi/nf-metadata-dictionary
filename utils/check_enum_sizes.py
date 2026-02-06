#!/usr/bin/env python3
"""
Check enum sizes and warn about Synapse API limits.

Synapse has a limit of 100 enum values per annotation field.
This script checks all enums and reports those approaching or exceeding this limit.
"""

import yaml
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Synapse API limit for annotation enum values
SYNAPSE_LIMIT = 100
WARNING_THRESHOLD = 80  # Warn when approaching limit

def load_enum_counts(modules_dir: Path) -> Dict[str, Tuple[str, int]]:
    """
    Load all enums from modules and count their values.

    Returns:
        Dictionary mapping enum_name to (file_path, value_count)
    """
    enum_counts = {}

    for yaml_file in modules_dir.rglob("*.yaml"):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)

            if not data or 'enums' not in data:
                continue

            for enum_name, enum_data in data['enums'].items():
                if 'permissible_values' in enum_data:
                    count = len(enum_data['permissible_values'])
                    enum_counts[enum_name] = (str(yaml_file.relative_to(modules_dir.parent)), count)

        except Exception as e:
            print(f"Warning: Error loading {yaml_file}: {e}", file=sys.stderr)

    return enum_counts

def check_enum_sizes(modules_dir: str = "modules") -> Tuple[List[dict], List[dict], List[dict]]:
    """
    Check all enum sizes and categorize them.

    Returns:
        Tuple of (exceeds_limit, approaching_limit, safe_enums)
    """
    modules_path = Path(modules_dir)

    if not modules_path.exists():
        print(f"Error: Modules directory {modules_dir} not found", file=sys.stderr)
        sys.exit(1)

    enum_counts = load_enum_counts(modules_path)

    exceeds_limit = []
    approaching_limit = []
    safe_enums = []

    for enum_name, (file_path, count) in enum_counts.items():
        enum_info = {
            'name': enum_name,
            'file': file_path,
            'count': count,
            'remaining': SYNAPSE_LIMIT - count
        }

        if count > SYNAPSE_LIMIT:
            exceeds_limit.append(enum_info)
        elif count >= WARNING_THRESHOLD:
            approaching_limit.append(enum_info)
        else:
            safe_enums.append(enum_info)

    return exceeds_limit, approaching_limit, safe_enums

def format_report(exceeds_limit: List[dict], approaching_limit: List[dict],
                 safe_enums: List[dict], verbose: bool = False) -> str:
    """Format a report of enum sizes."""
    lines = []

    lines.append("# Enum Size Report - Synapse API Limits")
    lines.append("")
    lines.append(f"**Synapse Limit:** {SYNAPSE_LIMIT} values per enum field")
    lines.append(f"**Warning Threshold:** {WARNING_THRESHOLD} values")
    lines.append("")

    if exceeds_limit:
        lines.append(f"## ⚠️ EXCEEDS LIMIT ({len(exceeds_limit)} enums)")
        lines.append("")
        lines.append("These enums exceed Synapse's 100-value limit and may cause API errors:")
        lines.append("")

        # Sort by count descending
        for enum_info in sorted(exceeds_limit, key=lambda x: x['count'], reverse=True):
            lines.append(f"- **{enum_info['name']}** ({enum_info['file']})")
            lines.append(f"  - Current: {enum_info['count']} values")
            lines.append(f"  - Exceeds by: {enum_info['count'] - SYNAPSE_LIMIT} values")
            lines.append("")
    else:
        lines.append("## ✅ No Enums Exceed Limit")
        lines.append("")

    if approaching_limit:
        lines.append(f"## ⚠️ Approaching Limit ({len(approaching_limit)} enums)")
        lines.append("")
        lines.append(f"These enums have {WARNING_THRESHOLD}+ values and should be monitored:")
        lines.append("")

        for enum_info in sorted(approaching_limit, key=lambda x: x['count'], reverse=True):
            lines.append(f"- **{enum_info['name']}** ({enum_info['file']})")
            lines.append(f"  - Current: {enum_info['count']} values")
            lines.append(f"  - Remaining before limit: {enum_info['remaining']} values")
            lines.append("")

    if verbose and safe_enums:
        lines.append(f"## ✅ Safe Enums ({len(safe_enums)} enums)")
        lines.append("")
        lines.append(f"These enums are well below the limit (< {WARNING_THRESHOLD} values)")
        lines.append("")

    # Summary
    total = len(exceeds_limit) + len(approaching_limit) + len(safe_enums)
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total enums:** {total}")
    lines.append(f"- **Exceeds limit:** {len(exceeds_limit)}")
    lines.append(f"- **Approaching limit:** {len(approaching_limit)}")
    lines.append(f"- **Safe:** {len(safe_enums)}")

    return '\n'.join(lines)

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Check enum sizes against Synapse API limits'
    )
    parser.add_argument(
        '--modules-dir',
        default='modules',
        help='Path to modules directory (default: modules)'
    )
    parser.add_argument(
        '--output',
        help='Output file for report (default: print to stdout)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Include safe enums in report'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Use strict exit codes for CI: 0=pass, 1=exceed limit (fail), 2=approaching (warning)'
    )
    parser.add_argument(
        '--format',
        choices=['markdown', 'json', 'text'],
        default='markdown',
        help='Output format (default: markdown)'
    )

    args = parser.parse_args()

    # Check enum sizes
    exceeds_limit, approaching_limit, safe_enums = check_enum_sizes(args.modules_dir)

    # Format report
    if args.format == 'markdown':
        report = format_report(exceeds_limit, approaching_limit, safe_enums, args.verbose)
    elif args.format == 'json':
        import json
        report = json.dumps({
            'exceeds_limit': exceeds_limit,
            'approaching_limit': approaching_limit,
            'safe_enums': safe_enums if args.verbose else [],
            'summary': {
                'total': len(exceeds_limit) + len(approaching_limit) + len(safe_enums),
                'exceeds': len(exceeds_limit),
                'approaching': len(approaching_limit),
                'safe': len(safe_enums)
            }
        }, indent=2)
    else:  # text
        lines = []
        if exceeds_limit:
            lines.append(f"⚠️  {len(exceeds_limit)} enum(s) exceed Synapse limit:")
            for e in exceeds_limit:
                lines.append(f"  - {e['name']}: {e['count']} values")
        if approaching_limit:
            lines.append(f"⚠️  {len(approaching_limit)} enum(s) approaching limit:")
            for e in approaching_limit:
                lines.append(f"  - {e['name']}: {e['count']} values")
        if not exceeds_limit and not approaching_limit:
            lines.append("✅ All enums within safe limits")
        report = '\n'.join(lines)

    # Output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)

    # Exit codes for CI integration (when --strict is used)
    # 0 = all checks passed (no enums exceed or approach limit)
    # 1 = enums exceed limit (should fail PR)
    # 2 = enums approaching limit (warning only, don't fail PR)
    if args.strict:
        if exceeds_limit:
            print(f"\n❌ ERROR: {len(exceeds_limit)} enum(s) exceed Synapse 100-value limit")
            sys.exit(1)
        elif approaching_limit:
            print(f"\n⚠️  WARNING: {len(approaching_limit)} enum(s) approaching limit (80+ values)")
            sys.exit(2)
        else:
            print("\n✅ All enum sizes within safe limits")
            sys.exit(0)
    else:
        # Default behavior: exit 0 unless exceeds limit
        sys.exit(1 if exceeds_limit else 0)

if __name__ == '__main__':
    main()
