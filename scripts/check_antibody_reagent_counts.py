#!/usr/bin/env python3
"""
Check how many Antibody and Genetic Reagent resources are in syn51730943.

Usage:
    python scripts/check_antibody_reagent_counts.py
"""

import synapseclient
import pandas as pd

# Connect to Synapse (anonymous)
syn = synapseclient.Synapse()
print("✓ Connected to Synapse (anonymous)\n")

table_id = 'syn51730943'

# Query for Antibodies
print("Querying for Antibodies...")
query = f"SELECT * FROM {table_id} WHERE resourceType = 'Antibody'"
results = syn.tableQuery(query)
antibody_df = results.asDataFrame()
print(f"  → Found {len(antibody_df)} Antibody resources\n")

if len(antibody_df) > 0:
    print("Sample Antibodies:")
    for i, row in antibody_df.head(10).iterrows():
        print(f"  - {row['resourceName']}")
    if len(antibody_df) > 10:
        print(f"  ... and {len(antibody_df) - 10} more")
    print()

# Query for Genetic Reagents
print("Querying for Genetic Reagents...")
query = f"SELECT * FROM {table_id} WHERE resourceType = 'Genetic Reagent'"
results = syn.tableQuery(query)
reagent_df = results.asDataFrame()
print(f"  → Found {len(reagent_df)} Genetic Reagent resources\n")

if len(reagent_df) > 0:
    print("Sample Genetic Reagents:")
    for i, row in reagent_df.head(10).iterrows():
        print(f"  - {row['resourceName']}")
    if len(reagent_df) > 10:
        print(f"  ... and {len(reagent_df) - 10} more")
    print()

# Summary
print("=" * 70)
print(f"Total resources that could have enums with see_also links:")
print(f"  - Cell Lines: 638 (already done)")
print(f"  - Animal Models: 123 (already done)")
print(f"  - Antibodies: {len(antibody_df)}")
print(f"  - Genetic Reagents: {len(reagent_df)}")
print(f"  - TOTAL NEW: {len(antibody_df) + len(reagent_df)}")
print("=" * 70)
