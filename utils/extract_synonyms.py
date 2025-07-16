#!/usr/bin/env python3
import os, sys
import yaml
import csv
import requests
import concurrent.futures
from functools import lru_cache
from rdflib import Graph, Namespace, URIRef
from rdflib.exceptions import ParserError
from urllib.parse import urlparse
from tqdm import tqdm
import time
import signal

# Create a session for connection pooling
session = requests.Session()
session.timeout = 15  # Reduced timeout to 15 seconds

# Global timeout handler
class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Script timeout reached")

# Set script timeout to 55 minutes (3300 seconds)
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(3300)

def expand_abbreviated_uri(abbreviated_uri):
    """
    Convert abbreviated URI (e.g., 'NCIT:C18485') to full URL.
    Returns None if the URI format is not recognized.
    """
    if not abbreviated_uri or ':' not in abbreviated_uri:
        return abbreviated_uri  # Already a full URL or invalid
    
    # If it's already a full URL, return as-is
    if abbreviated_uri.startswith('http'):
        return abbreviated_uri
    
    prefix, local_id = abbreviated_uri.split(':', 1)
    
    # Map common prefixes to base URIs
    prefix_map = {
        'NCIT': 'http://purl.obolibrary.org/obo/NCIT_',
        'EFO': 'http://www.ebi.ac.uk/efo/EFO_',
        'OBI': 'http://purl.obolibrary.org/obo/OBI_',
        'GO': 'http://purl.obolibrary.org/obo/GO_',
        'MONDO': 'http://purl.obolibrary.org/obo/MONDO_',
        'MI': 'http://purl.obolibrary.org/obo/MI_',
        'BAO': 'http://www.bioassayontology.org/bao#BAO_',
        'CHMO': 'http://purl.obolibrary.org/obo/CHMO_',
        'MAXO': 'http://purl.obolibrary.org/obo/MAXO_',
        'ERO': 'http://purl.obolibrary.org/obo/ERO_',
        'VT': 'http://purl.obolibrary.org/obo/VT_',
        'UO': 'http://purl.obolibrary.org/obo/UO_',
        'CL': 'http://purl.obolibrary.org/obo/CL_',
        'UBERON': 'http://purl.obolibrary.org/obo/UBERON_',
        'BTO': 'http://purl.obolibrary.org/obo/BTO_',
        'MMO': 'http://purl.obolibrary.org/obo/MMO_',
        'IAO': 'http://purl.obolibrary.org/obo/IAO_',
        'MS': 'http://purl.obolibrary.org/obo/MS_',
        'OMIABIS': 'http://purl.obolibrary.org/obo/OMIABIS_',
        'FBbi': 'http://purl.obolibrary.org/obo/FBbi_',
        'FBcv': 'http://purl.obolibrary.org/obo/FBcv_',
        'PATO': 'http://purl.obolibrary.org/obo/PATO_',
        'EDAM': 'http://edamontology.org/',
        'SWO': 'http://www.ebi.ac.uk/swo/data/SWO_',
        'SNOMED': 'http://snomed.info/id/',
        'ENM': 'http://purl.enanomapper.org/onto/ENM_',
        'DCM': 'http://dicom.nema.org/resources/ontology/DCM/',
        'CHEMINF': 'http://semanticscience.org/resource/CHEMINF_',
        'CMPO': 'http://www.ebi.ac.uk/cmpo/CMPO_',
        'ZFA': 'http://purl.obolibrary.org/obo/ZFA_',
        'DOID': 'http://purl.obolibrary.org/obo/DOID_',
        'FMA': 'http://purl.obolibrary.org/obo/FMA_',
        'CLO': 'http://purl.obolibrary.org/obo/CLO_',
        'GENO': 'http://purl.obolibrary.org/obo/GENO_'
    }
    
    if prefix in prefix_map:
        # Handle NCIT special case - it uses 'C' prefix in the ID
        if prefix == 'NCIT':
            return f"{prefix_map[prefix]}{local_id}"
        else:
            return f"{prefix_map[prefix]}{local_id}"
    
    print(f"Warning: Unknown prefix '{prefix}' in URI '{abbreviated_uri}'")
    return None

