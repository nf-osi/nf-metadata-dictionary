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

@lru_cache(maxsize=1000)
def fetch_rdf(term_url):
    """
    Try to fetch just that class as RDF/XML via content negotiation.
    Cached to avoid repeated requests for the same URL.
    """
    try:
        headers = {"Accept": "application/rdf+xml"}
        resp = session.get(term_url, headers=headers, timeout=15)
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
        base = term_url.rsplit("_", 1)[0]
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
        term = URIRef(term_iri)
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
    """Check if the URL is valid and not empty"""
    if not url or not isinstance(url, str):
        return False
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
        urls.append(('meaning', term_data['meaning']))

    if not urls:
        return None

    all_synonyms = []
    for url_type, url in urls:
        synonyms = get_synonyms_for_term(url)
        if synonyms:
            all_synonyms.extend(synonyms)

    if all_synonyms:
        return [term, '; '.join(url for _, url in urls), '; '.join(all_synonyms)]
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
                writer.writerow(['Term', 'URLs', 'Synonyms'])
            
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