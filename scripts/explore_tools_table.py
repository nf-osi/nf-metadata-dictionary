#!/usr/bin/env python3
"""
Explore syn51730943 table structure to find the resourceId column.

Usage:
    export SYNAPSE_AUTH_TOKEN=your_token
    python scripts/explore_tools_table.py
"""

import synapseclient
import pandas as pd
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def main():
    # Connect to Synapse
    auth_token = os.getenv('SYNAPSE_AUTH_TOKEN')

    syn = synapseclient.Synapse()

    if auth_token:
        syn.login(authToken=auth_token, silent=True)
        logger.info("✓ Connected to Synapse (authenticated)\n")
    else:
        logger.info("⚠ No SYNAPSE_AUTH_TOKEN - attempting anonymous access")
        logger.info("✓ Connected to Synapse (anonymous)\n")

    # Query table
    table_id = 'syn51730943'
    query = f"SELECT * FROM {table_id} LIMIT 5"

    logger.info(f"Querying {table_id}...")
    results = syn.tableQuery(query)
    df = results.asDataFrame()

    # Display table structure
    logger.info(f"\n{'=' * 70}")
    logger.info(f"Table: {table_id}")
    logger.info(f"Rows: {len(df)}")
    logger.info(f"Columns: {len(df.columns)}")
    logger.info(f"{'=' * 70}\n")

    logger.info("Column Names:")
    for col in df.columns:
        logger.info(f"  - {col}")

    logger.info(f"\n{'=' * 70}")
    logger.info("Sample Data (first 3 rows):")
    logger.info(f"{'=' * 70}\n")

    # Show first few rows with key columns
    key_cols = ['toolName', 'toolType']
    # Add columns that might contain resource ID
    potential_id_cols = [c for c in df.columns if any(x in c.lower() for x in ['id', 'resource', 'uuid', 'row'])]
    display_cols = key_cols + potential_id_cols

    # Filter to only existing columns
    display_cols = [c for c in display_cols if c in df.columns]

    logger.info(df[display_cols].head(3).to_string())

    logger.info(f"\n{'=' * 70}")
    logger.info("Looking for resource ID columns...")
    logger.info(f"{'=' * 70}\n")

    for col in potential_id_cols:
        if col in df.columns:
            logger.info(f"{col}:")
            logger.info(f"  Type: {df[col].dtype}")
            logger.info(f"  Sample values:")
            for val in df[col].head(3):
                logger.info(f"    - {val}")
            logger.info("")

    # Query specific cell line to match the example
    logger.info(f"{'=' * 70}")
    logger.info("Looking for JH-2-002 example...")
    logger.info(f"{'=' * 70}\n")

    query = f"SELECT * FROM {table_id} WHERE toolName = 'JH-2-002'"
    try:
        results = syn.tableQuery(query)
        df = results.asDataFrame()

        if not df.empty:
            logger.info("Found JH-2-002:")
            logger.info(f"  toolType: {df.iloc[0]['toolType'] if 'toolType' in df.columns else 'N/A'}")
            for col in potential_id_cols:
                if col in df.columns:
                    logger.info(f"  {col}: {df.iloc[0][col]}")
            logger.info("")
            logger.info("Expected URL format:")
            logger.info("  https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=1bc84ef2-208f-4f0e-8045-6be47fd968de")
        else:
            logger.info("JH-2-002 not found in table")
    except Exception as e:
        logger.error(f"Error querying JH-2-002: {e}")


if __name__ == '__main__':
    main()
