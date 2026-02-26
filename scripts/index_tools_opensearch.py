#!/usr/bin/env python3
"""
Index NF Tools Central into OpenSearch, enabling unified search with
dependent faceted filtering across all 9 resource types.

Dependent facets follow the OpenSearch post_filter + filter aggregations pattern:
https://docs.opensearch.org/latest/tutorials/faceted-search/#step-4-filter-by-facet-values

How dependent facets work here:
  - `resourceType` is the pivot facet. Selecting "Antibody" filters results to
    Antibody records only.
  - Each facet's aggregation applies all OTHER active filters (not its own), so:
      - The `resourceType` agg always shows all resource type counts (unfiltered by itself)
      - The `targetAntigen` agg is filtered by the active `resourceType` selection,
        so it only counts target antigens from Antibody records when "Antibody" is selected
  - Dependent facets (e.g. targetAntigen, cellLineManifestation) are naturally scoped
    because those columns are only populated for their respective resource types.
    The portal UI can additionally choose to render them only when the relevant
    resourceType is active.

Data sources:
  - syn51730943 (Tools materialized view, existing 5 types):
      Cell Line, Animal Model, Antibody, Genetic Reagent, Biobank
  - syn73709226 (ComputationalToolDetails): Computational Tool
  - syn73709227 (AdvancedCellularModelDetails): Advanced Cellular Model
  - syn73709228 (PatientDerivedModelDetails): Patient-Derived Model
  - syn73709229 (ClinicalAssessmentToolDetails): Clinical Assessment Tool

Why separate sources instead of one unified materialized view?
  Synapse has a 64 KB per-row size limit for materialized views. The new v2.0
  types have STRING_LIST columns (e.g. programmingLanguage, cellTypes) that are
  expensive (up to 1,000 bytes each), and adding all new columns to syn51730943
  would risk exceeding this limit. OpenSearch has no row size constraint, so we
  query each source table independently and merge into a single index here.

Usage:
    # Dry run — shows document counts, no writes
    python scripts/index_tools_opensearch.py --dry-run

    # Index into a running OpenSearch instance
    python scripts/index_tools_opensearch.py --host localhost:9200

    # Custom index name
    python scripts/index_tools_opensearch.py --host localhost:9200 --index nf-tools

    # Print a sample query for given active filters (no OpenSearch needed)
    python scripts/index_tools_opensearch.py --show-query --filters '{"resourceType":"Antibody"}'
"""

import argparse
import json
import logging
import math
import os
import sys
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

# Existing 5 resource types (Cell Line, Animal Model, Antibody, Genetic Reagent, Biobank)
SOURCE_VIEW_ID = 'syn51730943'

# v2.0 resource types — dedicated detail tables, queried separately to avoid
# pushing syn51730943 past the Synapse 64 KB per-row limit.
# Keys are the resourceType values these records will carry in OpenSearch.
# id_col: primary key column in the Synapse table (used as OpenSearch _id)
# name_col: column to surface as `resourceName` for text search (None if absent)
NEW_RESOURCE_TABLES: Dict[str, Dict[str, Optional[str]]] = {
    'Computational Tool': {
        'syn_id': 'syn73709226',
        'id_col': 'computationalToolId',
        'name_col': 'softwareName',
    },
    'Advanced Cellular Model': {
        'syn_id': 'syn73709227',
        'id_col': 'advancedCellularModelId',
        'name_col': None,   # No dedicated display-name column in table schema
    },
    'Patient-Derived Model': {
        'syn_id': 'syn73709228',
        'id_col': 'patientDerivedModelId',
        'name_col': None,   # No dedicated display-name column in table schema
    },
    'Clinical Assessment Tool': {
        'syn_id': 'syn73709229',
        'id_col': 'clinicalAssessmentToolId',
        'name_col': 'assessmentName',
    },
}

# ---------------------------------------------------------------------------
# Facet definitions
# ---------------------------------------------------------------------------

# Always-visible facets regardless of resourceType selection.
COMMON_FACETS: List[str] = [
    'resourceType',
    'species',
    'usageRequirements',
    'funderName',
]

