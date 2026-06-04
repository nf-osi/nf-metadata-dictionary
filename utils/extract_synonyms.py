#!/usr/bin/env python3
"""
Extract synonyms for ontology-mapped terms in the NF metadata dictionary.

Primary method: OLS4 REST API (fast, reliable JSON responses).
Fallback: RDF content negotiation against the term URI.
"""
import os
import sys
import yaml
import csv
import requests
import concurrent.futures
import urllib.parse
import signal
import re
from functools import lru_cache
from tqdm import tqdm

# Optional: RDF fallback (only used when OLS4 doesn't cover the ontology)
try:
    from rdflib import Graph, Namespace, URIRef
    HAS_RDFLIB = True
except ImportError:
    HAS_RDFLIB = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLS4_BASE = "https://www.ebi.ac.uk/ols4/api/ontologies"
REQUEST_TIMEOUT = 15  # seconds per HTTP request
FUTURE_TIMEOUT = 30   # seconds per term in thread pool
BATCH_SIZE = 50
MAX_WORKERS = 5
SCRIPT_TIMEOUT = 600  # 10 minutes -- OLS4 is fast enough

# Map URL patterns to OLS4 ontology identifiers
OLS4_ONTOLOGY_MAP: dict[str, str] = {
    "purl.obolibrary.org/obo/NCIT_": "ncit",
    "purl.obolibrary.org/obo/OBI_": "obi",
    "purl.obolibrary.org/obo/BTO_": "bto",
    "purl.obolibrary.org/obo/UBERON_": "uberon",
    "purl.obolibrary.org/obo/CHMO_": "chmo",
    "purl.obolibrary.org/obo/MI_": "mi",
    "purl.obolibrary.org/obo/ERO_": "ero",
    "purl.obolibrary.org/obo/CL_": "cl",
    "purl.obolibrary.org/obo/MMO_": "mmo",
    "purl.obolibrary.org/obo/UO_": "uo",
    "purl.obolibrary.org/obo/MAXO_": "maxo",
    "purl.obolibrary.org/obo/MONDO_": "mondo",
    "purl.obolibrary.org/obo/VT_": "vt",
    "purl.obolibrary.org/obo/FMA_": "fma",
    "purl.obolibrary.org/obo/GO_": "go",
    "purl.obolibrary.org/obo/GENO_": "geno",
    "purl.obolibrary.org/obo/IAO_": "iao",
    "purl.obolibrary.org/obo/FBbi_": "fbbi",
    "purl.obolibrary.org/obo/FBcv_": "fbcv",
    "purl.obolibrary.org/obo/NBO_": "nbo",
    "purl.obolibrary.org/obo/ZFA_": "zfa",
    "purl.obolibrary.org/obo/MS_": "ms",
    "purl.obolibrary.org/obo/ENM_": "enm",
    "purl.obolibrary.org/obo/OMIABIS_": "omiabis",
    "purl.obolibrary.org/obo/SWO_": "swo",
    "www.ebi.ac.uk/efo/EFO_": "efo",
    "edamontology.org/": "edam",
    "www.bioassayontology.org/bao#BAO_": "bao",
}

# Create a session for connection pooling
session = requests.Session()
session.headers.update({"Accept": "application/json"})

# ---------------------------------------------------------------------------
# Timeout handler
# ---------------------------------------------------------------------------
class ScriptTimeout(Exception):
    pass

def _timeout_handler(signum, frame):
    raise ScriptTimeout("Script timeout reached")

signal.signal(signal.SIGALRM, _timeout_handler)
signal.alarm(SCRIPT_TIMEOUT)

# ---------------------------------------------------------------------------
# CURIE / URI helpers
# ---------------------------------------------------------------------------
def load_prefixes_from_yaml(yaml_file: str) -> dict[str, str]:
    """Load prefix mappings from the compiled NF.yaml."""
    try:
        with open(yaml_file, "r") as f:
            data = yaml.safe_load(f)
        return data.get("prefixes", {})
    except Exception as e:
        print(f"Error loading prefixes from {yaml_file}: {e}")
        return {}


def expand_curie(curie: str, prefixes: dict[str, str]) -> str:
    """Expand a CURIE to a full URI using prefix mappings."""
    if not curie or not isinstance(curie, str):
        return curie
    if curie.startswith("http://") or curie.startswith("https://"):
        return curie
    if ":" in curie:
        prefix, suffix = curie.split(":", 1)
        if prefix in prefixes:
            return prefixes[prefix] + suffix
    return curie


def is_valid_ontology_url(url: str) -> bool:
    """Return True if url looks like a resolvable ontology term URI."""
    if not url or not isinstance(url, str):
        return False
    # Skip non-ontology URLs (Creative Commons, ROR, RRID, etc.)
    skip_patterns = [
        "creativecommons.org",
        "ror.org",
        "identifiers.org/RRID",
    ]
    return (
        url.startswith("http://") or url.startswith("https://")
    ) and not any(pat in url for pat in skip_patterns)


# ---------------------------------------------------------------------------
# OLS4 API (primary)
# ---------------------------------------------------------------------------
def _extract_ontology_id(term_url: str) -> str | None:
    """Derive the OLS4 ontology identifier from a term URL."""
    for pattern, ontology_id in OLS4_ONTOLOGY_MAP.items():
        if pattern in term_url:
            return ontology_id
    return None