@lru_cache(maxsize=1000)
def fetch_rdf(term_url):
    """
    Try to fetch just that class as RDF/XML via content negotiation.
    Cached to avoid repeated requests for the same URL.
    """
    try:
        # Expand abbreviated URI if necessary
        full_url = expand_abbreviated_uri(term_url)
        if not full_url:
            print(f"Could not expand abbreviated URI: {term_url}")
            return None
            
        headers = {"Accept": "application/rdf+xml"}
        resp = session.get(full_url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Error fetching RDF for {term_url}: {str(e)}")
        return None

@lru_cache(maxsize=1000)
def fetch_full_ontology(term_url):
    """
    If that fails (or yields HTML), grab the entire ontology .owl file.
    Cached to avoid repeated requests for the same URL.
    """
    try:
        # Expand abbreviated URI if necessary
        full_url = expand_abbreviated_uri(term_url)
        if not full_url:
            print(f"Could not expand abbreviated URI: {term_url}")
            return None
            
        # Try to determine the ontology base URL from the full URL
        if 'purl.obolibrary.org/obo/' in full_url:
            # For OBO ontologies, extract the prefix and construct the .owl URL
            parts = full_url.split('/')
            for i, part in enumerate(parts):
                if part.startswith(('NCIT_', 'EFO_', 'OBI_', 'GO_', 'MONDO_', 'MI_', 'CHMO_', 'MAXO_', 'ERO_', 'VT_', 'UO_', 'CL_', 'UBERON_', 'BTO_', 'MMO_', 'IAO_', 'MS_', 'OMIABIS_', 'FBbi_', 'FBcv_', 'PATO_', 'ZFA_', 'DOID_', 'FMA_', 'CLO_', 'GENO_')):
                    prefix = part.split('_')[0]
                    ontology_url = f"http://purl.obolibrary.org/obo/{prefix.lower()}.owl"
                    break
            else:
                # Fallback: try to construct from the base
                base = full_url.rsplit("_", 1)[0]
                ontology_url = base + ".owl"
        elif 'ebi.ac.uk/efo/' in full_url:
            ontology_url = "http://www.ebi.ac.uk/efo/efo.owl"
        elif 'bioassayontology.org/bao' in full_url:
            ontology_url = "http://www.bioassayontology.org/bao/bao_complete.owl"
        else:
            # Generic fallback
            base = full_url.rsplit("_", 1)[0]
            ontology_url = base + ".owl"
            
        resp = session.get(ontology_url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Error fetching ontology for {term_url}: {str(e)}")
        return None

def extract_synonyms(rdf_data, term_iri):
    if not rdf_data:
        return []
    try:
        g = Graph()
        # explicitly tell RDFlib this is RDF/XML
        g.parse(data=rdf_data, format="xml")
        OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
        
        # Expand abbreviated URI if necessary
        expanded_iri = expand_abbreviated_uri(term_iri)
        if not expanded_iri:
            print(f"Could not expand IRI: {term_iri}")
            return []
            
        term = URIRef(expanded_iri)
        return [str(o) for o in g.objects(term, OIO.hasExactSynonym)]
    except Exception as e:
        print(f"Error extracting synonyms for {term_iri}: {str(e)}")
        return []

def get_synonyms_for_term(term_url):
    try:
        rdf = fetch_rdf(term_url)
        if rdf:
            syns = extract_synonyms(rdf, term_url)
            if syns:
                return syns
        
        # fallback to full ontology
        full_rdf = fetch_full_ontology(term_url)
        if full_rdf:
            return extract_synonyms(full_rdf, term_url)
    except Exception as e:
        print(f"Error processing {term_url}: {str(e)}")
    
    return []

def is_valid_url(url):
    """Check if the URL is valid (full URL or abbreviated URI) and not empty"""
    if not url or not isinstance(url, str):
        return False
    
    # Check if it's an abbreviated URI (like NCIT:C18485)
    if ':' in url and not url.startswith('http'):
        parts = url.split(':', 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return True
    
    # Check if it's a full URL
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def process_term(term, term_data):
    """Process a single term and return its data for CSV writing"""
    if term_data is None or not isinstance(term_data, dict):
        return None

    urls = []
    if 'meaning' in term_data and is_valid_url(term_data['meaning']):
        # Store both the original abbreviated URI and the expanded URL for reference
        original_uri = term_data['meaning']
        expanded_url = expand_abbreviated_uri(original_uri)
        if expanded_url:
            urls.append(('meaning', original_uri, expanded_url))
        else:
            urls.append(('meaning', original_uri, original_uri))

    if not urls:
        return None

    all_synonyms = []
    for url_type, original_uri, expanded_url in urls:
        # Use the expanded URL for fetching synonyms
        synonyms = get_synonyms_for_term(expanded_url if expanded_url != original_uri else original_uri)
        if synonyms:
            all_synonyms.extend(synonyms)

    if all_synonyms:
        # Store the original URI in the CSV for consistency with YAML
        return [term, original_uri, '; '.join(all_synonyms)]
    return None

def main():
    try:
        print("Reading YAML file...")
        # Read the YAML file
        with open('dist/NF.yaml', 'r') as f:
            data = yaml.safe_load(f)
        
        # Collect all terms to process
        terms_to_process = []
        for enum_name, enum_data in data.get('enums', {}).items():
            for term, term_data in enum_data.get('permissible_values', {}).items():
                terms_to_process.append((term, term_data))
        
        total_terms = len(terms_to_process)
        print(f"Found {total_terms} terms to process")
        
        # Check if we should resume from existing CSV
        processed_terms = set()
        csv_exists = os.path.exists('term_synonyms.csv')
        
        if csv_exists:
            print("Found existing CSV file, checking for already processed terms...")
            try:
                with open('term_synonyms.csv', 'r', newline='') as csvfile:
                    reader = csv.reader(csvfile)
                    next(reader)  # Skip header
                    for row in reader:
                        if row:  # Skip empty rows
                            processed_terms.add(row[0])
                print(f"Found {len(processed_terms)} already processed terms")
            except Exception as e:
                print(f"Error reading existing CSV: {e}")
                processed_terms = set()
        
        # Filter out already processed terms
        terms_to_process = [(term, term_data) for term, term_data in terms_to_process 
                           if term not in processed_terms]
        
        remaining_terms = len(terms_to_process)
        print(f"Processing {remaining_terms} remaining terms...")
        
        if remaining_terms == 0:
            print("All terms already processed!")
            return
        
        # Prepare CSV output (append mode if file exists)
        mode = 'a' if csv_exists else 'w'
        with open('term_synonyms.csv', mode, newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header only if creating new file
            if not csv_exists:
                writer.writerow(['Term', 'Meaning_URI', 'Synonyms'])
            
            # Process terms in smaller batches with reduced parallelism
            batch_size = 50
            max_workers = 5  # Reduced from 10
            
            for i in range(0, remaining_terms, batch_size):
                batch = terms_to_process[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (remaining_terms + batch_size - 1) // batch_size
                
                print(f"\nProcessing batch {batch_num}/{total_batches} ({len(batch)} terms)")
                
                # Process batch in parallel
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_term = {
                        executor.submit(process_term, term, term_data): term 
                        for term, term_data in batch
                    }
                    
                    # Use tqdm for batch progress
                    for future in tqdm(concurrent.futures.as_completed(future_to_term), 
                                     total=len(batch), 
                                     desc=f"Batch {batch_num}"):
                        try:
                            result = future.result(timeout=30)  # Reduced timeout to 30 seconds
                            if result:
                                writer.writerow(result)
                        except concurrent.futures.TimeoutError:
                            term_name = future_to_term[future]
                            print(f"\nTimeout processing term: {term_name}")
                        except Exception as e:
                            term_name = future_to_term[future]
                            print(f"\nError processing term {term_name}: {str(e)}")
                
                # Flush after each batch to save progress
                csvfile.flush()
                
        print("\nProcessing complete! Results saved to term_synonyms.csv")
        
    except TimeoutError:
        print("\nScript timeout reached (35 minutes). Partial results saved to CSV.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nScript interrupted. Partial results saved to CSV.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")
        sys.exit(1)
    finally:
        signal.alarm(0)  # Cancel the alarm

if __name__ == "__main__":
    main() 