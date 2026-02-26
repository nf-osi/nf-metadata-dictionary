#!/usr/bin/env python3
"""
Index the NF Files search tab (5 per-model Synapse materialized views) into
OpenSearch, enabling unified search with dependent faceted filtering.

Dependent facets follow the OpenSearch post_filter + filter aggregations pattern:
https://docs.opensearch.org/latest/tutorials/faceted-search/#step-4-filter-by-facet-values

How dependent facets work here:
  - `Data Context` is the pivot facet. Selecting "clinical" filters results to
    clinical records only.
  - Each facet's aggregation applies all OTHER active filters (not its own), so:
      - The `Data Context` agg always shows all model type counts (unfiltered by itself)
      - The `Diagnosis` agg is filtered by the active `Data Context` selection,
        so it only shows diagnoses from clinical records when "clinical" is selected
  - Dependent facets (e.g. `Tissue of Origin` for cell_line) are naturally scoped
    because those columns are only populated for their respective model types.

Data sources — 5 Synapse materialized views created by create_model_materialized_views.py:
  clinical       Clinical (human patient) data with HPO phenotypes, MONDO codes
  animal_model   Mouse/rat/zebrafish model organism experiments
  cell_line      In vitro cell line and iPSC data
  organoid       Organoid and spheroid culture data
  pdx            Patient-derived xenograft (PDX) data

All 5 views are sourced from syn16858331 (NF entity view) and enriched with
computed columns (Diagnosis, NF Type, NF1/NF2 Genotype, Data Type, Age Group,
Has Treatment, Tissue of Origin, etc.) by ModelMetadataEnricher.

View IDs:
  View IDs are created dynamically by create_model_materialized_views.py and
  must be provided at runtime via --view-ids or by updating SOURCE_VIEWS in
  this file after view creation.

Usage:
    # Dry run — shows document counts per model type, no writes
    python scripts/index_files_opensearch.py --dry-run \\
        --view-ids '{"clinical":"synAAA","animal_model":"synBBB","cell_line":"synCCC","organoid":"synDDD","pdx":"synEEE"}'

    # Index into a running OpenSearch instance
    python scripts/index_files_opensearch.py \\
        --view-ids '{"clinical":"synAAA",...}' \\
        --host localhost:9200

    # Use hardcoded SOURCE_VIEWS (after updating them in this file)
    python scripts/index_files_opensearch.py --host localhost:9200

    # Print a sample query for given active filters (no Synapse or OpenSearch needed)
    python scripts/index_files_opensearch.py \\
        --show-query --filters '{"Data Context":"clinical","Diagnosis":"Neurofibromatosis type 1"}'
"""

import argparse
import json
import logging
import math
import os
import sys
from typing import Any, Dict, List, Optional, Set

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source views
# ---------------------------------------------------------------------------

# Update these IDs after running:
#   python scripts/create_model_materialized_views.py --execute
# Or supply them at runtime via --view-ids.
SOURCE_VIEWS: Dict[str, str] = {
    'clinical':     '',   # NF Clinical Data - Enriched Filters
    'animal_model': '',   # NF Animal Model Data - Enriched Filters
    'cell_line':    '',   # NF Cell Line Data - Enriched Filters
    'organoid':     '',   # NF Organoid Data - Enriched Filters
    'pdx':          '',   # NF PDX Data - Enriched Filters
}

# ---------------------------------------------------------------------------
# Facet definitions
# ---------------------------------------------------------------------------

# Fields stored as JSON array strings in Synapse (e.g. '["NF1", "NF2"]').
# These are parsed into Python lists on ingest for proper OpenSearch multi-value
# keyword indexing and per-value term aggregations.
JSON_ARRAY_FIELDS: Set[str] = {
    'Phenotypes',
    'Phenotype HPO Codes',
    'Tumor Type NCIT Codes',
    'Tumor Type MONDO Codes',
    'Tumor Type OMIM Codes',
}

# Always-visible facets regardless of Data Context selection.
COMMON_FACETS: List[str] = [
    'Data Context',      # pivot — clinical / animal_model / cell_line / organoid / pdx
    'Data Type',         # enriched, normalized dataType
    'assay',
    'NF1 Genotype',      # enriched, normalized nf1Genotype
    'NF2 Genotype',      # enriched, normalized nf2Genotype
    'accessType',
]

