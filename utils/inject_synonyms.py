#!/usr/bin/env python3
"""
Script to inject synonyms from CSV file into NF.yaml as aliases.
Also implements fuzzy matching to handle case-only differences.
"""
import os
import sys
import yaml
import csv
import re
from difflib import SequenceMatcher

def normalize_for_comparison(text):
    """Normalize text for fuzzy comparison (remove spaces, punctuation, lowercase)"""
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def is_case_only_difference(term, synonym):
    """Check if two strings differ only by case and punctuation"""
    return normalize_for_comparison(term) == normalize_for_comparison(synonym)

def similarity_ratio(a, b):
    """Calculate similarity ratio between two strings"""
    return SequenceMatcher(None, normalize_for_comparison(a), normalize_for_comparison(b)).ratio()

def load_synonyms_from_csv(csv_file):
    """Load synonyms from CSV file and return a dictionary"""
    synonyms_dict = {}
    
    if not os.path.exists(csv_file):
        print(f"Warning: CSV file {csv_file} not found")
        return synonyms_dict
    
    try:
        with open(csv_file, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                term = row['Term']
                synonyms_str = row['Synonyms']
                
                if synonyms_str and synonyms_str.strip():
                    # Split synonyms by semicolon and clean whitespace
                    synonyms = [syn.strip() for syn in synonyms_str.split(';') if syn.strip()]
                    synonyms_dict[term] = synonyms
                    
        print(f"Loaded synonyms for {len(synonyms_dict)} terms from {csv_file}")
        return synonyms_dict
        
    except Exception as e:
        print(f"Error reading CSV file {csv_file}: {str(e)}")
        return synonyms_dict

def filter_synonyms(term, synonyms, fuzzy_threshold=0.9):
    """
    Filter synonyms to:
    1. Skip case-only differences
    2. Use fuzzy matching for near-duplicates
    """
    filtered = []
    
    for synonym in synonyms:
        # Skip exact matches (case sensitive)
        if synonym == term:
            continue
            
        # Skip case-only differences
        if is_case_only_difference(term, synonym):
            print(f"  Skipping case-only difference: '{term}' vs '{synonym}'")
            continue
            
        # Check for fuzzy matches with existing filtered synonyms
        is_fuzzy_duplicate = False
        for existing in filtered:
            if similarity_ratio(synonym, existing) >= fuzzy_threshold:
                print(f"  Skipping fuzzy duplicate: '{synonym}' (similar to '{existing}')")
                is_fuzzy_duplicate = True
                break
                
        if not is_fuzzy_duplicate:
            # Also check against the original term
            if similarity_ratio(synonym, term) < fuzzy_threshold:
                filtered.append(synonym)
            else:
                print(f"  Skipping fuzzy match with term: '{synonym}' vs '{term}'")
    
    return filtered

def inject_synonyms_into_yaml(yaml_file, synonyms_dict, output_file=None):
    """Inject synonyms as aliases into the YAML file"""
    
    if not os.path.exists(yaml_file):
        print(f"Error: YAML file {yaml_file} not found")
        return False
        
    try:
        # Load YAML file
        with open(yaml_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            
        modifications_made = 0
        
        # Process enums
        if 'enums' in data:
            for enum_name, enum_data in data['enums'].items():
                if 'permissible_values' in enum_data:
                    for term, term_data in enum_data['permissible_values'].items():
                        if term in synonyms_dict:
                            # Filter synonyms
                            filtered_synonyms = filter_synonyms(term, synonyms_dict[term])
                            
                            if filtered_synonyms:
                                if term_data is None:
                                    term_data = {}
                                    enum_data['permissible_values'][term] = term_data
                                
                                # Add aliases
                                term_data['aliases'] = filtered_synonyms
                                modifications_made += 1
                                print(f"Added {len(filtered_synonyms)} aliases to '{term}'")
        
        # Write output
        output_path = output_file or yaml_file
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, width=1000)
            
        print(f"\nCompleted! Modified {modifications_made} terms.")
        if output_file:
            print(f"Results written to {output_file}")
        else:
            print(f"Updated {yaml_file} in place")
            
        return True
        
    except Exception as e:
        print(f"Error processing YAML file: {str(e)}")
        return False

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Inject synonyms from CSV into YAML as aliases')
    parser.add_argument('--csv', default='term_synonyms.csv', 
                       help='Path to CSV file with synonyms (default: term_synonyms.csv)')
    parser.add_argument('--yaml', default='dist/NF.yaml',
                       help='Path to YAML file to modify (default: dist/NF.yaml)')
    parser.add_argument('--output', 
                       help='Output file path (default: modify input YAML in place)')
    parser.add_argument('--fuzzy-threshold', type=float, default=0.9,
                       help='Fuzzy matching threshold (0.0-1.0, default: 0.9)')
    
    args = parser.parse_args()
    
    print("=== Synonym Injection Tool ===")
    print(f"CSV file: {args.csv}")
    print(f"YAML file: {args.yaml}")
    print(f"Fuzzy threshold: {args.fuzzy_threshold}")
    
    # Load synonyms from CSV
    synonyms_dict = load_synonyms_from_csv(args.csv)
    
    if not synonyms_dict:
        print("No synonyms loaded. Exiting.")
        return 1
        
    # Inject synonyms into YAML
    success = inject_synonyms_into_yaml(args.yaml, synonyms_dict, args.output)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
