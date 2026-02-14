#!/usr/bin/env python3
"""
Test materialized views with real Synapse data, saving results locally.

This script:
1. Queries syn16858331 for real data
2. Applies enrichment logic from ModelMetadataEnricher
3. Filters data according to each view type's criteria
4. Saves enriched results locally as CSV files
5. Generates summary statistics for each view

Usage:
    python scripts/test_materialized_views_local.py --output-dir test_views
"""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("Warning: pandas not installed. Install with: pip install pandas")

try:
    import synapseclient
    from synapseclient import Synapse
    SYNAPSE_AVAILABLE = True
except ImportError:
    SYNAPSE_AVAILABLE = False
    print("Warning: synapseclient not installed. Install with: pip install synapseclient")

# Import the enricher from the main script
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from create_model_materialized_views import ModelMetadataEnricher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LocalMaterializedViewTester:
    """Tests materialized view logic with real data, saving results locally."""

    def __init__(self, syn: 'synapseclient.Synapse', output_dir: str):
        """
        Initialize tester.

        Args:
            syn: Authenticated Synapse client
            output_dir: Directory to save output files
        """
        self.syn = syn
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.enricher = ModelMetadataEnricher()
        self.source_view_id = "syn16858331"

    def query_source_data(self, limit: Optional[int] = None) -> pd.DataFrame:
        """
        Query source data from syn16858331.

        Args:
            limit: Optional limit on number of rows (for testing)

        Returns:
            DataFrame with source data
        """
        logger.info(f"Querying source data from {self.source_view_id}...")

        query = f"SELECT * FROM {self.source_view_id}"
        if limit:
            query += f" LIMIT {limit}"

        results = self.syn.tableQuery(query)
        df = results.asDataFrame()

        logger.info(f"✓ Retrieved {len(df)} rows with {len(df.columns)} columns")
        return df

    def apply_enrichment(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply enrichment logic to dataframe.

        Args:
            df: Source dataframe

        Returns:
            Enriched dataframe with additional columns
        """
        logger.info("Applying enrichment logic...")

        enriched_rows = []
        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            enriched_cols = self.enricher.create_filter_columns(row_dict)

            # Merge original and enriched columns
            merged = {**row_dict, **enriched_cols}
            enriched_rows.append(merged)

        enriched_df = pd.DataFrame(enriched_rows)
        logger.info(f"✓ Enriched data with {len(enriched_df.columns)} total columns")

        return enriched_df

    def filter_for_view_type(self, df: pd.DataFrame, view_type: str) -> pd.DataFrame:
        """
        Filter data according to view type criteria.

        Args:
            df: Enriched dataframe
            view_type: One of 'clinical', 'animal_model', 'cell_line', 'organoid', 'pdx'

        Returns:
            Filtered dataframe
        """
        logger.info(f"Filtering for view type: {view_type}...")

        # Helper to safely check boolean columns
        def is_true(series):
            if series.dtype == 'bool':
                return series
            return series.astype(str).str.lower().isin(['true', '1', 'yes'])

        if view_type == "clinical":
            # Clinical: human patient data (not cell line, not xenograft, no model system)
            mask = (df['species'] == 'Homo sapiens')

            # Exclude cell lines
            if 'isCellLine' in df.columns:
                mask = mask & ~is_true(df['isCellLine'])
            elif 'specimenType' in df.columns:
                mask = mask & ~df['specimenType'].isin(['cell line', 'iPSC', 'induced pluripotent stem cell'])

            # Exclude xenografts
            if 'isXenograft' in df.columns:
                mask = mask & ~is_true(df['isXenograft'])

            # Exclude model systems
            if 'modelSystemName' in df.columns:
                mask = mask & (df['modelSystemName'].isna() | (df['modelSystemName'] == ''))

            filtered = df[mask]

        elif view_type == "animal_model":
            # Animal models: mouse, rat, zebrafish, or has modelSystemName (but not PDX or cell lines)
            mask = (
                df['species'].isin(['Mus musculus', 'Rattus norvegicus', 'Danio rerio']) |
                (df['modelSystemName'].notna() & (df['modelSystemName'] != ''))
            )

            # Exclude PDX
            if 'isXenograft' in df.columns:
                mask = mask & ~is_true(df['isXenograft'])

            # Exclude cell lines
            if 'isCellLine' in df.columns:
                mask = mask & ~is_true(df['isCellLine'])

            filtered = df[mask]

        elif view_type == "cell_line":
            # Cell lines - use isCellLine column if available
            if 'isCellLine' in df.columns:
                filtered = df[is_true(df['isCellLine'])]
            elif 'specimenType' in df.columns:
                filtered = df[
                    df['specimenType'].isin(['cell line', 'iPSC', 'induced pluripotent stem cell'])
                ]
            else:
                filtered = pd.DataFrame()

        elif view_type == "organoid":
            # Organoids and spheroids
            if 'specimenType' in df.columns:
                # Convert to string and handle NaN
                specimen_str = df['specimenType'].astype(str).str.lower()
                filtered = df[
                    specimen_str.str.contains('organoid', na=False) |
                    specimen_str.str.contains('spheroid', na=False)
                ]
            else:
                filtered = pd.DataFrame()

        elif view_type == "pdx":
            # Patient-derived xenografts - use isXenograft column if available
            if 'isXenograft' in df.columns:
                mask = is_true(df['isXenograft'])
            else:
                mask = pd.Series([False] * len(df), index=df.index)

            # Also check modelSystemName and specimenType as fallback
            if 'modelSystemName' in df.columns:
                model_str = df['modelSystemName'].astype(str).str.lower()
                mask = mask | (
                    model_str.str.contains('pdx', na=False) |
                    model_str.str.contains('xenograft', na=False)
                )

            if 'specimenType' in df.columns:
                specimen_str = df['specimenType'].astype(str).str.lower()
                mask = mask | specimen_str.str.contains('xenograft', na=False)

            filtered = df[mask]

        else:
            raise ValueError(f"Unknown view type: {view_type}")

        logger.info(f"✓ Filtered to {len(filtered)} rows for {view_type}")
        return filtered

    def generate_summary_stats(self, df: pd.DataFrame, view_type: str) -> Dict[str, Any]:
        """
        Generate summary statistics for a view.

        Args:
            df: Filtered and enriched dataframe
            view_type: View type name

        Returns:
            Dictionary of summary statistics
        """
        stats = {
            "view_type": view_type,
            "total_rows": len(df),
            "timestamp": datetime.now().isoformat(),
        }

        # Data Context distribution
        if "Data Context" in df.columns:
            stats["data_context_distribution"] = df["Data Context"].value_counts().to_dict()

        # Diagnosis distribution (top 10)
        if "Diagnosis" in df.columns:
            diagnosis_counts = df["Diagnosis"].value_counts().head(10).to_dict()
            stats["top_diagnoses"] = diagnosis_counts

        # MONDO code distribution (top 10)
        if "Diagnosis MONDO Code" in df.columns:
            mondo_counts = df["Diagnosis MONDO Code"].dropna().value_counts().head(10).to_dict()
            stats["top_mondo_codes"] = mondo_counts

        # Phenotype statistics
        if "Phenotype Count" in df.columns:
            stats["phenotype_stats"] = {
                "mean_phenotypes_per_sample": float(df["Phenotype Count"].mean()) if len(df) > 0 else 0,
                "max_phenotypes": int(df["Phenotype Count"].max()) if len(df) > 0 else 0,
                "samples_with_phenotypes": int((df["Phenotype Count"] > 0).sum()),
            }

        # Top phenotypes
        if "Phenotypes" in df.columns:
            all_phenotypes = []
            for pheno_json in df["Phenotypes"].dropna():
                try:
                    phenotypes = json.loads(pheno_json) if isinstance(pheno_json, str) else pheno_json
                    if isinstance(phenotypes, list):
                        all_phenotypes.extend(phenotypes)
                except (json.JSONDecodeError, TypeError):
                    pass

            if all_phenotypes:
                from collections import Counter
                pheno_counts = Counter(all_phenotypes)
                stats["top_phenotypes"] = dict(pheno_counts.most_common(10))

        # Age group distribution
        if "Age Group" in df.columns:
            stats["age_group_distribution"] = df["Age Group"].value_counts().to_dict()

        # Model type distribution (for non-clinical)
        if "Model Type" in df.columns:
            stats["model_type_distribution"] = df["Model Type"].value_counts().to_dict()

        # Species distribution
        if "species" in df.columns:
            stats["species_distribution"] = df["species"].value_counts().head(10).to_dict()

        return stats

    def save_view_data(self, df: pd.DataFrame, view_type: str, stats: Dict[str, Any]):
        """
        Save view data and statistics to files.

        Args:
            df: Filtered and enriched dataframe
            view_type: View type name
            stats: Summary statistics dictionary
        """
        # Save CSV
        csv_path = self.output_dir / f"{view_type}_view.csv"
        df.to_csv(csv_path, index=False)
        logger.info(f"✓ Saved CSV: {csv_path} ({len(df)} rows)")

        # Save stats as JSON
        stats_path = self.output_dir / f"{view_type}_stats.json"
        with open(stats_path, 'w') as f:
            json.dump(stats, f, indent=2)
        logger.info(f"✓ Saved stats: {stats_path}")

        # Save human-readable summary
        summary_path = self.output_dir / f"{view_type}_summary.txt"
        with open(summary_path, 'w') as f:
            f.write(f"View Type: {view_type}\n")
            f.write(f"Generated: {stats['timestamp']}\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"Total Rows: {stats['total_rows']}\n\n")

            if "data_context_distribution" in stats:
                f.write("Data Context Distribution:\n")
                for context, count in sorted(stats["data_context_distribution"].items(), key=lambda x: x[1], reverse=True):
                    f.write(f"  {context:20s}: {count:6d}\n")
                f.write("\n")

            if "top_diagnoses" in stats:
                f.write("Top 10 Diagnoses:\n")
                for diagnosis, count in list(stats["top_diagnoses"].items())[:10]:
                    f.write(f"  {count:6d}  {diagnosis}\n")
                f.write("\n")

            if "top_mondo_codes" in stats:
                f.write("Top 10 MONDO Codes:\n")
                for code, count in list(stats["top_mondo_codes"].items())[:10]:
                    f.write(f"  {count:6d}  {code}\n")
                f.write("\n")

            if "phenotype_stats" in stats:
                f.write("Phenotype Statistics:\n")
                for key, value in stats["phenotype_stats"].items():
                    f.write(f"  {key}: {value}\n")
                f.write("\n")

            if "top_phenotypes" in stats:
                f.write("Top 10 Phenotypes:\n")
                for pheno, count in list(stats["top_phenotypes"].items())[:10]:
                    f.write(f"  {count:6d}  {pheno}\n")
                f.write("\n")

            if "age_group_distribution" in stats:
                f.write("Age Group Distribution:\n")
                for age_group, count in sorted(stats["age_group_distribution"].items(), key=lambda x: x[1], reverse=True):
                    f.write(f"  {age_group:20s}: {count:6d}\n")
                f.write("\n")

            if "model_type_distribution" in stats:
                f.write("Model Type Distribution:\n")
                for model_type, count in sorted(stats["model_type_distribution"].items(), key=lambda x: x[1], reverse=True):
                    f.write(f"  {model_type:20s}: {count:6d}\n")
                f.write("\n")

            if "species_distribution" in stats:
                f.write("Top 10 Species:\n")
                for species, count in list(stats["species_distribution"].items())[:10]:
                    f.write(f"  {count:6d}  {species}\n")
                f.write("\n")

        logger.info(f"✓ Saved summary: {summary_path}")

    def test_all_views(self, limit: Optional[int] = None):
        """
        Test all view types with real data.

        Args:
            limit: Optional limit on source data rows (for quick testing)
        """
        logger.info("=" * 80)
        logger.info("Testing All Materialized Views with Real Data")
        logger.info("=" * 80)
        logger.info("")

        # Query source data
        source_df = self.query_source_data(limit=limit)
        logger.info("")

        # Apply enrichment
        enriched_df = self.apply_enrichment(source_df)
        logger.info("")

        # Test each view type
        view_types = ["clinical", "animal_model", "cell_line", "organoid", "pdx"]
        all_stats = {}

        for view_type in view_types:
            logger.info("=" * 80)
            logger.info(f"Processing: {view_type.upper()}")
            logger.info("=" * 80)

            # Filter for view type
            filtered_df = self.filter_for_view_type(enriched_df, view_type)

            if len(filtered_df) == 0:
                logger.warning(f"⚠ No data found for {view_type} view")
                logger.info("")
                continue

            # Generate statistics
            stats = self.generate_summary_stats(filtered_df, view_type)
            all_stats[view_type] = stats

            # Save results
            self.save_view_data(filtered_df, view_type, stats)
            logger.info("")

        # Save combined stats
        combined_stats_path = self.output_dir / "all_views_summary.json"
        with open(combined_stats_path, 'w') as f:
            json.dump(all_stats, f, indent=2)
        logger.info(f"✓ Saved combined summary: {combined_stats_path}")

        # Print final summary
        logger.info("")
        logger.info("=" * 80)
        logger.info("SUMMARY OF ALL VIEWS")
        logger.info("=" * 80)
        for view_type, stats in all_stats.items():
            logger.info(f"{view_type:20s}: {stats['total_rows']:6d} rows")
        logger.info("=" * 80)
        logger.info(f"✓ All results saved to: {self.output_dir}")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Test materialized views with real Synapse data, saving results locally"
    )
    parser.add_argument(
        "--output-dir",
        default="test_views",
        help="Directory to save output files (default: test_views)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of rows from source (for quick testing)"
    )

    args = parser.parse_args()

    if not SYNAPSE_AVAILABLE:
        logger.error("synapseclient not available. Install with: pip install synapseclient")
        return 1

    if not PANDAS_AVAILABLE:
        logger.error("pandas not available. Install with: pip install pandas")
        return 1

    # Authenticate to Synapse
    logger.info("Authenticating to Synapse...")
    syn = Synapse()
    try:
        syn.login(silent=True)
        logger.info(f"✓ Authenticated as: {syn.getUserProfile()['userName']}")
        logger.info("")
    except Exception as e:
        logger.error(f"Synapse authentication failed: {e}")
        logger.error("Please run: synapse login")
        return 1

    # Run tests
    tester = LocalMaterializedViewTester(syn, args.output_dir)
    tester.test_all_views(limit=args.limit)

    return 0


if __name__ == "__main__":
    exit(main())
