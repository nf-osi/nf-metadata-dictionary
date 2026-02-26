# NF Files Search Tab — OpenSearch Indexing Guide

## Overview

`scripts/index_files_opensearch.py` fetches enriched NF file metadata from the
5 per-model Synapse materialized views and indexes them into OpenSearch, enabling
unified search across all biological model types with **dependent (cascading)
faceted filtering**.

The 5 Synapse views are created by `scripts/create_model_materialized_views.py`.
Each view covers one biological model context and contains both raw annotations
from `syn16858331` and enriched computed columns (Diagnosis, NF Type, NF1/NF2
Genotype, Age Group, etc.) added by `ModelMetadataEnricher`.

Dependent facets mean:
- Selecting `Data Context = "clinical"` filters results to clinical records.
- The `Diagnosis` facet then only shows diagnoses that exist in clinical records.
- Each facet stays scoped to the active filters on all *other* facets, not itself.

Implementation follows the [OpenSearch post_filter + filter aggregations pattern](https://docs.opensearch.org/latest/tutorials/faceted-search/#step-4-filter-by-facet-values).

---

## Two-Script Workflow

```
scripts/create_model_materialized_views.py   →   Synapse materialized views
                                                         ↓
scripts/index_files_opensearch.py            →   OpenSearch index `nf-files`
```

**Step 1 — Create Synapse views** (requires write access to syn26451327):
```bash
python scripts/create_model_materialized_views.py --execute
# Outputs: Synapse IDs for each created view
```

**Step 2 — Index into OpenSearch** (supply IDs from step 1):
```bash
python scripts/index_files_opensearch.py \
    --view-ids '{"clinical":"synAAA","animal_model":"synBBB","cell_line":"synCCC","organoid":"synDDD","pdx":"synEEE"}' \
    --host localhost:9200
```

Or update `SOURCE_VIEWS` in `index_files_opensearch.py` with the IDs and omit `--view-ids`.

---

## Data Sources

| View Type | View Name in Synapse | Source |
|---|---|---|
| `clinical` | NF Clinical Data - Enriched Filters | syn16858331 (human patients, HPO phenotypes) |
| `animal_model` | NF Animal Model Data - Enriched Filters | syn16858331 (mouse/rat/zebrafish experiments) |
| `cell_line` | NF Cell Line Data - Enriched Filters | syn16858331 (in vitro cell systems) |
| `organoid` | NF Organoid Data - Enriched Filters | syn16858331 (organoids and spheroids) |
| `pdx` | NF PDX Data - Enriched Filters | syn16858331 (patient-derived xenografts) |

All views are created under parent folder `syn26451327`. View IDs are assigned
dynamically at creation time (no hardcoded IDs in the scripts).

### Source filter logic

| View type | Synapse SQL `WHERE` clause |
|---|---|
| `clinical` | `species = 'Homo sapiens'` AND not a cell line or xenograft AND no model system name |
| `animal_model` | `species IN ('Mus musculus', 'Rattus norvegicus', 'Danio rerio')` OR model system name present (not cell line or xenograft) |
| `cell_line` | `isCellLine = true` OR `specimenType IN ('cell line', 'iPSC', 'induced pluripotent stem cell')` |
| `organoid` | `specimenType LIKE '%organoid%'` OR `specimenType LIKE '%spheroid%'` |
| `pdx` | `isXenograft = true` OR model system name contains 'PDX'/'xenograft' OR specimen type contains 'xenograft' |

---

## Enriched Columns

`ModelMetadataEnricher` computes these columns for every view row:

| Column | Views | Description |
|---|---|---|
| `Data Context` | all | Model type: `clinical` / `animal_model` / `cell_line` / `organoid` / `pdx` |
| `Diagnosis` | all | Canonical disease label (NF1 synonyms unified to "Neurofibromatosis type 1", etc.) |
| `Diagnosis MONDO Code` | all | MONDO ontology code (e.g. MONDO:0007617) |
| `Diagnosis NCIT Code` | all | NCIT code for diagnosis |
| `NF1 Genotype` | all | Normalized allele notation (e.g. `+/-`, `-/-`, `Unknown`) |
| `NF2 Genotype` | all | Normalized allele notation |
| `Data Type` | all | Normalized data type (e.g. "drug screen" from "drugScreen") |
| `Has Treatment` | all | `"True"` / `"False"` — whether treatment context is present |
| `Age Group` | all | `infant` / `child` / `adolescent` / `adult` |
| `Model Type` | animal_model | `mouse` / `rat` / `zebrafish` / `drosophila` / `other` |
| `NF Type` | animal_model, cell_line, organoid, pdx | NF disease subtype from diagnosis |
| `Tissue of Origin` | cell_line | Tissue source (from tissue column or NF Tools Central cross-reference) |
| `Phenotypes` | clinical | JSON array of HPO phenotype labels (mapped from `tumorType`); parsed to list in OpenSearch |
| `Phenotype HPO Codes` | clinical | JSON array of HPO codes |
| `Phenotype Count` | clinical | Number of distinct phenotypes detected (integer; supports range queries) |
| `Tumor Type NCIT Codes` | clinical | JSON array of NCIT codes for tumor manifestations |
| `Tumor Type MONDO Codes` | clinical | JSON array of MONDO disease codes for manifestations |
| `Tumor Type OMIM Codes` | clinical | JSON array of OMIM codes for manifestations |

### JSON array fields

The following columns are stored as JSON array strings in Synapse (e.g.
`'["Plexiform neurofibroma", "Optic nerve glioma"]'`) and are automatically parsed
into Python lists on ingest so OpenSearch can use them for per-value term aggregations:

- `Phenotypes`
- `Phenotype HPO Codes`
- `Tumor Type NCIT Codes`
- `Tumor Type MONDO Codes`
- `Tumor Type OMIM Codes`

---

## Facet Design

### Common facets (always visible)

| Field | Description |
|---|---|
| `Data Context` | Pivot facet — drives which dependent facets appear |
| `Data Type` | Normalized experiment/data type |
| `assay` | Assay technique |
| `NF1 Genotype` | NF1 allele status |
| `NF2 Genotype` | NF2 allele status |
| `accessType` | Open / Controlled access |

### Dependent facets (per Data Context)

| Data Context | Facets |
|---|---|
| **clinical** | `Diagnosis`, `Diagnosis MONDO Code`, `Phenotypes`¹, `Age Group`, `Has Treatment`, `sex`, `species`, `vitalStatus` |
| **animal_model** | `NF Type`, `Diagnosis`, `Model Type`, `species`, `genePerturbed`, `genePerturbationType`, `Has Treatment` |
| **cell_line** | `NF Type`, `Diagnosis`, `Tissue of Origin`, `tumorType`, `sex`, `cellType`, `Has Treatment` |
| **organoid** | `NF Type`, `Diagnosis`, `tumorType` |
| **pdx** | `NF Type`, `Diagnosis`, `transplantationType`, `tumorType`, `species` |

¹ `Phenotypes` is a multi-value keyword field (parsed from JSON array). Each phenotype value
is indexed as a separate keyword, so individual phenotype filtering works as a `terms` query.

---

## Running the Indexer

```bash
# Dry run — shows document counts per model type, no writes
python scripts/index_files_opensearch.py --dry-run \
    --view-ids '{"clinical":"synAAA","animal_model":"synBBB","cell_line":"synCCC","organoid":"synDDD","pdx":"synEEE"}'

# Index one view type only (omit the others from --view-ids)
python scripts/index_files_opensearch.py \
    --view-ids '{"clinical":"synAAA"}' \
    --host localhost:9200

# Index all views using hardcoded SOURCE_VIEWS (update the dict in the script first)
python scripts/index_files_opensearch.py --host localhost:9200

# Custom index name
python scripts/index_files_opensearch.py \
    --view-ids '...' --host localhost:9200 --index nf-files-staging

# Print a sample query DSL without Synapse or OpenSearch
python scripts/index_files_opensearch.py \
    --show-query --filters '{"Data Context":"clinical","Diagnosis":"Neurofibromatosis type 1"}'
```

### Environment variables

| Variable | Description |
|---|---|
| `SYNAPSE_AUTH_TOKEN` | Synapse personal access token. Required if the materialized views are not publicly readable. |

### Dependencies

```bash
pip install synapseclient opensearch-py pandas
```

---

## How Dependent Facets Work

```
active_filters = { "Data Context": "clinical", "Diagnosis": "Neurofibromatosis type 1" }

Hits:              restricted by Data Context=clinical AND Diagnosis=NF1

Data Context agg:  filtered by Diagnosis=NF1 only
  → shows all model types that have NF1 diagnosis records

Diagnosis agg:     filtered by Data Context=clinical only
  → shows all diagnoses available in clinical records

Age Group agg:     filtered by Data Context=clinical AND Diagnosis=NF1
  → shows age groups in clinical NF1 records

NF Type agg:       filtered by Data Context=clinical AND Diagnosis=NF1
  → will be empty (NF Type only populated for non-clinical types)
```

The portal UI should additionally render dependent facets only when the
corresponding `Data Context` is selected, since those fields are only populated
for their respective model types.

---

## Sample Query Output

```bash
python scripts/index_files_opensearch.py \
  --show-query \
  --filters '{"Data Context":"clinical","Diagnosis":"Neurofibromatosis type 1"}'
```

```json
{
  "size": 20,
  "from": 0,
  "query": { "match_all": {} },
  "post_filter": {
    "bool": {
      "must": [
        { "term": { "Data Context": "clinical" } },
        { "term": { "Diagnosis": "Neurofibromatosis type 1" } }
      ]
    }
  },
  "aggs": {
    "Data_Context_agg": {
      "filter": { "term": { "Diagnosis": "Neurofibromatosis type 1" } },
      "aggs": { "Data Context": { "terms": { "field": "Data Context", "size": 100 } } }
    },
    "Diagnosis_agg": {
      "filter": { "term": { "Data Context": "clinical" } },
      "aggs": { "Diagnosis": { "terms": { "field": "Diagnosis", "size": 100 } } }
    },
    "Age_Group_agg": {
      "filter": {
        "bool": {
          "must": [
            { "term": { "Data Context": "clinical" } },
            { "term": { "Diagnosis": "Neurofibromatosis type 1" } }
          ]
        }
      },
      "aggs": { "Age Group": { "terms": { "field": "Age Group", "size": 100 } } }
    }
  }
}
```

---

## Adding a New Model Type

1. **Create the Synapse materialized view** in `create_model_materialized_views.py`:
   - Add a `create_<type>_view()` method with SQL filter and enriched columns
   - Add to `create_all_views()`

2. **Add dependent facets** to `DEPENDENT_FACETS` in `index_files_opensearch.py`:
   ```python
   DEPENDENT_FACETS['my_new_type'] = [
       'NF Type',
       'Diagnosis',
       'someNewField',
   ]
   ```

3. **Add a view ID placeholder** to `SOURCE_VIEWS`:
   ```python
   SOURCE_VIEWS['my_new_type'] = ''  # Set after view creation
   ```

4. **Run dry-run** after creating the view to confirm document counts:
   ```bash
   python scripts/index_files_opensearch.py --dry-run \
       --view-ids '{"my_new_type":"synXXX"}'
   ```

---

## Relationship to Other Search Tabs

| Aspect | Files tab | Tools tab |
|---|---|---|
| Script | `index_files_opensearch.py` | `index_tools_opensearch.py` |
| Documentation | This file | `TOOLS_OPENSEARCH_GUIDE.md` |
| OpenSearch index | `nf-files` | `nf-tools` |
| Pivot facet | `Data Context` | `resourceType` |
| Synapse sources | 5 enriched materialized views (per model type) | syn51730943 + 4 dedicated tables |
| Enriched columns | Yes — HPO/MONDO codes, NF Type, Age Group, etc. | No — raw annotations from source tables |
| Synapse view IDs | Dynamic (created by `create_model_materialized_views.py`) | Fixed (syn51730943 + syn737092xx) |

The Synapse views for the Files tab exist primarily as **ETL sources** for the
OpenSearch index — their row size constraints are managed by keeping them
model-type-specific (one view per context). The OpenSearch index merges all 5
into a single unified search layer.

See `docs/MODEL_FILTERS_GUIDE.md` for the Synapse materialized view architecture
and enrichment logic (HPO/MONDO mappings, genotype normalization, etc.).
