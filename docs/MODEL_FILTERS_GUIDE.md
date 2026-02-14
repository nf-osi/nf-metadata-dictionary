# Synapse Clinical Materialized Views - Implementation Guide

## Overview

This guide describes how to create context-specific Synapse materialized views with enriched clinical metadata filters, inspired by GA4GH Phenopacket structure.

**Goal**: Create multiple materialized views from the main entity view (syn16858331) with context-specific filters for:
- Clinical data (human patients)
- Animal model data
- Cell line data
- Advanced cellular models (organoids)
- Patient-derived systems (PDX)

**Parent Folder**: syn26451327
**Source View**: syn16858331 (primary key: id)
**Existing General View**: syn52702673

---

## Architecture

### Current State
```
syn16858331 (Entity View)
    │
    ├─► syn52702673 (General materialized view - all data types)
    └─► [New] Context-specific views with enriched filters
```

### Proposed Architecture
```
syn16858331 (Entity View - Source)
    │
    ├─► syn52702673 (General view - UNCHANGED)
    │
    └─► syn26451327 (Parent folder)
         ├─► Clinical Data View (NEW)
         │   └─ Filters: Human patients, HPO phenotypes, MONDO codes
         ├─► Animal Model View (NEW)
         │   └─ Filters: Mouse/rat/zebrafish, model systems
         ├─► Cell Line View (NEW)
         │   └─ Filters: Established cell lines, iPSCs
         ├─► Organoid View (NEW)
         │   └─ Filters: Organoids, spheroids
         └─► PDX View (NEW)
             └─ Filters: Patient-derived xenografts
```

---

## Enriched Metadata Columns

Each context-specific view includes these additional computed columns:

| Column Name | Type | Description | Example Values |
|-------------|------|-------------|----------------|
| `Data Context` | STRING | Data source category | "clinical", "animal_model", "cell_line", "organoid", "pdx" |
| `Phenotypes` | STRING (JSON) | List of phenotype names (human-readable) | `["Cafe-au-lait spot", "Plexiform neurofibroma"]` |
| `Phenotype HPO Codes` | STRING (JSON) | List of HPO terms for present phenotypes | `["HP:0000957", "HP:0009732"]` |
| `Phenotype Count` | INTEGER | Number of documented phenotypes | 5 |
| `Diagnosis MONDO Code` | STRING | MONDO ontology term for diagnosis | "MONDO:0007617" |
| `Diagnosis` | STRING | Human-readable diagnosis name | "Neurofibromatosis type 1" |
| `Has Treatment` | BOOLEAN | Whether treatment information exists | true/false |
| `Age Group` | STRING | Age group classification | "infant", "child", "adolescent", "adult" |
| `Model Type` | STRING | Model organism type (non-clinical only) | "mouse", "rat", "zebrafish", "drosophila" |

### Benefits of Enriched Columns

1. **Clinician-Friendly Phenotypes**: Search using clinical terms like "Plexiform neurofibroma" instead of HPO codes
2. **Dual Phenotype Search**: Filter by readable names (`Phenotypes`) or technical codes (`Phenotype HPO Codes`)
3. **MONDO Codes**: Standardized diagnosis filtering across international databases
4. **Dual Diagnosis Search**: Filter by ontology codes (`Diagnosis MONDO Code`) or readable names (`Diagnosis`)
5. **User-Friendly Names**: All enriched columns have friendly display names with proper capitalization
6. **Data Context**: Quick filtering by experimental system type
7. **Age Categories**: Simpler queries for pediatric vs adult cohorts
8. **Treatment Flags**: Rapidly identify treated vs untreated cohorts

---

## View Definitions

### 1. Clinical Data View

**Name**: `NF Clinical Data - Enriched Filters`

**Purpose**: Human patient clinical data with phenotype-based filtering

**Filter Criteria**:
```sql
SELECT *
FROM syn16858331
WHERE species = 'Homo sapiens'
  AND (modelSystemName IS NULL OR modelSystemName = '')
  AND dataType IN ('clinical', 'demographics', 'behavioral data')
```

**Use Cases**:
- Filter patients by HPO phenotype (e.g., all with optic glioma)
- Group by diagnosis (NF1 vs NF2 vs schwannomatosis)
- Analyze by age category (pediatric vs adult manifestations)
- Identify treatment cohorts

