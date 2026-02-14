#!/usr/bin/env python3
"""
Query Synapse data and verify ontology mappings using local repositories.

This script:
1. Queries syn16858331 for unique diagnosis and phenotype values
2. Searches local HPO repository (ontology-service) for phenotype codes
3. Searches local MONDO repository for diagnosis codes
4. Reports matches, near matches, and missing codes
"""

import json
import os
import re
import subprocess
from collections import Counter
from typing import Dict, List, Tuple, Optional

try:
    import synapseclient
    from synapseclient import Synapse
    SYNAPSE_AVAILABLE = True
except ImportError:
    SYNAPSE_AVAILABLE = False
    print("WARNING: synapseclient not available. Install with: pip install synapseclient")

# Paths to local ontology repositories
HPO_REPO = os.path.expanduser("~/Documents/GitHub/ontology-service")
MONDO_REPO = os.path.expanduser("~/Documents/GitHub/mondo")


def query_synapse_diagnoses(syn: Synapse, view_id: str = "syn16858331") -> Dict[str, int]:
    """Query Synapse for unique diagnosis values and their counts."""
    print(f"\n{'='*80}")
    print(f"Querying {view_id} for diagnosis values...")
    print(f"{'='*80}\n")

    query = f"SELECT diagnosis FROM {view_id} WHERE diagnosis IS NOT NULL"
    results = syn.tableQuery(query)

    diagnoses = []
    df = results.asDataFrame()

    for val in df['diagnosis']:
        if val and str(val) not in ['nan', 'None', '']:
            diagnoses.append(str(val))

    diagnosis_counts = Counter(diagnoses)

    print(f"Found {len(diagnosis_counts)} unique diagnosis values:")
    for diagnosis, count in diagnosis_counts.most_common():
        print(f"  {count:4d}x  {diagnosis}")

    return dict(diagnosis_counts)


def query_synapse_phenotypes(syn: Synapse, view_id: str = "syn16858331") -> Dict[str, Dict[str, int]]:
    """Query Synapse for phenotype field values."""
    print(f"\n{'='*80}")
    print(f"Querying {view_id} for phenotype field values...")
    print(f"{'='*80}\n")

    # Key clinical phenotype fields to check
    phenotype_fields = [
        "cafeaulaitMacules",
        "skinFoldFreckling",
        "IrisLischNodules",
        "plexiformNeurofibromas",
        "dermalNeurofibromas",
        "subcutaneousNodularNeurofibromas",
        "diffuseDermalNeurofibromas",
        "spinalNeurofibromas",
        "opticGlioma",
        "nonopticGlioma",
        "learningDisability",
        "intellectualDisability",
        "attentionDeficitDisorder",
        "scoliosis",
        "vestibularSchwannoma",
        "meningioma",
        "pheochromocytoma",
        "glomusTumor",
        "GIST",
        "leukemia",
        "breastCancer",
        "spinalSchwannoma",
        "dermalSchwannoma",
    ]

    phenotype_data = {}

    for field in phenotype_fields:
        try:
            query = f"SELECT {field} FROM {view_id} WHERE {field} IS NOT NULL"
            results = syn.tableQuery(query)

            df = results.asDataFrame()
            values = []
            for val in df[field]:
                if val and str(val) not in ['nan', 'None', '']:
                    values.append(str(val))

            if values:
                value_counts = Counter(values)
                phenotype_data[field] = dict(value_counts)

                # Only print fields with non-absent values
                has_present = any(v not in ["absent", "Unknown", "unknown", ""] for v in value_counts.keys())
                if has_present:
                    print(f"\n{field}:")
                    for value, count in value_counts.most_common():
                        if value not in ["absent", "Unknown", "unknown", ""]:
                            print(f"  {count:4d}x  {value}")
        except Exception as e:
            print(f"  Error querying {field}: {e}")

    return phenotype_data