# Facets that are only meaningful (and only populated) for a specific resourceType.
# The portal UI should render these only when the corresponding resourceType is
# selected; OpenSearch will naturally return empty buckets for unrelated records.
DEPENDENT_FACETS: Dict[str, List[str]] = {
    # ── Original 5 resource types (from syn51730943) ──────────────────────────
    'Cell Line': [
        'cellLineGeneticDisorder',
        'cellLineCategory',
        'cellLineManifestation',
        'sex',
        'age',
        'race',
    ],
    'Animal Model': [
        'animalModelGeneticDisorder',
        'animalModelOfManifestation',
        'backgroundStrain',
    ],
    'Antibody': [
        'targetAntigen',
        'reactiveSpecies',
        'hostOrganism',
        'clonality',
        'conjugate',
    ],
    'Genetic Reagent': [
        'insertName',
        'vectorType',
        'insertSpecies',
    ],
    'Biobank': [
        'specimenTissueType',
        'tumorType',
        'specimenFormat',
        'specimenPreparationMethod',
        'specimenType',
    ],
    # ── v2.0 resource types (from dedicated tables) ───────────────────────────
    'Computational Tool': [
        'softwareType',
        'programmingLanguage',   # STRING_LIST in Synapse → multi-value keyword in OpenSearch
        'licenseType',
        'containerized',
    ],
    'Advanced Cellular Model': [
        'modelType',
        'derivationSource',
        'organoidType',
        'cultureSystem',
    ],
    'Patient-Derived Model': [
        'modelSystemType',
        'patientDiagnosis',
        'tumorType',             # Also used by Biobank; same field, different records
        'engraftmentSite',
        'hostStrain',
    ],
    'Clinical Assessment Tool': [
        'assessmentType',
        'targetPopulation',
        'diseaseSpecific',
        'scoringMethod',
    ],
}

# All facet fields in one flat list (common + all dependent).
ALL_FACET_FIELDS: List[str] = COMMON_FACETS + list(dict.fromkeys(
    f for facets in DEPENDENT_FACETS.values() for f in facets
))

# Fields that should be full-text searchable in addition to keyword filtering.
# `resourceName` is the normalized name field across all resource types; the
# per-type name columns (softwareName, assessmentName) are mapped to it on ingest.
TEXT_SEARCH_FIELDS: List[str] = [
    'resourceName',
    'synonyms',
    'description',
]

# ---------------------------------------------------------------------------
# Indexer class
# ---------------------------------------------------------------------------

