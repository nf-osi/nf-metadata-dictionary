# Synapse Data Analysis - Actual Diagnosis Values

Analysis of diagnosis values from syn16858331 (queried 2026-02-13)

## Summary

- **Total records with diagnosis**: 77,482
- **Unique diagnosis values**: 24 (including variations)
- **Main diagnosis**: Neurofibromatosis type 1 (88.9% of records)

## Diagnosis Values Found (with counts)

| Count | Diagnosis Value | Status | Notes |
|-------|----------------|--------|-------|
| 68,823 | Neurofibromatosis type 1 | ✅ Mapped | MONDO:0018975 |
| 3,463 | Not Applicable | ⚪ Skip | Not a diagnosis |
| 1,573 | Schwannomatosis | ✅ Mapped | MONDO:0010896 |
| 1,284 | (empty) | ⚪ Skip | Missing data |
| 1,199 | Neurofibromatosis type 2 | ❓ **NEEDS VERIFICATION** | Is this NF2-related schwannomatosis (MONDO:0007039)? |
| 519 | nan | ⚪ Skip | Missing data |
| 264 | NF2-related schwannomatosis | ✅ Mapped | MONDO:0007039 |
| 79 | Cancer | ❓ **TOO GENERIC** | Need specific cancer type |
| 72 | Unknown | ⚪ Skip | Missing data |
| 44 | Sporadic Schwannoma | ❓ **NEEDS MONDO CODE** | |
| 28 | high grade metastatic MPNST | ❓ **NEEDS CODE** | Variant of NCIT:C9030? |
| 25 | NA | ⚪ Skip | Missing data |
| 23 | high grade MPNST | ✅ Mapped | NCIT:C9030 |
| 22 | Atypical Neurofibroma | ✅ Mapped | MONDO:0003306 |
| 22 | High grade MPNST | ✅ Mapped | NCIT:C9030 (case variation) |
| 15 | Noonan Syndrome | ❓ **NEEDS MONDO CODE** | Has Orphanet but need MONDO |
| 11 | JMML | ✅ Mapped | OMIM:607785 (need MONDO?) |
| 3 | high grade MPNST with divergent differentiation | ❓ **NEEDS CODE** | Variant of MPNST |
| 3 | Neurofibromatosis type 1 + Noonan Syndrome + Not Applicable | ⚪ **MULTIPLE** | Combo - how to handle? |
| 3 | NF1 | ✅ Synonym | → Neurofibromatosis type 1 |
| 2 | Neurofibromatosis type 1 + Neurofibromatosis type 2 | ⚪ **MULTIPLE** | Combo - how to handle? |
| 2 | NF1+/+, NF1 -/- | ⚪ **GENOTYPE** | Not diagnosis, genotype info |
| 1 | Neurofibromatosis 1 | ✅ Synonym | → Neurofibromatosis type 1 |
| 1 | NF2 | ✅ Synonym | → Neurofibromatosis type 2 |

## Critical Findings

### 1. Diagnosis Field is JSON Array
**Problem**: Diagnosis column stores values as JSON arrays: `['Neurofibromatosis type 1']`
**Impact**: Need to parse arrays and handle multiple diagnoses

### 2. Case Variations
Multiple case variants exist for same diagnosis:
- "high grade MPNST" / "High grade MPNST" / "high grade metastatic MPNST"
- "Neurofibromatosis type 1" / "Neurofibromatosis 1" / "NF1"

**Solution**: Case-insensitive matching + synonym support ✅ (already implemented)

### 3. Missing MONDO Codes (High Priority)

**Neurofibromatosis type 2 (1,199 records)**
- Current data uses this term
- Schema has "NF2-related schwannomatosis" (MONDO:0007039)
- **ACTION NEEDED**: Verify if these are synonyms or different conditions

**Sporadic Schwannoma (44 records)**
- **ACTION NEEDED**: Search MONDO for schwannoma codes
- Possible: MONDO:0001381 (schwannoma) or more specific

**Noonan Syndrome (15 records)**
- Schema has Orphanet:648
- **ACTION NEEDED**: Find MONDO code (likely MONDO:0018955 or similar)

**high grade metastatic MPNST (28 records)**
- Variant of "high grade MPNST" (NCIT:C9030)
- **ACTION NEEDED**: Confirm if same code or needs separate mapping