**Example Queries**:
```sql
-- All NF1 patients with plexiform neurofibromas (using friendly names)
SELECT * FROM <clinical_view>
WHERE "Diagnosis" = 'Neurofibromatosis type 1'
  AND "Phenotypes" LIKE '%Plexiform neurofibroma%'

-- Same query using technical ontology codes (for precise matching)
SELECT * FROM <clinical_view>
WHERE "Diagnosis MONDO Code" = 'MONDO:0007617'
  AND "Phenotype HPO Codes" LIKE '%HP:0009732%'

-- Pediatric patients with learning disabilities (friendly search)
SELECT * FROM <clinical_view>
WHERE "Age Group" IN ('child', 'adolescent')
  AND "Phenotypes" LIKE '%learning disability%'

-- Patients with treatment data and 3+ documented phenotypes
SELECT * FROM <clinical_view>
WHERE "Has Treatment" = TRUE
  AND "Phenotype Count" >= 3
```

---

### 2. Animal Model View

**Name**: `NF Animal Model Data - Enriched Filters`

**Purpose**: Model organism data (mouse, rat, zebrafish) with system categorization

**Filter Criteria**:
```sql
SELECT *
FROM syn16858331
WHERE species IN ('Mus musculus', 'Rattus norvegicus', 'Danio rerio')
   OR modelSystemName IS NOT NULL
```

**Enriched Filters**:
- `Model Type`: "mouse", "rat", "zebrafish", etc.
- Genotype information
- Treatment/intervention data

**Use Cases**:
- Compare NF1 mouse models across studies
- Filter by genetic background (e.g., C57BL/6)
- Identify drug treatment experiments
- Cross-reference with human phenotypes

---

### 3. Cell Line View

**Name**: `NF Cell Line Data - Enriched Filters`

**Purpose**: Established cell lines and iPSCs

**Filter Criteria**:
```sql
SELECT *
FROM syn16858331
WHERE specimenType IN ('cell line', 'iPSC', 'induced pluripotent stem cell')
```

**Use Cases**:
- Filter by cell line origin (NF1 vs NF2 patient-derived)
- Identify drug screening datasets
- Compare genomics vs proteomics across lines

---

### 4. Organoid View

**Name**: `NF Organoid Data - Enriched Filters`

**Purpose**: Organoid and spheroid cultures

**Filter Criteria**:
```sql
SELECT *
FROM syn16858331
WHERE specimenType LIKE '%organoid%'
   OR specimenType LIKE '%spheroid%'
```

**Use Cases**:
- Compare 2D vs 3D culture models
- Filter by tissue origin (brain organoids, Schwann cell spheroids)
- Identify advanced model systems

---

### 5. PDX View

**Name**: `NF PDX Data - Enriched Filters`

**Purpose**: Patient-derived xenograft data

**Filter Criteria**:
```sql
SELECT *
FROM syn16858331
WHERE modelSystemName LIKE '%PDX%'
   OR modelSystemName LIKE '%xenograft%'
   OR specimenType LIKE '%xenograft%'
```

**Use Cases**:
- Link PDX models to source patient data
- Filter by tumor type (MPNST PDX models)
- Track treatment response in PDX models

---

## Implementation Steps

### Phase 1: Preparation (Day 1)

#### 1.1 Install Dependencies

```bash
pip install synapseclient pandas
```

#### 1.2 Authenticate to Synapse

```bash
# Configure credentials
synapse login -u your_username -p your_password --rememberMe

# Or use auth token
export SYNAPSE_AUTH_TOKEN="your_token"
```

#### 1.3 Test Access

```python
import synapseclient
syn = synapseclient.Synapse()
syn.login()

# Verify access to source view
view = syn.get("syn16858331")
print(f"✓ Access confirmed: {view.name}")
```

---

### Phase 2: Dry Run and Validation (Day 2)

#### 2.1 Preview Changes

```bash
# Preview all views without creating them
python scripts/create_clinical_materialized_views.py \
  --parent syn26451327 \
  --dry-run

# Preview specific view only
python scripts/create_clinical_materialized_views.py \
  --parent syn26451327 \
  --view-type clinical \
  --dry-run
```

#### 2.2 Validate Enrichment Logic

Create a test script to validate the enrichment on sample data:

```python
from scripts.create_clinical_materialized_views import ClinicalMetadataEnricher

enricher = ClinicalMetadataEnricher()

# Test with sample clinical record
test_record = {
    "id": "syn123456",
    "species": "Homo sapiens",
    "diagnosis": "Neurofibromatosis type 1",
    "age": 14,
    "cafeaulaitMacules": "present",
    "plexiformNeurofibromas": "few",
    "learningDisability": "present",
    "tumorTreatmentStatus": "targeted therapy"
}

enriched = enricher.create_filter_columns(test_record)
print(f"Data context: {enriched['Data Context']}")
print(f"Phenotypes (friendly): {enriched['Phenotypes']}")
print(f"Phenotype HPO codes: {enriched['Phenotype HPO Codes']}")
print(f"Phenotype count: {enriched['Phenotype Count']}")
print(f"Diagnosis MONDO code: {enriched['Diagnosis MONDO Code']}")
print(f"Diagnosis: {enriched['Diagnosis']}")
print(f"Age group: {enriched['Age Group']}")

# Expected output:
# Data context: clinical
# HPO phenotypes: ["HP:0000957", "HP:0009732", "HP:0001328"]
# Phenotype count: 3
# MONDO code: MONDO:0007617
# Age category: adolescent
```

