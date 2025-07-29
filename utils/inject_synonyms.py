#!/usr/bin/env python3
"""
Script to inject synonyms from CSV file into NF.yaml as aliases.
Also implements fuzzy matching to handle case-only differences.
Supports both full URIs and CURIEs in the meaning field.
"""
import os
import sys
import yaml
import csv
import re
from difflib import SequenceMatcher

def expand_curie(curie, prefixes):
    """Expand a CURIE to a full URI using prefix mappings"""
    if not curie or not isinstance(curie, str):
        return curie
    
    # If it's already a full URI, return as-is
    if curie.startswith('http://') or curie.startswith('https://'):
        return curie
    
    # Check if it's a CURIE (contains colon)
    if ':' in curie:
        prefix, suffix = curie.split(':', 1)
        if prefix in prefixes:
            return prefixes[prefix] + suffix
    
    return curie

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
            
        return modifications_made > 0
        
    except Exception as e:
        print(f"Error processing YAML file: {str(e)}")
        return False

def inject_synonyms_into_modules(modules_dir, synonyms_dict):
    """Inject synonyms as aliases into all module YAML files"""
    import glob
    
    if not os.path.exists(modules_dir):
        print(f"Error: Modules directory {modules_dir} not found")
        return False
        
    # Find all YAML files in modules directory (recursively)
    yaml_pattern = os.path.join(modules_dir, "**/*.yaml")
    yaml_files = glob.glob(yaml_pattern, recursive=True)
    
    if not yaml_files:
        print(f"No YAML files found in {modules_dir}")
        return False
        
    print(f"Found {len(yaml_files)} YAML files in modules directory")
    
    total_modifications = 0
    modified_files = []
    
    for yaml_file in yaml_files:
        print(f"\nProcessing: {yaml_file}")
        
        # Process this file
        file_modified = inject_synonyms_into_yaml(yaml_file, synonyms_dict)
        
        if file_modified:
            modified_files.append(yaml_file)
            total_modifications += 1
    
    print(f"\n=== Summary ===")
    print(f"Processed {len(yaml_files)} files")
    print(f"Modified {len(modified_files)} files")
    
    if modified_files:
        print("\nModified files:")
        for file_path in modified_files:
            print(f"  {file_path}")
    
    return len(modified_files) > 0

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Inject synonyms from CSV into YAML as aliases')
    parser.add_argument('--csv', default='term_synonyms.csv', 
                       help='Path to CSV file with synonyms (default: term_synonyms.csv)')
    parser.add_argument('--yaml', 
                       help='Path to single YAML file to modify (use either --yaml or --modules-dir)')
    parser.add_argument('--modules-dir', default='modules',
                       help='Path to modules directory containing YAML files (default: modules)')
    parser.add_argument('--output', 
                       help='Output file path (only works with --yaml option)')
    parser.add_argument('--fuzzy-threshold', type=float, default=0.9,
                       help='Fuzzy matching threshold (0.0-1.0, default: 0.9)')
    
    args = parser.parse_args()
    
    print("=== Synonym Injection Tool ===")
    print(f"CSV file: {args.csv}")
    print(f"Fuzzy threshold: {args.fuzzy_threshold}")
    
    # Check arguments
    if args.yaml and args.modules_dir != 'modules':
        print("Error: Cannot specify both --yaml and --modules-dir")
        return 1
        
    if args.output and not args.yaml:
        print("Error: --output can only be used with --yaml")
        return 1
    
    # Load synonyms from CSV
    synonyms_dict = load_synonyms_from_csv(args.csv)
    
    if not synonyms_dict:
        print("No synonyms loaded. Exiting.")
        return 1
    
    # Determine operation mode
    if args.yaml:
        print(f"Mode: Single file - {args.yaml}")
        success = inject_synonyms_into_yaml(args.yaml, synonyms_dict, args.output)
    else:
        print(f"Mode: Modules directory - {args.modules_dir}")
        success = inject_synonyms_into_modules(args.modules_dir, synonyms_dict)
        
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