**high grade MPNST with divergent differentiation (3 records)**
- Rare variant
- **ACTION NEEDED**: Verify if uses same NCIT:C9030 or needs specific code

### 4. Phenotype Fields Don't Exist in syn16858331

The clinical phenotype fields (cafeaulaitMacules, plexiformNeurofibromas, etc.) are **NOT** in syn16858331.

**Possible locations**:
- Individual-level clinical view (different from syn16858331)?
- Biospecimen metadata tables?
- Patient metadata in separate tables?

**ACTION NEEDED**: Find correct Synapse table/view for patient-level phenotype data

## Recommendations

### Immediate Actions (Required)

1. **Verify "Neurofibromatosis type 2"**
   - Check if synonym for "NF2-related schwannomatosis"
   - If yes, map to MONDO:0007039
   - If different, find correct MONDO code

2. **Update Diagnosis Parsing**
   - Handle JSON arrays: `['value']` → `value`
   - Support multiple diagnoses (3 records have multiple)
   - Normalize synonyms:
     - "NF1" → "Neurofibromatosis type 1"
     - "NF2" → "Neurofibromatosis type 2"
     - "Neurofibromatosis 1" → "Neurofibromatosis type 1"

3. **Find Missing MONDO Codes**
   - Sporadic Schwannoma
   - Noonan Syndrome
   - MPNST variants

### Search Strategy (Without Local Ontologies)

**Use Web APIs**:
- MONDO: https://www.ebi.ac.uk/ols/ontologies/mondo
- HPO: https://hpo.jax.org/ or https://www.ebi.ac.uk/ols/ontologies/hp

**Example searches**:
```
https://www.ebi.ac.uk/ols/api/search?q=noonan+syndrome&ontology=mondo
https://www.ebi.ac.uk/ols/api/search?q=sporadic+schwannoma&ontology=mondo
https://hpo.jax.org/app/browse/search?q=neurofibroma
```

## Updated Mapping Table (Based on Real Data)

### Verified Mappings (High Confidence)

| Diagnosis | MONDO/NCIT Code | Source | Count in Data |
|-----------|-----------------|--------|---------------|
| Neurofibromatosis type 1 | MONDO:0018975 | User correction | 68,823 |
| Schwannomatosis | MONDO:0010896 | Diagnosis.yaml | 1,573 |
| NF2-related schwannomatosis | MONDO:0007039 | Diagnosis.yaml | 264 |
| Atypical Neurofibroma | MONDO:0003306 | Diagnosis.yaml | 22 |
| High grade MPNST | NCIT:C9030 | Diagnosis.yaml | 45 total |
| JMML | OMIM:607785 | Diagnosis.yaml | 11 |

### Synonyms to Add

```python
# Add these to diagnosis mappings:
"NF1": "Neurofibromatosis type 1",
"Neurofibromatosis 1": "Neurofibromatosis type 1",
"NF2": "Neurofibromatosis type 2",  # After verifying mapping
"high grade metastatic MPNST": "High Grade Malignant Peripheral Nerve Sheath Tumor",
"high grade MPNST with divergent differentiation": "High Grade Malignant Peripheral Nerve Sheath Tumor",  # Confirm
```

### Needs Verification (Manual Search Required)

1. **Neurofibromatosis type 2** (1,199 records) - Is this MONDO:0007039?
2. **Sporadic Schwannoma** (44 records) - Find MONDO code
3. **Noonan Syndrome** (15 records) - Find MONDO code (MONDO:0018955?)
4. **Cancer** (79 records) - Too generic, may need data cleanup

## Next Steps

1. ✅ Parse diagnosis arrays correctly
2. ✅ Add synonym mappings
3. ❓ Manually search MONDO/HPO web APIs for missing codes
4. ❓ Find correct Synapse view for phenotype data
5. ❓ Verify "Neurofibromatosis type 2" mapping
6. ❓ Handle multiple diagnoses in single record

## Data Quality Issues

- **Missing/invalid values**: 1,875 records (2.4%) have nan/empty/NA
- **Generic "Cancer"**: 79 records (0.1%) - should be more specific
- **Multiple diagnoses**: 5 records have comma-separated lists
- **Genotype data in diagnosis field**: 2 records have "NF1+/+, NF1 -/-"

---

*Generated from syn16858331 query on 2026-02-13*