# Facets only meaningful (and only populated) for a specific Data Context.
# The portal UI should render these only when the corresponding Data Context
# is active; OpenSearch will naturally return empty buckets for unrelated records.
DEPENDENT_FACETS: Dict[str, List[str]] = {
    'clinical': [
        'Diagnosis',
        'Diagnosis MONDO Code',
        'Phenotypes',          # JSON array → multi-value keyword in OpenSearch
        'Age Group',
        'Has Treatment',
        'sex',
        'species',
        'vitalStatus',
    ],
    'animal_model': [
        'NF Type',
        'Diagnosis',
        'Model Type',
        'species',
        'genePerturbed',
        'genePerturbationType',
        'Has Treatment',
    ],
    'cell_line': [
        'NF Type',
        'Diagnosis',
        'Tissue of Origin',
        'tumorType',
        'sex',
        'cellType',
        'Has Treatment',
    ],
    'organoid': [
        'NF Type',
        'Diagnosis',
        'tumorType',
    ],
    'pdx': [
        'NF Type',
        'Diagnosis',
        'transplantationType',
        'tumorType',
        'species',
    ],
}

# Flat deduplicated list of all facet fields (common + all dependent).
ALL_FACET_FIELDS: List[str] = COMMON_FACETS + list(dict.fromkeys(
    f for facets in DEPENDENT_FACETS.values() for f in facets
))

# Fields that should be full-text searchable in addition to keyword filtering.
TEXT_SEARCH_FIELDS: List[str] = [
    'name',       # Synapse entity/file name
    'assay',
    'dataType',
    'Diagnosis',
]

# ---------------------------------------------------------------------------
# Indexer class
# ---------------------------------------------------------------------------

