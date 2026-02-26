# NF Tools Central — OpenSearch Indexing Guide

## Overview

`scripts/index_tools_opensearch.py` fetches tool records from Synapse and indexes
them into OpenSearch, enabling unified search across all NF resource types with
**dependent (cascading) faceted filtering**.

Dependent facets mean:
- Selecting `resourceType = "Antibody"` filters results to Antibody records.
- The `targetAntigen` facet then only shows antigens that exist on Antibody records
  (not all possible values across every resource type).
- Each facet stays scoped to the active filters on all *other* facets, not itself.

Implementation follows the [OpenSearch post_filter + filter aggregations pattern](https://docs.opensearch.org/latest/tutorials/faceted-search/#step-4-filter-by-facet-values).

---

## Data Sources

The indexer queries **multiple Synapse tables** and merges them into one OpenSearch
index. This avoids adding more columns to the unified materialized view (syn51730943),
which is near the Synapse 64 KB per-row limit due to existing STRING_LIST columns.

| Resource Type | Synapse ID | Notes |
|---|---|---|
| Cell Line | syn51730943 | Unified MV (5 original types) |
| Animal Model | syn51730943 | — |
| Antibody | syn51730943 | — |
| Genetic Reagent | syn51730943 | — |
| Biobank | syn51730943 | — |
| Computational Tool | syn73709226 | v2.0 dedicated table |
| Advanced Cellular Model | syn73709227 | v2.0 dedicated table |
| Patient-Derived Model | syn73709228 | v2.0 dedicated table |
| Clinical Assessment Tool | syn73709229 | v2.0 dedicated table |

All tables are open access; no Synapse login is required.

### Why separate source tables for v2.0 types?

Adding new resource-type-specific columns to syn51730943 increases the theoretical
max row size for *every* row (including existing types), even when the new columns
are NULL. The v2.0 tables use STRING_LIST columns (e.g., `programmingLanguage`,
`cellTypes`) sized at up to 1,000 bytes each. Adding all four new types' columns
to the unified MV would risk hitting the 64 KB row limit.

OpenSearch has no row size constraint, so it is the right layer to unify sources.

---

## Facet Design

### Common facets (always visible)

| Field | Description |
|---|---|
| `resourceType` | Pivot facet — drives which dependent facets appear |
| `species` | Biological species |
| `usageRequirements` | License / access restrictions |
| `funderName` | Funding organization |

### Dependent facets (per resource type)

| Resource Type | Facets |
|---|---|
| **Cell Line** | `cellLineGeneticDisorder`, `cellLineCategory`, `cellLineManifestation`, `sex`, `age`, `race` |
| **Animal Model** | `animalModelGeneticDisorder`, `animalModelOfManifestation`, `backgroundStrain` |
| **Antibody** | `targetAntigen`, `reactiveSpecies`, `hostOrganism`, `clonality`, `conjugate` |
| **Genetic Reagent** | `insertName`, `vectorType`, `insertSpecies` |
| **Biobank** | `specimenTissueType`, `tumorType`, `specimenFormat`, `specimenPreparationMethod`, `specimenType` |
| **Computational Tool** | `softwareType`, `programmingLanguage`¹, `licenseType`, `containerized` |
| **Advanced Cellular Model** | `modelType`, `derivationSource`, `organoidType`, `cultureSystem` |
| **Patient-Derived Model** | `modelSystemType`, `patientDiagnosis`, `tumorType`, `engraftmentSite`, `hostStrain` |
| **Clinical Assessment Tool** | `assessmentType`, `targetPopulation`, `diseaseSpecific`, `scoringMethod` |

¹ `programmingLanguage` is a STRING_LIST in Synapse (multi-value). OpenSearch stores
it as a keyword array, so `terms` aggregations and filtering work without special handling.

---

## Field Schema

### Common document fields (all resource types)

| Field | OpenSearch type | Notes |
|---|---|---|
| `resourceId` | keyword | Document `_id`; normalized from type-specific ID columns for v2.0 types |
| `resourceName` | text + keyword | Normalized from `softwareName`/`assessmentName` for v2.0 types |
| `synonyms` | text + keyword | Full-text searchable |
| `description` | text + keyword | Full-text searchable |
| `resourceType` | keyword | One of the 9 resource type values |
| `species` | keyword | Facet |
| `usageRequirements` | keyword | Facet |
| `funderName` | keyword | Facet |
| `dateAdded` | date | epoch_millis or yyyy-MM-dd |
| `dateModified` | date | epoch_millis or yyyy-MM-dd |

### v2.0 resource type fields

Fields are indexed as-is from each source table. The type-specific ID and name columns
are renamed during ingest:

| Source column | Becomes |
|---|---|
| `computationalToolId` | `resourceId` |
| `advancedCellularModelId` | `resourceId` |
| `patientDerivedModelId` | `resourceId` |
| `clinicalAssessmentToolId` | `resourceId` |
| `softwareName` | `resourceName` |
| `assessmentName` | `resourceName` |

---

## Running the Indexer

```bash
# Dry run — shows document counts per resource type, no writes
python scripts/index_tools_opensearch.py --dry-run

# Index into a running OpenSearch instance
python scripts/index_tools_opensearch.py --host localhost:9200

# Custom index name
python scripts/index_tools_opensearch.py --host localhost:9200 --index nf-tools

# Print a sample query DSL for given active filters (no Synapse or OpenSearch needed)
python scripts/index_tools_opensearch.py --show-query --filters '{"resourceType":"Antibody"}'

# Show query for multiple active filters
python scripts/index_tools_opensearch.py \
  --show-query \
  --filters '{"resourceType":"Antibody","hostOrganism":"Rabbit"}'
```

### Environment variables

| Variable | Description |
|---|---|
| `SYNAPSE_AUTH_TOKEN` | Optional. Only needed if tables require authentication. All current sources are open access. |

### Dependencies

```bash
pip install synapseclient opensearch-py pandas
```

---

## How Dependent Facets Work

The query pattern uses `post_filter` for search hits and per-facet `filter`
aggregations with all *other* active filters applied:

```
active_filters = { "resourceType": "Antibody", "hostOrganism": "Rabbit" }

Hits:            restricted by resourceType=Antibody AND hostOrganism=Rabbit

resourceType agg: filtered by hostOrganism=Rabbit only
  → shows all resource types that have Rabbit host organism records

hostOrganism agg: filtered by resourceType=Antibody only
  → shows all host organisms available for Antibody records

targetAntigen agg: filtered by resourceType=Antibody AND hostOrganism=Rabbit
  → shows antigens available in Rabbit Antibody records
```

The portal UI should additionally render dependent facets only when the corresponding
`resourceType` is selected, since those fields are only populated for their
respective resource types.

---

## Adding a New Resource Type

1. **Add an entry to `NEW_RESOURCE_TABLES`** in `index_tools_opensearch.py`:

```python
NEW_RESOURCE_TABLES: Dict[str, Dict] = {
    ...
    'My New Type': {
        'syn_id': 'synXXXXXXXX',   # Synapse table ID
        'id_col': 'myNewTypeId',    # Primary key column
        'name_col': 'myName',       # Display name column (or None)
    },
}
```

2. **Add dependent facets** to `DEPENDENT_FACETS`:

```python
DEPENDENT_FACETS: Dict[str, List[str]] = {
    ...
    'My New Type': [
        'fieldOne',
        'fieldTwo',
    ],
}
```

3. **Run dry-run** to confirm document counts:

```bash
python scripts/index_tools_opensearch.py --dry-run
```

4. **Re-index** to update OpenSearch:

```bash
python scripts/index_tools_opensearch.py --host localhost:9200
```

---

## Relationship to Synapse Materialized Views

The Tools search uses a different strategy than the Files search tab:

| Aspect | Files tab | Tools tab |
|---|---|---|
| Synapse source | Per-model materialized views (clinical, animal_model, cell_line, organoid, pdx) | syn51730943 unified MV + dedicated per-type tables |
| Search backend | MySQL full-text (current) → OpenSearch (planned) | OpenSearch |
| Dependent facets | Not yet implemented | Implemented via post_filter + filter aggs |
| Row limit concern | Managed via separate views | Avoided by not adding new columns to syn51730943 |

See `docs/MODEL_FILTERS_GUIDE.md` for the Files tab Synapse materialized view architecture.

---

## Sample Query Output

```bash
python scripts/index_tools_opensearch.py \
  --show-query --filters '{"resourceType":"Antibody","hostOrganism":"Rabbit"}'
```

```json
{
  "size": 20,
  "from": 0,
  "query": { "match_all": {} },
  "post_filter": {
    "bool": {
      "must": [
        { "term": { "resourceType": "Antibody" } },
        { "term": { "hostOrganism": "Rabbit" } }
      ]
    }
  },
  "aggs": {
    "resourceType_agg": {
      "filter": { "term": { "hostOrganism": "Rabbit" } },
      "aggs": { "resourceType": { "terms": { "field": "resourceType", "size": 100 } } }
    },
    "hostOrganism_agg": {
      "filter": { "term": { "resourceType": "Antibody" } },
      "aggs": { "hostOrganism": { "terms": { "field": "hostOrganism", "size": 100 } } }
    },
    "targetAntigen_agg": {
      "filter": {
        "bool": {
          "must": [
            { "term": { "resourceType": "Antibody" } },
            { "term": { "hostOrganism": "Rabbit" } }
          ]
        }
      },
      "aggs": { "targetAntigen": { "terms": { "field": "targetAntigen", "size": 100 } } }
    }
  }
}
```
