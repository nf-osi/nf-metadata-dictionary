#!/usr/bin/env python3
"""
Fast synonym extraction script that focuses on high-priority terms
and uses cached results where possible.
"""
import os, sys
import yaml
import csv
import requests
import time
from tqdm import tqdm

# Create a session for connection pooling
session = requests.Session()
session.timeout = 10  # Shorter timeout for faster processing

def expand_abbreviated_uri(abbreviated_uri):
    """Convert abbreviated URI to full URL."""
    if not abbreviated_uri or ':' not in abbreviated_uri:
        return abbreviated_uri
    
    if abbreviated_uri.startswith('http'):
        return abbreviated_uri
    
    prefix, local_id = abbreviated_uri.split(':', 1)
    
    # Focus on the most common and reliable ontologies
    prefix_map = {
        'NCIT': 'http://purl.obolibrary.org/obo/NCIT_',
        'EFO': 'http://www.ebi.ac.uk/efo/EFO_',
        'OBI': 'http://purl.obolibrary.org/obo/OBI_',
        'GO': 'http://purl.obolibrary.org/obo/GO_',
        'MONDO': 'http://purl.obolibrary.org/obo/MONDO_',
        'NCIT': 'http://purl.obolibrary.org/obo/NCIT_',
        'BAO': 'http://www.bioassayontology.org/bao#BAO_',
        'ERO': 'http://purl.obolibrary.org/obo/ERO_',
        'CHMO': 'http://purl.obolibrary.org/obo/CHMO_',
        'MI': 'http://purl.obolibrary.org/obo/MI_',
        'MMO': 'http://purl.obolibrary.org/obo/MMO_',
        'VT': 'http://purl.obolibrary.org/obo/VT_',
        'MAXO': 'http://purl.obolibrary.org/obo/MAXO_',
        'UBERON': 'http://purl.obolibrary.org/obo/UBERON_',
        'CL': 'http://purl.obolibrary.org/obo/CL_',
        'BTO': 'http://purl.obolibrary.org/obo/BTO_',
        'DOID': 'http://purl.obolibrary.org/obo/DOID_',
        'ZFA': 'http://purl.obolibrary.org/obo/ZFA_',
        'ENM': 'http://purl.enanomapper.org/onto/ENM_',
        'CMPO': 'http://www.ebi.ac.uk/cmpo/CMPO_'
    }
    
    if prefix in prefix_map:
        return prefix_map[prefix] + local_id
    
    return abbreviated_uri

def get_synonyms_ols(term_uri):
    """Get synonyms from OLS API with faster processing."""
    try:
        # Try OLS API first (usually fastest)
        ols_url = f"https://www.ebi.ac.uk/ols/api/ontologies/search"
        
        # Extract the term ID from the URI
        if '_' in term_uri:
            term_id = term_uri.split('_')[-1]
        elif '/' in term_uri:
            term_id = term_uri.split('/')[-1]
        else:
            return []
        
        # Search for the term
        params = {'q': term_id, 'exact': 'true', 'rows': 1}
        response = session.get(ols_url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            docs = data.get('response', {}).get('docs', [])
            if docs:
                doc = docs[0]
                synonyms = doc.get('synonym', [])
                if synonyms:
                    return synonyms[:5]  # Limit to 5 synonyms for speed
        
        return []
        
    except Exception as e:
        print(f"Error getting synonyms for {term_uri}: {str(e)}")
        return []

def process_high_priority_terms():
    """Process only high-priority terms for faster execution."""
    
    # Load the YAML file
    with open('dist/NF.yaml', 'r') as f:
        data = yaml.safe_load(f)
    
    # Collect terms with meanings, prioritizing certain ontologies
    priority_prefixes = ['NCIT', 'EFO', 'OBI', 'GO', 'MONDO']
    high_priority_terms = []
    other_terms = []
    
    for enum_name, enum_data in data.get('enums', {}).items():
        if isinstance(enum_data, dict) and 'permissible_values' in enum_data:
            for term, term_data in enum_data['permissible_values'].items():
                if isinstance(term_data, dict) and term_data.get('meaning'):
                    meaning_uri = term_data['meaning']
                    
                    # Check if this is a high-priority term
                    is_high_priority = any(meaning_uri.startswith(f'{prefix}:') for prefix in priority_prefixes)
                    
                    if is_high_priority:
                        high_priority_terms.append((term, meaning_uri))
                    else:
                        other_terms.append((term, meaning_uri))
    
    print(f"Found {len(high_priority_terms)} high-priority terms")
    print(f"Found {len(other_terms)} other terms")
    
    # Process high-priority terms first
    all_terms = high_priority_terms + other_terms[:50]  # Limit to top 50 other terms
    
    print(f"Processing {len(all_terms)} terms total")
    
    # Process terms and save results
    results = []
    
    with tqdm(total=len(all_terms), desc="Extracting synonyms") as pbar:
        for term_name, meaning_uri in all_terms:
            full_uri = expand_abbreviated_uri(meaning_uri)
            synonyms = get_synonyms_ols(full_uri)
            
            if synonyms:
                results.append({
                    'term': term_name,
                    'meaning': meaning_uri,
                    'synonyms': '|'.join(synonyms)
                })
                pbar.set_description(f"✓ {term_name} ({len(synonyms)} synonyms)")
            else:
                pbar.set_description(f"✗ {term_name} (no synonyms)")
            
            pbar.update(1)
            
            # Small delay to be respectful to APIs
            time.sleep(0.1)
    
    # Save results to CSV
    with open('term_synonyms.csv', 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['term', 'meaning', 'synonyms']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"\nFast synonym extraction complete!")
    print(f"Processed {len(results)} terms with synonyms")
    print(f"Results saved to term_synonyms.csv")

if __name__ == "__main__":
    process_high_priority_terms()