def search_hpo_code(term: str, hpo_repo: str) -> List[Tuple[str, str, float]]:
    """
    Search for HPO code using local ontology-service repository.

    Returns list of (code, label, similarity_score) tuples.
    """
    if not os.path.exists(hpo_repo):
        print(f"WARNING: HPO repository not found at {hpo_repo}")
        return []

    # Try searching hp.json if it exists
    hp_json = os.path.join(hpo_repo, "src", "main", "resources", "hp.json")
    if not os.path.exists(hp_json):
        # Try alternate locations
        for possible_path in [
            os.path.join(hpo_repo, "hp.json"),
            os.path.join(hpo_repo, "data", "hp.json"),
        ]:
            if os.path.exists(possible_path):
                hp_json = possible_path
                break

    if not os.path.exists(hp_json):
        print(f"WARNING: hp.json not found in {hpo_repo}")
        return []

    try:
        with open(hp_json, 'r') as f:
            hpo_data = json.load(f)

        matches = []
        term_lower = term.lower()

        # Search through HPO terms
        for node in hpo_data.get('graphs', [{}])[0].get('nodes', []):
            if node.get('type') == 'CLASS':
                hpo_id = node.get('id', '')
                if 'HP:' in hpo_id:
                    label = node.get('lbl', '')

                    # Exact match
                    if label.lower() == term_lower:
                        matches.append((hpo_id.split('/')[-1], label, 1.0))
                    # Partial match
                    elif term_lower in label.lower() or label.lower() in term_lower:
                        similarity = len(term_lower) / max(len(label), len(term))
                        matches.append((hpo_id.split('/')[-1], label, similarity))

        # Sort by similarity
        matches.sort(key=lambda x: x[2], reverse=True)
        return matches[:5]  # Top 5 matches

    except Exception as e:
        print(f"ERROR searching HPO for '{term}': {e}")
        return []


def search_mondo_code(term: str, mondo_repo: str) -> List[Tuple[str, str, float]]:
    """
    Search for MONDO code using local mondo repository.

    Returns list of (code, label, similarity_score) tuples.
    """
    if not os.path.exists(mondo_repo):
        print(f"WARNING: MONDO repository not found at {mondo_repo}")
        return []

    # Try mondo.json or mondo.obo
    mondo_json = os.path.join(mondo_repo, "src", "ontology", "mondo.json")
    mondo_obo = os.path.join(mondo_repo, "src", "ontology", "mondo.obo")

    # Check for mondo.json first
    if os.path.exists(mondo_json):
        try:
            with open(mondo_json, 'r') as f:
                mondo_data = json.load(f)

            matches = []
            term_lower = term.lower()

            for node in mondo_data.get('graphs', [{}])[0].get('nodes', []):
                if node.get('type') == 'CLASS':
                    mondo_id = node.get('id', '')
                    if 'MONDO:' in mondo_id or 'MONDO_' in mondo_id:
                        label = node.get('lbl', '')

                        # Exact match
                        if label.lower() == term_lower:
                            code = mondo_id.split('/')[-1].replace('MONDO_', 'MONDO:')
                            matches.append((code, label, 1.0))
                        # Partial match
                        elif term_lower in label.lower() or label.lower() in term_lower:
                            similarity = len(term_lower) / max(len(label), len(term))
                            code = mondo_id.split('/')[-1].replace('MONDO_', 'MONDO:')
                            matches.append((code, label, similarity))

            matches.sort(key=lambda x: x[2], reverse=True)
            return matches[:5]

        except Exception as e:
            print(f"ERROR searching MONDO JSON for '{term}': {e}")

    # Fallback to searching .obo file
    if os.path.exists(mondo_obo):
        try:
            matches = []
            term_lower = term.lower()

            with open(mondo_obo, 'r') as f:
                current_id = None
                current_name = None

                for line in f:
                    line = line.strip()

                    if line.startswith('id: MONDO:'):
                        current_id = line.split('id: ')[1]
                    elif line.startswith('name: '):
                        current_name = line.split('name: ')[1]

                        if current_id and current_name:
                            # Exact match
                            if current_name.lower() == term_lower:
                                matches.append((current_id, current_name, 1.0))
                            # Partial match
                            elif term_lower in current_name.lower() or current_name.lower() in term_lower:
                                similarity = len(term_lower) / max(len(current_name), len(term))
                                matches.append((current_id, current_name, similarity))

                    elif line == '' or line.startswith('[Term]'):
                        current_id = None
                        current_name = None

            matches.sort(key=lambda x: x[2], reverse=True)
            return matches[:5]

        except Exception as e:
            print(f"ERROR searching MONDO OBO for '{term}': {e}")

    print(f"WARNING: No MONDO data files found in {mondo_repo}")
    return []