@lru_cache(maxsize=2000)
def fetch_synonyms_ols4(term_url: str) -> list[str]:
    """Fetch synonyms via the OLS4 REST API (primary method)."""
    ontology_id = _extract_ontology_id(term_url)
    if not ontology_id:
        return []
    try:
        encoded_iri = urllib.parse.quote(urllib.parse.quote(term_url, safe=""))
        url = f"{OLS4_BASE}/{ontology_id}/terms/{encoded_iri}"
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("synonyms", [])
    except Exception as e:
        print(f"  OLS4 lookup failed for {term_url}: {e}")
        return []


# ---------------------------------------------------------------------------
# RDF content negotiation (fallback)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1000)
def _fetch_rdf(term_url: str) -> str | None:
    """Try to fetch the term as RDF/XML via content negotiation."""
    if not HAS_RDFLIB:
        return None
    try:
        headers = {"Accept": "application/rdf+xml"}
        resp = session.get(term_url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "xml" not in ct and "rdf" not in ct:
            return None  # got HTML or something else
        return resp.text
    except Exception:
        return None


def _extract_synonyms_rdf(rdf_data: str, term_iri: str) -> list[str]:
    """Parse RDF/XML and extract hasExactSynonym values."""
    if not rdf_data or not HAS_RDFLIB:
        return []
    try:
        g = Graph()
        g.parse(data=rdf_data, format="xml")
        OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
        term = URIRef(term_iri)
        return [str(o) for o in g.objects(term, OIO.hasExactSynonym)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Unified synonym fetcher
# ---------------------------------------------------------------------------
def get_synonyms_for_term(term_url: str) -> list[str]:
    """Get synonyms for a term URL, trying OLS4 first then RDF fallback."""
    # Primary: OLS4 API
    syns = fetch_synonyms_ols4(term_url)
    if syns:
        return syns

    # Fallback: RDF content negotiation (for ontologies not in OLS4)
    rdf = _fetch_rdf(term_url)
    if rdf:
        syns = _extract_synonyms_rdf(rdf, term_url)
        if syns:
            return syns

    return []


# ---------------------------------------------------------------------------
# Term processing
# ---------------------------------------------------------------------------
def process_term(
    term: str, term_data: dict, prefixes: dict[str, str]
) -> list[str] | None:
    """Process a single term and return a CSV row [term, url, synonyms] or None."""
    if term_data is None or not isinstance(term_data, dict):
        return None

    meaning = term_data.get("meaning")
    full_url = expand_curie(meaning, prefixes) if meaning else None
    if not full_url or not is_valid_ontology_url(full_url):
        return None

    synonyms = get_synonyms_for_term(full_url)
    if synonyms:
        return [term, full_url, "; ".join(synonyms)]
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        print("Reading YAML file...")
        with open("dist/NF.yaml", "r") as f:
            data = yaml.safe_load(f)

        prefixes = load_prefixes_from_yaml("dist/NF.yaml")
        print(f"Loaded {len(prefixes)} prefixes")

        # Collect all terms
        terms_to_process: list[tuple[str, dict]] = []
        for enum_name, enum_data in data.get("enums", {}).items():
            for term, term_data in enum_data.get("permissible_values", {}).items():
                terms_to_process.append((term, term_data))

        total_terms = len(terms_to_process)
        print(f"Found {total_terms} terms to process")

        # Resume from existing CSV if present
        processed_terms: set[str] = set()
        csv_exists = os.path.exists("term_synonyms.csv")

        if csv_exists:
            print("Found existing CSV, checking for already processed terms...")
            try:
                with open("term_synonyms.csv", "r", newline="") as csvfile:
                    reader = csv.reader(csvfile)
                    next(reader)  # skip header
                    for row in reader:
                        if row:
                            processed_terms.add(row[0])
                print(f"Found {len(processed_terms)} already processed terms")
            except Exception as e:
                print(f"Error reading existing CSV: {e}")
                processed_terms = set()

        terms_to_process = [
            (t, td) for t, td in terms_to_process if t not in processed_terms
        ]
        remaining = len(terms_to_process)
        print(f"Processing {remaining} remaining terms...")

        if remaining == 0:
            print("All terms already processed!")
            return

        mode = "a" if csv_exists else "w"
        with open("term_synonyms.csv", mode, newline="") as csvfile:
            writer = csv.writer(csvfile)
            if not csv_exists:
                writer.writerow(["Term", "URLs", "Synonyms"])

            total_batches = (remaining + BATCH_SIZE - 1) // BATCH_SIZE

            for i in range(0, remaining, BATCH_SIZE):
                batch = terms_to_process[i : i + BATCH_SIZE]
                batch_num = (i // BATCH_SIZE) + 1
                print(f"\nProcessing batch {batch_num}/{total_batches} ({len(batch)} terms)")

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=MAX_WORKERS
                ) as executor:
                    future_to_term = {
                        executor.submit(process_term, term, term_data, prefixes): term
                        for term, term_data in batch
                    }

                    for future in tqdm(
                        concurrent.futures.as_completed(future_to_term),
                        total=len(batch),
                        desc=f"Batch {batch_num}",
                    ):
                        try:
                            result = future.result(timeout=FUTURE_TIMEOUT)
                            if result:
                                writer.writerow(result)
                        except concurrent.futures.TimeoutError:
                            term_name = future_to_term[future]
                            print(f"\nTimeout processing term: {term_name}")
                        except Exception as e:
                            term_name = future_to_term[future]
                            print(f"\nError processing term {term_name}: {e}")

                csvfile.flush()

        print("\nProcessing complete! Results saved to term_synonyms.csv")

    except ScriptTimeout:
        print("\nScript timeout reached. Partial results saved to CSV.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nScript interrupted. Partial results saved to CSV.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