---

### Phase 3: Create Views (Day 3)

#### 3.1 Create Clinical View First

Start with the clinical view as a pilot:

```bash
python scripts/create_clinical_materialized_views.py \
  --parent syn26451327 \
  --view-type clinical \
  --execute
```

#### 3.2 Validate Clinical View

```python
import synapseclient
syn = synapseclient.Synapse()
syn.login()

# Query the new clinical view (replace with actual syn ID from output)
clinical_view_id = "synXXXXXXX"  # From script output

# Test query
query = f"""
SELECT id, individualID, "Diagnosis", "Phenotypes", "Phenotype Count"
FROM {clinical_view_id}
WHERE "Phenotype Count" >= 3
LIMIT 10
"""

results = syn.tableQuery(query)
df = results.asDataFrame()
print(df)
```

#### 3.3 Create Remaining Views

Once validated, create all views:

```bash
python scripts/create_clinical_materialized_views.py \
  --parent syn26451327 \
  --execute
```

---

### Phase 4: Integration and Testing (Days 4-5)

#### 4.1 Update Portal Code

If using the NF Data Portal, update filter configurations to use new views:

```python
# config/portal_views.py

CONTEXT_SPECIFIC_VIEWS = {
    "clinical": "synXXXXXXX",      # Clinical view ID
    "animal_model": "synXXXXXXX",  # Animal model view ID
    "cell_line": "synXXXXXXX",     # Cell line view ID
    "organoid": "synXXXXXXX",      # Organoid view ID
    "pdx": "synXXXXXXX",           # PDX view ID
}

# Use in query builder
def get_view_for_context(context: str) -> str:
    return CONTEXT_SPECIFIC_VIEWS.get(context, "syn16858331")
```

#### 4.2 Create Filter UI Components

Example filter for clinical view:

```python
# Clinical data filters using enriched columns

CLINICAL_FILTERS = {
    "diagnosis": {
        "field": "Diagnosis",
        "type": "select",
        "options": [
            {"label": "NF1", "value": "Neurofibromatosis type 1"},
            {"label": "NF2", "value": "NF2-related schwannomatosis"},
            {"label": "Schwannomatosis", "value": "Schwannomatosis"},
        ]
    },
    "phenotype": {
        "field": "Phenotypes",  # User-friendly labels
        "type": "multiselect",
        "options": [
            {"label": "Plexiform neurofibroma", "value": "Plexiform neurofibroma"},
            {"label": "Optic glioma", "value": "Optic glioma"},
            {"label": "Learning disability", "value": "Specific learning disability"},
            # ... more phenotypes
        ],
        "search_type": "contains"  # JSON array search
    },
    "age_group": {
        "field": "Age Group",
        "type": "select",
        "options": ["infant", "child", "adolescent", "adult"]
    },
    "has_treatment": {
        "field": "Has Treatment",
        "type": "boolean"
    }
}
```

---

## Advanced Use Cases

### 1. Cross-Context Queries

Find all data (clinical, cell line, PDX) from the same patient:

```sql
-- Clinical data
SELECT id, individualID, "Diagnosis"
FROM <clinical_view>
WHERE individualID = 'PATIENT_001'

UNION

-- Cell line data derived from patient
SELECT id, individualID, 'cell_line' as source
FROM <cell_line_view>
WHERE individualID = 'PATIENT_001'

UNION

-- PDX derived from patient
SELECT id, individualID, 'pdx' as source
FROM <pdx_view>
WHERE individualID = 'PATIENT_001'
```

### 2. Phenotype-Driven Discovery

Find animal models that match a specific human phenotype profile:

```sql
-- Human patients with plexiform neurofibromas (using friendly names)
SELECT individualID, "Phenotypes"
FROM <clinical_view>
WHERE "Phenotypes" LIKE '%Plexiform neurofibroma%'

-- Find corresponding mouse models
SELECT modelSystemName, genePerturbed
FROM <animal_model_view>
WHERE "Model Type" = 'mouse'
  AND genePerturbed = 'NF1'
```

### 3. Treatment Response Analysis

Identify clinical cohorts with treatment data for specific manifestations:

