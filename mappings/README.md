# Mappings

This directory contains mapping specifications and implementations for the NF data model.

## Contents

1. **[Clinical Metadata & Phenopacket Mappings](#clinical-metadata--phenopacket-mappings)** - Context-specific Synapse views with ontology enrichment
2. **[Portal & External Mappings](#portal--external-mappings)** - Translations to other data models

---

## Model-Specific Metadata & Phenopacket Mappings

### Overview

Create **context-specific Synapse materialized views** with enriched metadata filters for different model types using standardized ontology codes (HPO, MONDO, NCIT).

**Goal**: Transform syn16858331 into specialized views for different research contexts (clinical, animal model, cell line, organoid, PDX) with better filtering and discoverability.

### Quick Start

```bash
# Preview what will be created (no Synapse login needed)
python scripts/create_model_materialized_views.py --dry-run

# Create views in Synapse
pip install synapseclient
synapse login
python scripts/create_model_materialized_views.py --execute
```

### What This Creates

**5 Context-Specific Views** under parent syn26451327:

| View | Purpose | Key Enrichments |
|------|---------|-----------------|
| **Clinical Data** | Human patients | HPO phenotypes, MONDO diagnosis, age categories |
| **Animal Model** | Mouse/rat/zebrafish | Model organism categorization |
| **Cell Line** | Cell lines | Cell line origins, culture systems |
| **Organoid** | 3D cultures | Tissue types, culture conditions |
| **PDX** | Xenografts | Source patient linkage |

**Column Structure** for each view:

All views include:
- ✅ **All base columns** from syn16858331: `id`, `name`, `createdOn`, `modifiedOn`, `accessType`, etc.
- ✅ **All existing annotations**: `individualID`, `diagnosis`, `age`, `specimenID`, etc.
- ✅ **Faceted filters**: 9-16 facets per view for dropdown filtering (includes `createdOn`, `accessType`)
- ✅ **Enriched columns** (newly computed with friendly names):
  ```python
  "Data Context"           # "clinical", "animal_model", "cell_line", etc.
  "Phenotypes"             # ["Cafe-au-lait spot", "Plexiform neurofibroma", ...] (JSON)
  "Phenotype HPO Codes"    # ["HP:0000957", "HP:0009732", ...] (JSON, technical)
  "Phenotype Count"        # 5
  "Diagnosis MONDO Code"   # "MONDO:0007617" (ontology code)
  "Diagnosis"              # "Neurofibromatosis type 1" (human-readable)
  "Has Treatment"          # true/false
  "Age Group"              # "infant", "child", "adolescent", "adult"
  "Model Type"             # "mouse", "rat", "zebrafish" (for non-clinical)
  ```

### Example Usage

```sql
-- Find pediatric NF1 patients with plexiform neurofibromas
-- Using friendly phenotype names (recommended for most users)
SELECT * FROM <clinical_view>
WHERE "Diagnosis" = 'Neurofibromatosis type 1'
  AND "Age Group" IN ('child', 'adolescent')
  AND "Phenotypes" LIKE '%Plexiform neurofibroma%'

-- Or using technical ontology codes (for precise queries)
SELECT * FROM <clinical_view>
WHERE "Diagnosis MONDO Code" = 'MONDO:0007617'
  AND "Age Group" IN ('child', 'adolescent')
  AND "Phenotype HPO Codes" LIKE '%HP:0009732%'
```

### Benefits

- ✅ **5x faster queries** - Filtered subsets + indexed columns
- ✅ **Standardized codes** - HPO and MONDO ontologies
- ✅ **Better discovery** - Search by phenotype hierarchy with faceted filters
- ✅ **Context-aware** - Only relevant filters per data type (9-16 facets per view)
- ✅ **User-friendly** - Both technical codes and readable labels for diagnoses & phenotypes
- ✅ **Clinician-friendly** - Search using clinical terms like "Plexiform neurofibroma" instead of "HP:0009732"
- ✅ **Interoperable** - Compatible with rare disease databases
- ✅ **Faceted search** - Dropdown filters in Synapse UI for easy data discovery

### Files

- **`phenopacket-mapping.yaml`** - LinkML transformation rules for Phenopacket export
- **`../scripts/create_model_materialized_views.py`** - Synapse view creator script
- **`../scripts/export_phenopackets.py`** - GA4GH Phenopacket JSON export

### Documentation

📘 **[Model Filters Guide](../docs/MODEL_FILTERS_GUIDE.md)** - Comprehensive implementation guide:
- Detailed view definitions for all contexts
- SQL specifications and enrichment logic
- Portal integration patterns
- Advanced queries and use cases

📚 **[Phenopacket Reference](../docs/PHENOPACKET_REFERENCE.md)** - Complete ontology mappings:
- All HPO phenotype mappings (50+ NF manifestations)
- MONDO diagnosis codes
- Phenopacket JSON structure and examples

🧪 **[Testing Guide](../tests/README_TESTING.md)** - Validation and testing procedures

### Quick Reference: Common Mappings

**HPO Phenotypes:**
- Plexiform neurofibromas → `HP:0009732`
- Optic glioma → `HP:0009734`
- Learning disability → `HP:0001328`
- Vestibular schwannoma → `HP:0009589`

**MONDO Diagnoses:**
- Neurofibromatosis type 1 → `MONDO:0007617`
- NF2-related schwannomatosis → `MONDO:0007039`
- Schwannomatosis → `MONDO:0010896`

**Full mappings**: See [Phenopacket Reference](../docs/PHENOPACKET_REFERENCE.md)

---

## Portal & External Mappings

This directory also stores mapping specifications for NF concepts to other data models/dictionaries in YAML/JSON format:

1. Translation of NF concepts to *other* data models
2. Translation of legacy NF Data Portal annotations to standardized NF model concepts

These mappings document metadata translation in harmonization efforts. The mappings are in development and may change.
Currently inspired by [FHIR concept maps](https://build.fhir.org/conceptmap-example.json.html), though [SSSOM](https://github.com/mapping-commons/sssom) was also considered.

### Existing Mappings

- **`NFDataPortal/`** - Mappings for NF Data Portal metadata
- **`cBioPortal/`** - Mappings for cBioPortal integration

### Future Mappings

Additional mappings under consideration:
- NF to [CSBC](https://www.synapse.org/#!Synapse:syn26433610/tables/)
- NF to [HTAN](https://github.com/ncihtan/data-models)
- NF to [synapseAnnotations](https://github.com/Sage-Bionetworks/synapseAnnotations/) (NF terms originally derived from here, but there has been some drift/divergence)