class FilesOpenSearchIndexer:
    """
    Fetches enriched NF Files metadata from the 5 per-model Synapse materialized
    views and indexes them into OpenSearch with dependent faceted search.
    """

    DEFAULT_INDEX = 'nf-files'

    def build_index_mapping(self) -> Dict:
        """
        Return the OpenSearch index mapping.

        - Facet fields: `keyword` type (exact aggregations/filters).
          Multi-value fields (JSON arrays parsed to lists) also use keyword —
          OpenSearch handles arrays natively.
        - Text-searchable fields: `text` type with `keyword` sub-field.
        - Integer fields: `Phenotype Count` (range queries).
        - Boolean fields: `Has Treatment` stored as string "True"/"False"
          from Synapse; mapped as keyword for consistency.
        - Date fields: Synapse epoch millis or ISO date strings.
        """
        properties: Dict[str, Any] = {}

        # Text-searchable fields
        for field in TEXT_SEARCH_FIELDS:
            properties[field] = {
                'type': 'text',
                'fields': {'keyword': {'type': 'keyword', 'ignore_above': 512}},
            }

        # Facet fields (keyword)
        for field in ALL_FACET_FIELDS:
            properties[field] = {'type': 'keyword'}

        # Numeric facets
        properties['Phenotype Count'] = {'type': 'integer'}

        # Synapse system / metadata fields
        for field in [
            'id', 'name', 'createdBy', 'modifiedBy', 'type',
            'parentId', 'projectId', 'benefactorId', 'etag',
            'versionNumber', 'versionLabel', 'currentVersion',
            'fileFormat', 'dataFileHandleId',
            # raw annotation pass-throughs
            'nf1Genotype', 'nf2Genotype', 'individualID',
            'specimenID', 'specimenType', 'tissue', 'cellType',
            'tumorType', 'diagnosis', 'species', 'sex',
            'modelSystemName', 'transplantationType', 'vitalStatus',
            'genePerturbed', 'genePerturbationType',
            'Diagnosis NCIT Code',
            'Phenotype HPO Codes',
            'Tumor Type NCIT Codes', 'Tumor Type MONDO Codes', 'Tumor Type OMIM Codes',
        ]:
            properties.setdefault(field, {'type': 'keyword'})

        properties['createdOn'] = {'type': 'date', 'format': 'epoch_millis||strict_date_optional_time'}
        properties['modifiedOn'] = {'type': 'date', 'format': 'epoch_millis||strict_date_optional_time'}

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

        Example: active_filters = {"Data Context": "clinical", "Diagnosis": "NF1"}
          - Hits: only clinical records with Diagnosis=NF1
          - `Data Context` agg: filtered by Diagnosis=NF1 only
            → shows all model types that have NF1 diagnosis records
          - `Diagnosis` agg: filtered by Data Context=clinical only
            → shows all diagnoses for clinical records
          - `Age Group` agg: filtered by Data Context=clinical AND Diagnosis=NF1
            → shows age groups for clinical NF1 records

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
                    'fields': TEXT_SEARCH_FIELDS + ['name^3'],
                    'type': 'best_fields',
                    'fuzziness': 'AUTO',
                }
            }
        else:
            query = {'match_all': {}}

        # Aggregations: each facet filters by all OTHER active selections
        aggs: Dict[str, Any] = {}
        for field in ALL_FACET_FIELDS:
            other = [clause for f, clause in filter_clauses.items() if f != field]

            if other:
                agg_filter: Dict = {'bool': {'must': other}} if len(other) > 1 else other[0]
            else:
                agg_filter = {'match_all': {}}

            # Sanitize field name for the aggregation key (replace spaces with underscores)
            agg_key = field.replace(' ', '_').replace('/', '_')
            aggs[f'{agg_key}_agg'] = {
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

    def _parse_value(self, col: str, val: Any) -> Any:
        """
        Convert a Synapse cell value to an OpenSearch-ready Python value.

        - Returns None for nulls, NaN, empty strings.
        - Parses JSON array strings (Phenotypes, HPO codes, etc.) into lists.
        - Preserves Synapse STRING_LIST columns (already lists) as lists.
        - Casts Phenotype Count to int.
        """
        if val is None:
            return None
        if isinstance(val, float) and math.isnan(val):
            return None

        # Preserve lists (Synapse STRING_LIST columns)
        if isinstance(val, list):
            cleaned = [
                str(v).strip() for v in val
                if v is not None and str(v).strip().lower() not in ('', 'nan', 'none')
            ]
            return cleaned if cleaned else None

        s = str(val).strip()
        if s.lower() in ('', 'nan', 'none'):
            return None

        # Parse JSON array strings
        if col in JSON_ARRAY_FIELDS and s.startswith('['):
            try:
                parsed = json.loads(s.replace("'", '"'))
                cleaned = [str(x).strip() for x in parsed if str(x).strip()]
                return cleaned if cleaned else None
            except (json.JSONDecodeError, TypeError):
                # Fallback: strip brackets and split on commas
                inner = s.strip('[]')
                parts = [p.strip().strip('\'"') for p in inner.split(',')]
                cleaned = [p for p in parts if p]
                return cleaned if cleaned else None

        # Numeric fields
        if col == 'Phenotype Count':
            try:
                return int(float(s))
            except (ValueError, TypeError):
                return None

        return s

    def fetch_from_view(
        self,
        syn,
        view_type: str,
        view_id: str,
        limit: int = 1_000_000,
    ) -> List[Dict]:
        """
        Fetch all rows from one materialized view and return as cleaned docs.

        Injects `Data Context` from view_type if not already present in the row.
        """
        logger.info(f'Fetching {view_type} from {view_id}...')
        try:
            results = syn.tableQuery(f'SELECT * FROM {view_id} LIMIT {limit}')
            df = results.asDataFrame()
        except Exception as e:
            logger.warning(f'  Could not fetch {view_id}: {e} — skipping')
            return []

        logger.info(f'  → {len(df):,} rows fetched')

        docs: List[Dict] = []
        for _, row in df.iterrows():
            doc: Dict[str, Any] = {}
            for col, val in row.items():
                parsed = self._parse_value(col, val)
                if parsed is not None:
                    doc[col] = parsed

            # Inject Data Context from view_type if enrichment didn't set it
            if 'Data Context' not in doc:
                doc['Data Context'] = view_type

            if doc:
                docs.append(doc)

        logger.info(f'  → {len(docs):,} documents prepared')
        return docs

    def fetch_all(
        self,
        syn,
        view_ids: Dict[str, str],
        limit: int = 1_000_000,
    ) -> List[Dict]:
        """Fetch from all provided views and return combined document list."""
        all_docs: List[Dict] = []
        for view_type, view_id in view_ids.items():
            if not view_id:
                logger.warning(f'No view ID for {view_type} — skipping')
                continue
            docs = self.fetch_from_view(syn, view_type, view_id, limit)
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
                '_id': doc.get('id'),          # Synapse entity ID (e.g. syn12345)
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
        view_ids: Dict[str, str],
        index_name: str = DEFAULT_INDEX,
        dry_run: bool = False,
    ) -> None:
        """Full ETL: fetch from all Synapse views → create index → bulk index."""
        docs = self.fetch_all(syn, view_ids)

        if dry_run:
            ctx_counts: Dict[str, int] = {}
            for d in docs:
                ctx = d.get('Data Context', 'unknown')
                ctx_counts[ctx] = ctx_counts.get(ctx, 0) + 1
            logger.info('[DRY RUN] Would index:')
            for ctx, count in sorted(ctx_counts.items()):
                logger.info(f'  {ctx:20s}: {count:,} documents')
            logger.info(f'  {"TOTAL":20s}: {len(docs):,} documents')
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
    return syn