class ToolsOpenSearchIndexer:
    """
    Fetches NF Tools Central data from Synapse and indexes it into OpenSearch
    with a mapping and query builder designed for dependent faceted search.
    """

    DEFAULT_INDEX = 'nf-tools'

    def build_index_mapping(self) -> Dict:
        """
        Return the OpenSearch index mapping.

        Facet fields use `keyword` type so they support exact-match
        aggregations/filters. Multi-value fields (STRING_LIST in Synapse)
        are also mapped as keyword — OpenSearch handles arrays natively.
        Numeric fields (`age`) use integer type.
        """
        properties: Dict[str, Any] = {}

        # Text-searchable fields with keyword sub-field for exact filtering
        for field in TEXT_SEARCH_FIELDS:
            properties[field] = {
                'type': 'text',
                'fields': {'keyword': {'type': 'keyword', 'ignore_above': 512}},
            }

        # Facet fields: keyword for aggregation/filter
        for field in ALL_FACET_FIELDS:
            if field == 'age':
                properties[field] = {'type': 'integer'}
            else:
                properties[field] = {'type': 'keyword'}

        # Non-facet metadata fields
        for field in [
            'resourceId', 'rrid', 'investigatorName', 'institution',
            'orcid', 'howToAcquire', 'latestPublicationDate',
            'biobankName', 'biobankURL', 'contact',
            'completenessCategory', 'availabilityCategory',
            # Computational Tool metadata
            'softwareVersion', 'sourceRepository', 'documentation', 'maintainer',
            # Advanced Cellular Model metadata
            'matrixType', 'maturationTime', 'passageNumber',
            # Patient-Derived Model metadata
            'engraftmentSite', 'establishmentRate', 'clinicalData',
            # Clinical Assessment Tool metadata
            'numberOfItems', 'administrationTime', 'availabilityStatus',
        ]:
            properties[field] = {'type': 'keyword'}

        properties['dateAdded'] = {'type': 'date', 'format': 'epoch_millis||yyyy-MM-dd'}
        properties['dateModified'] = {'type': 'date', 'format': 'epoch_millis||yyyy-MM-dd'}

        return {
            'mappings': {'properties': properties},
            'settings': {
                'number_of_shards': 1,
                'number_of_replicas': 1,
            },
        }

    def build_faceted_query(
        self,
        active_filters: Dict[str, Any],
        text_query: Optional[str] = None,
        size: int = 20,
        from_: int = 0,
        facet_size: int = 100,
    ) -> Dict:
        """
        Build an OpenSearch query with dependent facets.

        Per the OpenSearch faceted search tutorial (Step 4: Filter by facet values):
        - `post_filter` applies ALL active filter selections to the returned hits.
        - Each facet's aggregation applies all OTHER active filters (not its own),
          so that facet continues to show all available options given the other
          selections, not just the currently-selected value.

        Example: active_filters = {"resourceType": "Antibody", "hostOrganism": "Rabbit"}
          - Hits: only Antibody records with hostOrganism=Rabbit
          - `resourceType` agg: filtered by hostOrganism=Rabbit only
            → shows all resource types that have Rabbit host organism records
          - `hostOrganism` agg: filtered by resourceType=Antibody only
            → shows all host organisms available for Antibody records
          - `targetAntigen` agg: filtered by resourceType=Antibody AND hostOrganism=Rabbit
            → shows antigens available for Rabbit Antibody records

        Args:
            active_filters: Dict of field → value (str) or field → [values] (list)
            text_query:     Optional free-text search string
            size:           Number of hits to return
            from_:          Pagination offset
            facet_size:     Max number of buckets per facet aggregation

        Returns:
            OpenSearch query dict ready for the search API
        """
        # Build a term/terms clause for each active filter
        filter_clauses: Dict[str, Dict] = {}
        for field, value in active_filters.items():
            if isinstance(value, list):
                filter_clauses[field] = {'terms': {field: value}}
            else:
                filter_clauses[field] = {'term': {field: value}}

        # post_filter: apply all active selections to restrict returned hits
        post_filter: Optional[Dict] = None
        if filter_clauses:
            must = list(filter_clauses.values())
            post_filter = {'bool': {'must': must}} if len(must) > 1 else must[0]

        # Base query: full-text search or match_all
        if text_query:
            query = {
                'multi_match': {
                    'query': text_query,
                    'fields': TEXT_SEARCH_FIELDS + ['resourceName^3'],
                    'type': 'best_fields',
                    'fuzziness': 'AUTO',
                }
            }
        else:
            query = {'match_all': {}}

        # Aggregations: each facet filters by all OTHER active selections
        aggs: Dict[str, Any] = {}
        for field in ALL_FACET_FIELDS:
            # Filter = all active filters except this field's own filter
            other = [clause for f, clause in filter_clauses.items() if f != field]

            if other:
                agg_filter: Dict = {'bool': {'must': other}} if len(other) > 1 else other[0]
            else:
                agg_filter = {'match_all': {}}

            aggs[f'{field}_agg'] = {
                'filter': agg_filter,
                'aggs': {
                    field: {'terms': {'field': field, 'size': facet_size}}
                },
            }

        result: Dict[str, Any] = {
            'size': size,
            'from': from_,
            'query': query,
            'aggs': aggs,
        }
        if post_filter:
            result['post_filter'] = post_filter

        return result

    def create_index(self, client, index_name: str = DEFAULT_INDEX) -> None:
        """Create the OpenSearch index if it does not already exist."""
        if client.indices.exists(index=index_name):
            logger.info(f'Index "{index_name}" already exists — skipping creation')
            return
        mapping = self.build_index_mapping()
        client.indices.create(index=index_name, body=mapping)
        logger.info(f'Created index "{index_name}"')

    def _clean_row(self, row_items, resource_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Convert a Synapse table row (col→val pairs) to a clean OpenSearch doc.

        - Drops null, NaN, and empty-string values
        - Preserves STRING_LIST columns as Python lists (not stringified)
        - Casts age to int
        - Optionally injects resourceType
        """
        doc: Dict[str, Any] = {}
        for col, val in row_items:
            # Drop nulls
            if val is None:
                continue
            # Drop float NaN
            if isinstance(val, float) and math.isnan(val):
                continue
            # Preserve lists (STRING_LIST columns from Synapse)
            if isinstance(val, list):
                cleaned = [
                    str(v).strip() for v in val
                    if v is not None and str(v).strip().lower() not in ('', 'nan', 'none')
                ]
                if cleaned:
                    doc[col] = cleaned
                continue
            # Scalar values
            s = str(val).strip()
            if s.lower() in ('', 'nan', 'none'):
                continue
            if col == 'age':
                try:
                    doc[col] = int(float(s))
                    continue
                except (ValueError, TypeError):
                    continue
            doc[col] = s

        if resource_type and 'resourceType' not in doc:
            doc['resourceType'] = resource_type

        return doc

    def fetch_from_synapse(self, syn, limit: int = 100_000) -> List[Dict]:
        """
        Fetch all rows from the Tools materialized view (syn51730943).

        Covers the original 5 resource types: Cell Line, Animal Model,
        Antibody, Genetic Reagent, Biobank.

        Returns a list of dicts, one per tool record, with null/NaN values
        stripped so they do not pollute the index.
        """
        logger.info(f'Fetching up to {limit:,} rows from {SOURCE_VIEW_ID}...')
        results = syn.tableQuery(f'SELECT * FROM {SOURCE_VIEW_ID} LIMIT {limit}')
        df = results.asDataFrame()
        logger.info(f'  → {len(df):,} rows fetched')

        docs = []
        for _, row in df.iterrows():
            doc = self._clean_row(row.items())
            if doc:
                docs.append(doc)

        logger.info(f'  → {len(docs):,} non-empty documents prepared')
        return docs

    def fetch_from_new_tables(self, syn, limit: int = 100_000) -> List[Dict]:
        """
        Fetch records from the 4 v2.0 resource type detail tables.

        Each table is queried separately; `resourceType` and `resourceName`
        are injected/normalized per the NEW_RESOURCE_TABLES config so all
        documents share a consistent schema in OpenSearch.

        Returns a combined list of dicts.
        """
        all_docs: List[Dict] = []

        for resource_type, cfg in NEW_RESOURCE_TABLES.items():
            syn_id = cfg['syn_id']
            id_col = cfg['id_col']
            name_col = cfg['name_col']

            logger.info(f'Fetching {resource_type} from {syn_id}...')
            try:
                results = syn.tableQuery(f'SELECT * FROM {syn_id} LIMIT {limit}')
                df = results.asDataFrame()
            except Exception as e:
                logger.warning(f'  Could not fetch {syn_id}: {e} — skipping')
                continue

            logger.info(f'  → {len(df):,} rows fetched')

            docs: List[Dict] = []
            for _, row in df.iterrows():
                doc = self._clean_row(row.items(), resource_type=resource_type)

                # Normalize the type-specific ID column to `resourceId`
                if id_col in doc and 'resourceId' not in doc:
                    doc['resourceId'] = doc.pop(id_col)

                # Normalize the type-specific name column to `resourceName`
                if name_col and name_col in doc and 'resourceName' not in doc:
                    doc['resourceName'] = doc.pop(name_col)

                if doc:
                    docs.append(doc)

            logger.info(f'  → {len(docs):,} documents prepared')
            all_docs.extend(docs)

        return all_docs

    def index_documents(
        self,
        client,
        docs: List[Dict],
        index_name: str = DEFAULT_INDEX,
        batch_size: int = 500,
    ) -> int:
        """Bulk-index documents into OpenSearch. Returns total docs indexed."""
        try:
            from opensearchpy.helpers import bulk as os_bulk
        except ImportError:
            logger.error('opensearch-py required: pip install opensearch-py')
            sys.exit(1)

        actions = [
            {
                '_index': index_name,
                '_id': doc.get('resourceId'),
                '_source': doc,
            }
            for doc in docs
        ]

        total = 0
        for i in range(0, len(actions), batch_size):
            batch = actions[i:i + batch_size]
            success, errors = os_bulk(client, batch, raise_on_error=False)
            total += success
            if errors:
                logger.warning(f'  {len(errors)} errors in batch {i // batch_size + 1}')

        logger.info(f'Indexed {total:,} documents into "{index_name}"')
        return total

    def run(
        self,
        syn,
        client,
        index_name: str = DEFAULT_INDEX,
        dry_run: bool = False,
    ) -> None:
        """Full ETL: fetch from all Synapse sources → create index → bulk index."""
        # Fetch existing 5 resource types from unified MV
        docs = self.fetch_from_synapse(syn)

        # Fetch v2.0 resource types from dedicated tables
        new_docs = self.fetch_from_new_tables(syn)
        docs.extend(new_docs)

        if dry_run:
            rt_counts: Dict[str, int] = {}
            for d in docs:
                rt = d.get('resourceType', 'unknown')
                rt_counts[rt] = rt_counts.get(rt, 0) + 1
            logger.info('[DRY RUN] Would index:')
            for rt, count in sorted(rt_counts.items()):
                logger.info(f'  {rt:30s}: {count:,} documents')
            logger.info(f'  {"TOTAL":30s}: {len(docs):,} documents')
            return

        self.create_index(client, index_name)
        self.index_documents(client, docs, index_name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def make_opensearch_client(host: str):
    try:
        from opensearchpy import OpenSearch
    except ImportError:
        logger.error('opensearch-py required: pip install opensearch-py')
        sys.exit(1)

    # Parse host into scheme/host/port
    scheme = 'https' if host.startswith('https://') else 'http'
    host = host.removeprefix('https://').removeprefix('http://')
    hostname, _, port_str = host.partition(':')
    port = int(port_str) if port_str else (443 if scheme == 'https' else 9200)

    return OpenSearch(
        hosts=[{'host': hostname, 'port': port}],
        http_compress=True,
        use_ssl=(scheme == 'https'),
        verify_certs=False,
    )


def synapse_client():
    import synapseclient
    syn = synapseclient.Synapse()
    token = os.getenv('SYNAPSE_AUTH_TOKEN')
    if token:
        syn.login(authToken=token, silent=True)
    # No login for anonymous access — syn51730943 and the v2.0 tables are open access
    return syn


def main():
    parser = argparse.ArgumentParser(
        description='Index NF Tools (all resource types) into OpenSearch with dependent facets'
    )
    parser.add_argument(
        '--host',
        default='localhost:9200',
        help='OpenSearch host (default: localhost:9200)',
    )
    parser.add_argument(
        '--index',
        default=ToolsOpenSearchIndexer.DEFAULT_INDEX,
        help=f'OpenSearch index name (default: {ToolsOpenSearchIndexer.DEFAULT_INDEX})',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Fetch from Synapse and report document counts without writing to OpenSearch',
    )
    parser.add_argument(
        '--show-query',
        action='store_true',
        help='Print a sample faceted query and exit (no Synapse or OpenSearch needed)',
    )
    parser.add_argument(
        '--filters',
        default='{}',
        help='JSON dict of active filters for --show-query, e.g. \'{"resourceType":"Antibody"}\'',
    )
    args = parser.parse_args()

    indexer = ToolsOpenSearchIndexer()

    # --show-query: just print an example query DSL and exit
    if args.show_query:
        try:
            active_filters = json.loads(args.filters)
        except json.JSONDecodeError as e:
            logger.error(f'Invalid --filters JSON: {e}')
            sys.exit(1)
        query = indexer.build_faceted_query(active_filters)
        print(json.dumps(query, indent=2))
        return

    # Connect to Synapse (anonymous, open access)
    try:
        import synapseclient  # noqa: F401
    except ImportError:
        logger.error('synapseclient required: pip install synapseclient')
        sys.exit(1)

    syn = synapse_client()

    if args.dry_run:
        indexer.run(syn, client=None, index_name=args.index, dry_run=True)
        return

    client = make_opensearch_client(args.host)
    indexer.run(syn, client, index_name=args.index, dry_run=False)


if __name__ == '__main__':
    main()