```sql
SELECT
  "Diagnosis MONDO Code",
  "Diagnosis",
  COUNT(*) as patient_count,
  AVG("Phenotype Count") as avg_phenotypes
FROM <clinical_view>
WHERE "Has Treatment" = TRUE
  AND "Phenotypes" LIKE '%Plexiform neurofibroma%'
GROUP BY "Diagnosis MONDO Code", "Diagnosis"
```

---

## Maintenance and Updates

### Refreshing Views

Materialized views should be refreshed when source data changes:

```python
import synapseclient

syn = synapseclient.Synapse()
syn.login()

# Trigger view refresh
view_id = "synXXXXXXX"
syn.tableQuery(f"SELECT * FROM {view_id} LIMIT 1")
```

### Updating Ontology Mappings

When HPO/MONDO terms are updated in the metadata dictionary:

1. Update mappings in `ClinicalMetadataEnricher`
2. Re-run enrichment script
3. Refresh materialized views

```python
# Add new HPO term
self.phenotype_hpo_map["newManifestation"] = "HP:XXXXXXX"

# Add new MONDO term
self.diagnosis_mondo_map["New NF Subtype"] = "MONDO:XXXXXXX"
```

---

## Monitoring and Validation

### Check View Stats

```python
import synapseclient

syn = synapseclient.Synapse()
syn.login()

views = {
    "clinical": "synXXXXXXX",
    "animal_model": "synXXXXXXX",
    "cell_line": "synXXXXXXX",
    "organoid": "synXXXXXXX",
    "pdx": "synXXXXXXX",
}

for view_name, view_id in views.items():
    query = f"SELECT COUNT(*) as count FROM {view_id}"
    result = syn.tableQuery(query)
    count = result.asDataFrame()["count"][0]
    print(f"{view_name:15s}: {count:6d} records")
```

### Validate Enrichment Quality

```sql
-- Check for missing enrichment
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN "Data Context" IS NULL THEN 1 ELSE 0 END) as missing_context,
  SUM(CASE WHEN "Diagnosis MONDO Code" IS NULL THEN 1 ELSE 0 END) as missing_mondo
FROM <clinical_view>
```

---

## Comparison with Existing View (syn52702673)

| Feature | syn52702673 (General) | New Context-Specific Views |
|---------|----------------------|---------------------------|
| Scope | All data types | Filtered by context |
| Enrichment | Basic annotations | HPO/MONDO codes, computed fields |
| Query Performance | Slower (large dataset) | Faster (subset + indexed) |
| Filter Complexity | Manual filtering needed | Built-in context filters |
| Use Case | General exploration | Targeted analysis |

**Recommendation**: Keep both!
- Use syn52702673 for broad queries across all data
- Use context-specific views for focused clinical/model analysis

---

## Timeline and Resources

| Phase | Duration | Activities |
|-------|----------|------------|
| **Preparation** | 1 day | Install tools, validate access, test scripts |
| **Dry Run & Validation** | 1 day | Preview views, test enrichment logic |
| **Create Views** | 1 day | Execute scripts, create all views |
| **Integration & Testing** | 2 days | Update portal code, create filters, QA |
| **Documentation** | 1 day | Update user docs, create examples |
| **Total** | **6 days** | - |

---

## Success Metrics

- [ ] All 5 context-specific views created successfully
- [ ] Enriched columns populated correctly (>95% coverage)
- [ ] Query performance improved (>2x faster for filtered queries)
- [ ] Portal filters using new views
- [ ] User documentation updated
- [ ] Example queries validated

---

## Next Steps

1. **Immediate**: Run dry-run validation
2. **Week 1**: Create clinical view as pilot
3. **Week 2**: Deploy all views to production
4. **Week 3**: Integrate with portal UI
5. **Month 2**: Add Phenopacket export (separate feature)

---

## Support and Troubleshooting

### Common Issues

**Issue**: View creation fails with permission error
```
Solution: Ensure you have EDIT permissions on parent folder syn26451327
```

**Issue**: HPO phenotypes not populating
```
Solution: Check source field names match metadata dictionary exactly
```

**Issue**: Query performance still slow
```
Solution: Add indexes on frequently filtered columns ("Diagnosis MONDO Code", "Data Context", "Phenotypes")
```

### Getting Help

- Open issue in nf-metadata-dictionary repository
- Contact NF-OSI data team
- Reference this implementation guide

---

## References

- [Synapse Entity Views Documentation](https://help.synapse.org/docs/Views.2011070739.html)
- [GA4GH Phenopacket Mapping](./PHENOPACKET_MAPPING.md)
- [HPO Browser](https://hpo.jax.org/)
- [MONDO Disease Ontology](https://mondo.monarchinitiative.org/)
