#!/usr/bin/env python3
"""
Sample the Tools materialized view and per-resource-type source tables to discover
available columns and representative values for facet design.

Outputs a markdown report showing:
  - All columns in syn51730943 (Tools materialized view)
  - All columns in each per-resource source table
  - Sample values per column (top 10 most frequent, or first 10 for low-cardinality)
  - Column coverage (% non-null) to identify useful facet candidates

Source tables (more columns than the materialized view):
  Animal Model:    syn26486808
  Antibody:        syn26486811
  Cell Line:       syn26486823
  Genetic Reagent: syn26486832
  Biobank:         syn26486821

Usage:
    python scripts/sample_tools_schema.py
    python scripts/sample_tools_schema.py --output docs/tools_schema_sample.md
    python scripts/sample_tools_schema.py --table syn26486811  # single table only

All tables are open-access; no Synapse login required.
"""

import os
import sys
import argparse
import logging
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

SOURCE_TABLES = {
    'Animal Model':    'syn26486808',
    'Antibody':        'syn26486811',
    'Cell Line':       'syn26486823',
    'Genetic Reagent': 'syn26486832',
    'Biobank':         'syn26486821',
}

MATERIALIZED_VIEW = 'syn51730943'

SAMPLE_VALUES = 10   # number of top values to show per column
MAX_VALUE_LEN = 60   # truncate long strings in output


def synapse_client():
    import synapseclient
    syn = synapseclient.Synapse()
    token = os.getenv('SYNAPSE_AUTH_TOKEN')
    if token:
        syn.login(authToken=token, silent=True)
    # No login call for anonymous access — public tables work without authentication
    return syn


def get_columns(syn, table_id: str) -> List[str]:
    """Return column names for a Synapse table/view."""
    cols = syn.getTableColumns(table_id)
    return [c.name for c in cols]


def sample_table(syn, table_id: str, resource_type: Optional[str] = None,
                 limit: int = 500) -> 'pd.DataFrame':
    import pandas as pd
    where = f"WHERE resourceType = '{resource_type}'" if resource_type else ""
    query = f"SELECT * FROM {table_id} {where} LIMIT {limit}"
    logger.info(f"  Querying: {query}")
    results = syn.tableQuery(query)
    df = results.asDataFrame()
    return df


def column_summary(df: 'pd.DataFrame', col: str) -> Dict[str, Any]:
    """Return coverage % and top sample values for a column."""
    import pandas as pd
    series = df[col].dropna()
    # Flatten list-type cells (Synapse can return lists for multi-value columns)
    flat = []
    for v in series:
        if isinstance(v, list):
            flat.extend([str(x) for x in v if x is not None])
        else:
            s = str(v).strip()
            if s and s.lower() not in ('nan', 'none', ''):
                flat.append(s)

    total = len(df)
    coverage = round(len(series) / total * 100, 1) if total > 0 else 0.0
    counts: Dict[str, int] = {}
    for v in flat:
        counts[v] = counts.get(v, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:SAMPLE_VALUES]
    samples = [f"{v[:MAX_VALUE_LEN]!r} ({n})" for v, n in top]
    return {'coverage': coverage, 'unique': len(counts), 'samples': samples}


def render_table_section(title: str, syn_id: str, df: 'pd.DataFrame') -> str:
    lines = [
        f"## {title} (`{syn_id}`)",
        f"",
        f"Rows sampled: {len(df)}",
        f"",
        f"| Column | Coverage % | Unique vals | Top values |",
        f"|--------|-----------|-------------|------------|",
    ]
    for col in df.columns:
        s = column_summary(df, col)
        samples_str = ', '.join(s['samples'][:5]) if s['samples'] else '—'
        lines.append(
            f"| `{col}` | {s['coverage']}% | {s['unique']} | {samples_str} |"
        )
    lines.append("")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Sample Tools schema for facet design')
    parser.add_argument('--output', help='Write markdown report to this file (default: stdout)')
    parser.add_argument('--table', help='Only sample this Synapse ID (skip others)')
    parser.add_argument('--limit', type=int, default=500,
                        help='Max rows to sample per table (default: 500)')
    args = parser.parse_args()

    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas required: pip install pandas")
        sys.exit(1)

    logger.info("Connecting to Synapse...")
    syn = synapse_client()

    sections = [
        "# Tools Schema Sample Report",
        "",
        "Columns and representative values sampled from the Tools materialized view and",
        "per-resource-type source tables, for use in designing OpenSearch facet structure.",
        "",
    ]

    # --- Materialized view ---
    if not args.table or args.table == MATERIALIZED_VIEW:
        logger.info(f"Sampling materialized view {MATERIALIZED_VIEW}...")
        try:
            df_mv = sample_table(syn, MATERIALIZED_VIEW, limit=args.limit)
            sections.append(render_table_section(
                "Tools Materialized View (syn51730943)", MATERIALIZED_VIEW, df_mv
            ))
            # Also break down by resourceType within the MV
            if 'resourceType' in df_mv.columns:
                for rt in df_mv['resourceType'].dropna().unique():
                    df_rt = df_mv[df_mv['resourceType'] == rt]
                    sections.append(render_table_section(
                        f"Tools MV — {rt} subset", MATERIALIZED_VIEW, df_rt
                    ))
        except Exception as e:
            logger.warning(f"Could not sample {MATERIALIZED_VIEW}: {e}")
            sections.append(f"## Tools Materialized View\n\n⚠ Could not sample: {e}\n")

    # --- Per-resource source tables ---
    for resource_name, table_id in SOURCE_TABLES.items():
        if args.table and args.table != table_id:
            continue
        logger.info(f"Sampling {resource_name} source table {table_id}...")
        try:
            df = sample_table(syn, table_id, limit=args.limit)
            sections.append(render_table_section(
                f"{resource_name} Source Table", table_id, df
            ))
        except Exception as e:
            logger.warning(f"Could not sample {table_id}: {e}")
            sections.append(f"## {resource_name} Source Table (`{table_id}`)\n\n⚠ Could not sample: {e}\n")

    report = '\n'.join(sections)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        logger.info(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == '__main__':
    main()
