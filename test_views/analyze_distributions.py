#!/usr/bin/env python3
"""
Analyze value distributions and coverage for all materialized view CSVs.

For each view and each facet field, reports:
  - Total rows, filled rows, blank/NA rows (coverage)
  - Value distribution (count per value, descending)
  - Unmapped raw values (values in source columns that didn't resolve to an enriched field)

Usage:
    python test_views/analyze_distributions.py
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ── field configs per view ──────────────────────────────────────────────────
# Each entry: (column_name, known_values_or_None)
# known_values used to flag values that are off-enum (possible typos/synonyms).

NF1_GENOTYPE_VALS = {"+/+", "+/-", "-/-", "unknown", "Unknown"}
NF2_GENOTYPE_VALS = {"+/+", "+/-", "-/-", "unknown", "Unknown"}

VIEW_FIELDS = {
    "clinical": [
        # enriched
        ("Diagnosis",           None),
        ("Diagnosis MONDO Code",None),
        ("Has Treatment",       {"True", "False"}),
        ("Age Group",           {"infant", "child", "adolescent", "adult"}),
        ("Phenotypes",          None),       # JSON list – will unpack
        ("Phenotype Count",     None),
        # base annotations – key clinical facets
        ("diagnosis",           None),
        ("tumorType",           None),
        ("sex",                 {"Male", "Female", "male", "female", "Unknown", "unknown"}),
        ("species",             None),
        ("vitalStatus",         {"alive", "deceased", "unknown", "Unknown"}),
        ("nf1Genotype",         NF1_GENOTYPE_VALS),
        ("nf2Genotype",         NF2_GENOTYPE_VALS),
        ("nf2Genotype",         NF2_GENOTYPE_VALS),
        ("dataType",            None),
        ("assay",               None),
    ],
    "animal_model": [
        ("NF Type",             None),
        ("Diagnosis",           None),
        ("Model Type",          {"mouse", "rat", "zebrafish", "drosophila", "other"}),
        ("Has Treatment",       {"True", "False"}),
        # base
        ("diagnosis",           None),
        ("species",             None),
        ("modelSystemName",     None),
        ("nf1Genotype",         NF1_GENOTYPE_VALS),
        ("nf2Genotype",         NF2_GENOTYPE_VALS),
        ("genePerturbed",       None),
        ("genePerturbationType",None),
        ("tissue",              None),
        ("tumorType",           None),
        ("dataType",            None),
        ("assay",               None),
    ],
    "cell_line": [
        ("NF Type",             None),
        ("Diagnosis",           None),
        ("Tissue of Origin",    None),
        ("Has Treatment",       {"True", "False"}),
        # base
        ("diagnosis",           None),
        ("tumorType",           None),
        ("tissue",              None),
        ("sex",                 {"Male", "Female", "male", "female", "Unknown", "unknown"}),
        ("cellType",            None),
        ("nf1Genotype",         NF1_GENOTYPE_VALS),
        ("nf2Genotype",         NF2_GENOTYPE_VALS),
        ("individualID",        None),
        ("dataType",            None),
        ("assay",               None),
    ],
    "pdx": [
        ("NF Type",             None),
        ("Diagnosis",           None),
        ("Has Treatment",       {"True", "False"}),
        # base
        ("diagnosis",           None),
        ("tumorType",           None),
        ("transplantationType", None),
        ("modelSystemName",     None),
        ("species",             None),
        ("dataType",            None),
        ("assay",               None),
    ],
    "organoid": [
        ("NF Type",             None),
        ("Diagnosis",           None),
        ("Has Treatment",       {"True", "False"}),
        # base
        ("diagnosis",           None),
        ("tumorType",           None),
        ("tissue",              None),
        ("modelSystemName",     None),
        ("species",             None),
        ("dataType",            None),
        ("assay",               None),
    ],
}

BLANK = {"", "nan", "none", "NaN", "None", "NA", "N/A", "n/a", "[]", "['']"}


def is_blank(v):
    return v is None or str(v).strip() in BLANK


def read_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def unpack_list_field(val):
    """Try to parse JSON/Python-list strings into individual values."""
    v = str(val).strip()
    if v.startswith("["):
        try:
            parsed = json.loads(v.replace("'", '"'))
            return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            # Fallback: strip brackets and split on commas
            inner = v.strip("[]")
            parts = [p.strip().strip("'\"") for p in inner.split(",")]
            return [p for p in parts if p]
    return [v] if v else []


def analyze_field(rows, col, known_vals=None, max_values=30):
    total = len(rows)
    col_exists = any(col in r for r in rows[:10])
    if not col_exists:
        return None

    counter = Counter()
    blank_count = 0
    is_list_field = col in ("Phenotypes", "tumorType", "diagnosis")

    for row in rows:
        raw = row.get(col, "")
        if is_blank(raw):
            blank_count += 1
            continue
        if is_list_field:
            vals = unpack_list_field(raw)
            if not vals:
                blank_count += 1
            else:
                for v in vals:
                    counter[v] += 1
        else:
            counter[str(raw).strip()] += 1

    filled = total - blank_count
    pct_filled = 100.0 * filled / total if total else 0

    # Detect off-enum values
    off_enum = {}
    if known_vals:
        for v, c in counter.items():
            if v not in known_vals:
                off_enum[v] = c

    return {
        "total": total,
        "filled": filled,
        "blank": blank_count,
        "pct_filled": pct_filled,
        "unique_values": len(counter),
        "distribution": counter.most_common(max_values),
        "off_enum": sorted(off_enum.items(), key=lambda x: -x[1]) if off_enum else None,
    }


def print_field_report(col, result, show_off_enum=True):
    if result is None:
        print(f"  [{col}] — column not found in this CSV")
        return

    pct = result["pct_filled"]
    coverage_flag = "✓" if pct >= 80 else ("~" if pct >= 30 else "✗")
    print(f"\n  {coverage_flag} {col}")
    print(f"    Coverage: {result['filled']:,}/{result['total']:,} filled ({pct:.1f}%),  "
          f"{result['blank']:,} blank,  {result['unique_values']} unique values")

    if result["distribution"]:
        lines = []
        for val, cnt in result["distribution"]:
            lines.append(f"      {cnt:6,}  {val!r}")
        print("    Distribution (top):")
        print("\n".join(lines))

    if show_off_enum and result["off_enum"]:
        print(f"    ⚠  Off-enum / unmapped values ({len(result['off_enum'])}):")
        for val, cnt in result["off_enum"][:15]:
            print(f"      {cnt:6,}  {val!r}")


def analyze_raw_diagnosis_vs_enriched(rows, view_type):
    """Cross-check raw `diagnosis` values against enriched `Diagnosis` column to find unmapped entries."""
    raw_counts = Counter()
    enriched_miss = Counter()  # raw values that didn't get an enriched Diagnosis

    for row in rows:
        raw = row.get("diagnosis", "")
        enr = row.get("Diagnosis", "")
        if is_blank(raw):
            continue
        for v in unpack_list_field(raw):
            raw_counts[v] += 1
            if is_blank(enr):
                enriched_miss[v] += 1

    return raw_counts, enriched_miss


def analyze_raw_tumor_vs_phenotypes(rows):
    """Find tumorType values that produced no HPO/NCIT mapping."""
    unmapped = Counter()
    for row in rows:
        raw = row.get("tumorType", "")
        hpo = row.get("Phenotypes", "")
        ncit = row.get("Tumor Type NCIT Codes", "")
        if is_blank(raw):
            continue
        for v in unpack_list_field(raw):
            if is_blank(hpo) and is_blank(ncit):
                unmapped[v] += 1
    return unmapped


def main():
    base = Path(__file__).parent

    views = ["clinical", "animal_model", "cell_line", "pdx", "organoid"]

    print("=" * 90)
    print("MATERIALIZED VIEW DISTRIBUTION ANALYSIS")
    print("=" * 90)

    for view_type in views:
        csv_path = base / f"{view_type}_view.csv"
        if not csv_path.exists():
            print(f"\n[{view_type.upper()}] — CSV not found: {csv_path}")
            continue

        rows = read_csv(csv_path)
        print(f"\n{'=' * 90}")
        print(f"VIEW: {view_type.upper()}   ({len(rows):,} rows)   [{csv_path.name}]")
        print("=" * 90)

        fields = VIEW_FIELDS.get(view_type, [])
        # Deduplicate field list (same col may appear twice with different known_vals)
        seen_cols = set()
        for col, known_vals in fields:
            if col in seen_cols:
                continue
            seen_cols.add(col)
            result = analyze_field(rows, col, known_vals)
            print_field_report(col, result, show_off_enum=True)

        # Cross-checks
        if rows:
            print(f"\n  ── Cross-check: raw `diagnosis` → enriched `Diagnosis` mapping ──")
            raw_dx, miss_dx = analyze_raw_diagnosis_vs_enriched(rows, view_type)
            if miss_dx:
                print(f"  Raw diagnosis values NOT resolved to enriched Diagnosis ({len(miss_dx)} distinct):")
                for v, c in miss_dx.most_common(20):
                    print(f"    {c:6,}  {v!r}")
            else:
                print("  All raw diagnosis values resolved to enriched Diagnosis ✓")

            if view_type == "clinical":
                print(f"\n  ── Cross-check: `tumorType` → HPO/NCIT mapping coverage ──")
                unmapped_tt = analyze_raw_tumor_vs_phenotypes(rows)
                if unmapped_tt:
                    print(f"  tumorType values with NO HPO or NCIT mapping ({len(unmapped_tt)} distinct):")
                    for v, c in unmapped_tt.most_common(30):
                        print(f"    {c:6,}  {v!r}")
                else:
                    print("  All tumorType values have at least one HPO/NCIT mapping ✓")

    print(f"\n{'=' * 90}")
    print("DONE")
    print("=" * 90)


if __name__ == "__main__":
    main()