def main():
    """Main execution function."""

    if not SYNAPSE_AVAILABLE:
        print("\nERROR: synapseclient not installed")
        print("Install with: pip install synapseclient")
        return

    # Initialize Synapse client
    syn = Synapse()

    try:
        syn.login(silent=True)
        print("✓ Synapse authentication successful")
    except Exception as e:
        print(f"\nERROR: Synapse authentication failed: {e}")
        print("Please run: synapse login")
        return

    # Query Synapse data
    diagnoses = query_synapse_diagnoses(syn)
    phenotypes = query_synapse_phenotypes(syn)

    # Search for MONDO codes
    print(f"\n{'='*80}")
    print("Searching for MONDO codes for diagnoses...")
    print(f"{'='*80}\n")

    mondo_results = {}
    for diagnosis in diagnoses.keys():
        print(f"\nSearching for: '{diagnosis}'")
        matches = search_mondo_code(diagnosis, MONDO_REPO)

        if matches:
            mondo_results[diagnosis] = matches
            for code, label, similarity in matches[:3]:
                marker = "✓✓✓" if similarity == 1.0 else "~" if similarity > 0.7 else "?"
                print(f"  {marker} {code}: {label} (similarity: {similarity:.2f})")
        else:
            print(f"  ✗ No matches found")
            mondo_results[diagnosis] = []

    # Search for HPO codes
    print(f"\n{'='*80}")
    print("Searching for HPO codes for phenotype fields...")
    print(f"{'='*80}\n")

    # Phenotype field to friendly name mapping
    field_to_term = {
        "dermalNeurofibromas": "dermal neurofibroma",
        "subcutaneousNodularNeurofibromas": "subcutaneous neurofibroma",
        "diffuseDermalNeurofibromas": "diffuse neurofibroma",
        "spinalNeurofibromas": "spinal neurofibroma",
        "nonopticGlioma": "glioma",
        "pheochromocytoma": "pheochromocytoma",
        "glomusTumor": "glomus tumor",
        "GIST": "gastrointestinal stromal tumor",
        "leukemia": "leukemia",
        "breastCancer": "breast cancer",
        "spinalSchwannoma": "spinal schwannoma",
        "dermalSchwannoma": "cutaneous schwannoma",
    }

    hpo_results = {}
    for field, search_term in field_to_term.items():
        print(f"\nSearching for: '{search_term}' (field: {field})")
        matches = search_hpo_code(search_term, HPO_REPO)

        if matches:
            hpo_results[field] = matches
            for code, label, similarity in matches[:3]:
                marker = "✓✓✓" if similarity == 1.0 else "~" if similarity > 0.5 else "?"
                print(f"  {marker} {code}: {label} (similarity: {similarity:.2f})")
        else:
            print(f"  ✗ No matches found")
            hpo_results[field] = []

    # Generate summary report
    print(f"\n{'='*80}")
    print("SUMMARY REPORT")
    print(f"{'='*80}\n")

    print("## Diagnosis MONDO Mappings\n")
    print("| Diagnosis | Count | MONDO Code | Label | Match |\n|-----------|-------|------------|-------|-------|")
    for diagnosis, count in sorted(diagnoses.items(), key=lambda x: x[1], reverse=True):
        if diagnosis in mondo_results and mondo_results[diagnosis]:
            code, label, similarity = mondo_results[diagnosis][0]
            match_type = "Exact" if similarity == 1.0 else f"Similar ({similarity:.0%})"
            print(f"| {diagnosis} | {count} | {code} | {label} | {match_type} |")
        else:
            print(f"| {diagnosis} | {count} | ❌ NOT FOUND | - | - |")

    print("\n## Phenotype HPO Mappings\n")
    print("| Field | Search Term | HPO Code | Label | Match |\n|-------|-------------|----------|-------|-------|")
    for field, search_term in field_to_term.items():
        if field in hpo_results and hpo_results[field]:
            code, label, similarity = hpo_results[field][0]
            match_type = "Exact" if similarity == 1.0 else f"Similar ({similarity:.0%})"
            print(f"| {field} | {search_term} | {code} | {label} | {match_type} |")
        else:
            print(f"| {field} | {search_term} | ❌ NOT FOUND | - | - |")


if __name__ == "__main__":
    main()