def resolve_view_ids(cli_arg: Optional[str]) -> Dict[str, str]:
    """Merge SOURCE_VIEWS defaults with any CLI overrides."""
    ids = dict(SOURCE_VIEWS)
    if cli_arg:
        try:
            overrides = json.loads(cli_arg)
        except json.JSONDecodeError as e:
            logger.error(f'Invalid --view-ids JSON: {e}')
            sys.exit(1)
        ids.update(overrides)
    return ids


def main():
    parser = argparse.ArgumentParser(
        description='Index NF Files materialized views into OpenSearch with dependent facets'
    )
    parser.add_argument(
        '--view-ids',
        metavar='JSON',
        help=(
            'JSON dict mapping view type to Synapse ID, e.g. '
            '\'{"clinical":"synAAA","animal_model":"synBBB",...}\'. '
            'Overrides or supplements SOURCE_VIEWS defaults in this script.'
        ),
    )
    parser.add_argument(
        '--host',
        default='localhost:9200',
        help='OpenSearch host (default: localhost:9200)',
    )
    parser.add_argument(
        '--index',
        default=FilesOpenSearchIndexer.DEFAULT_INDEX,
        help=f'OpenSearch index name (default: {FilesOpenSearchIndexer.DEFAULT_INDEX})',
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
        help=(
            'JSON dict of active filters for --show-query, e.g. '
            '\'{"Data Context":"clinical","Diagnosis":"Neurofibromatosis type 1"}\''
        ),
    )
    args = parser.parse_args()

    indexer = FilesOpenSearchIndexer()

    if args.show_query:
        try:
            active_filters = json.loads(args.filters)
        except json.JSONDecodeError as e:
            logger.error(f'Invalid --filters JSON: {e}')
            sys.exit(1)
        query = indexer.build_faceted_query(active_filters)
        print(json.dumps(query, indent=2))
        return

    try:
        import synapseclient  # noqa: F401
    except ImportError:
        logger.error('synapseclient required: pip install synapseclient')
        sys.exit(1)

    view_ids = resolve_view_ids(args.view_ids)
    active_views = {k: v for k, v in view_ids.items() if v}
    if not active_views:
        logger.error(
            'No view IDs configured. Either update SOURCE_VIEWS in this script '
            'or pass --view-ids \'{"clinical":"synXXX",...}\''
        )
        sys.exit(1)

    syn = synapse_client()

    if args.dry_run:
        indexer.run(syn, client=None, view_ids=active_views, index_name=args.index, dry_run=True)
        return

    client = make_opensearch_client(args.host)
    indexer.run(syn, client, view_ids=active_views, index_name=args.index, dry_run=False)


if __name__ == '__main__':
    main()
