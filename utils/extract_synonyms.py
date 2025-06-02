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

# Create a session for connection pooling
session = requests.Session()
session.timeout = 30  # Set timeout to 30 seconds

@lru_cache(maxsize=1000)
def fetch_rdf(term_url):
    """
    Try to fetch just that class as RDF/XML via content negotiation.
    Cached to avoid repeated requests for the same URL.
    """
    try:
        headers = {"Accept": "application/rdf+xml"}
        resp = session.get(term_url, headers=headers, timeout=30)
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
        resp = session.get(ontology_url, timeout=30)
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
    
    # Prepare CSV output
    with open('term_synonyms.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Term', 'URLs', 'Synonyms'])
        
        # Process terms in parallel with progress bar
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_term = {
                executor.submit(process_term, term, term_data): term 
                for term, term_data in terms_to_process
            }
            
            # Use tqdm to show progress
            for future in tqdm(concurrent.futures.as_completed(future_to_term), 
                             total=total_terms, 
                             desc="Processing terms"):
                try:
                    result = future.result(timeout=60)  # 60 second timeout per term
                    if result:
                        writer.writerow(result)
                except concurrent.futures.TimeoutError:
                    print(f"\nTimeout processing term")
                except Exception as e:
                    print(f"\nError processing term: {str(e)}")
    
    print("\nProcessing complete! Results saved to term_synonyms.csv")

if __name__ == "__main__":
    main() 