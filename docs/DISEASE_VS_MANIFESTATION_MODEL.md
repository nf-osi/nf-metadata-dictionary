# Disease vs Manifestation Conceptual Model

## Overview

The NF metadata dictionary distinguishes between:
- **Disease**: Underlying genetic condition (NF1, NF2, schwannomatosis)
- **Manifestation**: Clinical tumors and symptoms that arise from the disease (MPNST, schwannomas, neurofibromas)

This separation aligns with established ontology practices and provides clearer semantic meaning for data analysis.

## Key Concepts

### Disease (Underlying Condition)
Diseases are the primary genetic conditions that patients have. These map to the `diagnosis` field in the source data.

**Ontology**: MONDO (Monarch Disease Ontology)

**Examples**:
- Neurofibromatosis type 1 (MONDO:0018975)
- NF2-related schwannomatosis (MONDO:0007039)
- LZTR1-related schwannomatosis (MONDO:0014299)
- Legius syndrome (MONDO:0012705)

**Important Note**: "Neurofibromatosis type 2" and "NF2" are synonyms for "NF2-related schwannomatosis" and all map to MONDO:0007039.

### Manifestation (Clinical Presentation)
Manifestations are the tumors and clinical features that develop as a result of the disease. These map to the `tumorType` field for tumors.

**Ontologies**: MONDO (for tumor types) and NCIT (NCI Thesaurus)

**Examples**:
- High Grade Malignant Peripheral Nerve Sheath Tumor (NCIT:C9030)
- Atypical Neurofibroma (MONDO:0003306)
- Sporadic Schwannoma (NCIT:C129278)
- Vestibular Schwannoma (NCIT:C3276)

## Data Model Mapping

### Clinical Data Structure

```
Patient Record:
├── diagnosis (Disease)
│   ├── Input: "Neurofibromatosis type 1" or "NF1"
│   ├── Canonical: "Neurofibromatosis type 1"
│   └── MONDO Code: MONDO:0018975
│
├── tumorType (Manifestation)
│   ├── Input: "High Grade MPNST"
│   ├── Canonical: "High Grade Malignant Peripheral Nerve Sheath Tumor"
│   └── NCIT Code: NCIT:C9030
│
└── Phenotypes (Manifestations)
    ├── cafeaulaitMacules → HP:0000957
    ├── plexiformNeurofibromas → HP:0009732
    └── opticGlioma → HP:0009734
```

### Materialized View Columns

The enriched materialized views provide three diagnosis-related columns:

1. **"Diagnosis"** - Human-readable canonical disease label
   - Example: "Neurofibromatosis type 1"
   - Handles case variations and synonyms

2. **"Diagnosis MONDO Code"** - MONDO ontology term for the disease
   - Example: "MONDO:0018975"
   - Preferred for standardization and cross-reference

3. **"Diagnosis NCIT Code"** - NCIT code (when MONDO not available)
   - Example: "NCIT:C6557" (for Schwannomatosis)
   - Supplemental to MONDO

## Implementation Details

### Disease Mappings (`disease_mondo_map`, `disease_ncit_map`)

Located in `scripts/create_model_materialized_views.py`:

```python
# MONDO mappings for DISEASES (underlying genetic conditions)
self.disease_mondo_map = {
    # NF diseases
    "Neurofibromatosis type 1": "MONDO:0018975",
    "NF1": "MONDO:0018975",  # Synonym

    # NF2 synonyms (user confirmed)
    "Neurofibromatosis type 2": "MONDO:0007039",
    "NF2": "MONDO:0007039",
    "NF2-related schwannomatosis": "MONDO:0007039",

    # Schwannomatosis subtypes
    "Schwannomatosis": "MONDO:0010896",
    "LZTR1-related schwannomatosis": "MONDO:0014299",

    # Related syndromes
    "Legius syndrome": "MONDO:0012705",
}
```

### Manifestation Mappings (`manifestation_mondo_map`, `manifestation_ncit_map`)

```python
# Separate manifestation/tumor mappings
self.manifestation_mondo_map = {
    "atypical neurofibroma": "MONDO:0003306",
    "Atypical Neurofibroma": "MONDO:0003306",
}

self.manifestation_ncit_map = {
    # MPNST variants
    "High Grade MPNST": "NCIT:C9030",
    "high grade MPNST": "NCIT:C9030",
    "high grade metastatic MPNST": "NCIT:C9030",

    # Schwannomas
    "Vestibular Schwannoma": "NCIT:C3276",
    "Sporadic Schwannoma": "NCIT:C129278",
}
```

### Methods

- `get_disease_ontology(diagnosis)` - Returns MONDO code for disease
- `get_disease_ncit(diagnosis)` - Returns NCIT code for disease
- `get_canonical_disease(diagnosis)` - Returns canonical disease label (handles synonyms)

All methods support case-insensitive matching and synonym resolution.

## Data Quality Considerations

### Synonym Handling

The system automatically normalizes synonyms:
- "NF1" → "Neurofibromatosis type 1"
- "NF2" → "NF2-related schwannomatosis"
- "High Grade MPNST" → "High Grade Malignant Peripheral Nerve Sheath Tumor"

### Case Variations

All matching is case-insensitive:
- "neurofibromatosis type 1" ✅
- "NEUROFIBROMATOSIS TYPE 1" ✅
- "Neurofibromatosis Type 1" ✅

### JSON Array Handling

The `diagnosis` field in syn16858331 stores values as JSON arrays:
```json
['Neurofibromatosis type 1']
```

The system needs to parse these arrays and handle records with multiple diagnoses.

## Future Extensions

### TODO: Manifestation Ontology Mapping

Currently, manifestations are stored in `tumorType` but not systematically mapped to ontologies in the materialized views. Future work could:

1. Add "Tumor Type MONDO Code" and "Tumor Type NCIT Code" columns
2. Map manifestations from `tumorType` field
3. Create separate phenotype columns for clinical manifestations

### TODO: Missing MONDO Codes

From SYNAPSE_DATA_ANALYSIS.md, these need verification:
- Sporadic Schwannoma (44 records) - ✅ Now mapped to NCIT:C129278
- Noonan Syndrome (15 records) - Need MONDO code
- Cancer (79 records) - Too generic, needs data cleanup

## References

- [MONDO Disease Ontology](https://mondo.monarchinitiative.org/)
- [NCI Thesaurus (NCIT)](https://ncithesaurus.nci.nih.gov/)
- [Human Phenotype Ontology (HPO)](https://hpo.jax.org/)
- [Diagnosis Module Schema](../modules/Sample/Diagnosis.yaml)
- [Verified Ontology Mappings](./VERIFIED_ONTOLOGY_MAPPINGS.md)
- [Synapse Data Analysis](./SYNAPSE_DATA_ANALYSIS.md)

---

**Last Updated**: 2026-02-13
**Version**: 1.0
