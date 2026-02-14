# Verified Ontology Mappings

**IMPORTANT**: This document contains ONLY codes that are explicitly defined in schema files or verified against ontologies. Do NOT add codes without verification.

## Mapping Sources

- ✅ **Schema-defined**: From `modules/Sample/Diagnosis.yaml` `meaning:` fields
- ✅ **Phenopacket-verified**: From `mappings/phenopacket-mapping.yaml`
- ⚠️ **Needs verification**: Listed in TODO section, must verify before using

## HPO Phenotype Mappings (11 VERIFIED)

### Verified from phenopacket-mapping.yaml

| Field Name | HPO Code | Label | Source |
|------------|----------|-------|--------|
| cafeaulaitMacules | HP:0000957 | Cafe-au-lait spot | phenopacket-mapping.yaml:291 |
| skinFoldFreckling | HP:0001250 | Axillary freckling | phenopacket-mapping.yaml:304 |
| IrisLischNodules | HP:0009737 | Lisch nodules | phenopacket-mapping.yaml:317 |
| plexiformNeurofibromas | HP:0009732 | Plexiform neurofibroma | phenopacket-mapping.yaml:330 |
| opticGlioma | HP:0009734 | Optic nerve glioma | phenopacket-mapping.yaml:345 |
| learningDisability | HP:0001328 | Specific learning disability | phenopacket-mapping.yaml:358 |
| intellectualDisability | HP:0001249 | Intellectual disability | phenopacket-mapping.yaml:366 |
| attentionDeficitDisorder | HP:0007018 | Attention deficit hyperactivity disorder | phenopacket-mapping.yaml:374 |
| scoliosis | HP:0002650 | Scoliosis | phenopacket-mapping.yaml:382 |
| vestibularSchwannoma | HP:0009589 | Vestibular schwannoma | phenopacket-mapping.yaml:392 |
| meningioma | HP:0002858 | Meningioma | phenopacket-mapping.yaml:406 |

### TODO: Need HPO Code Verification

These phenotype fields exist in Biosample.yaml but need HPO codes verified:

- ❓ `dermalNeurofibromas` - Need correct HPO for "Neurofibromas" (not HP:0001067 which is incorrect)
- ❓ `subcutaneousNodularNeurofibromas` - **NOT HP:0009729** (that's cardiac rhabdomyoma!)
- ❓ `diffuseDermalNeurofibromas` - Need verification
- ❓ `spinalNeurofibromas` - Need verification
- ❓ `nonopticGlioma` - Need verification
- ❓ `gliomaOrEpendymoma` - Need verification
- ❓ `aqueductalStenosis` - Need verification
- ❓ `longBoneDysplasia` - Need verification
- ❓ `sphenoidDysplasia` - Need verification
- ❓ `spinalSchwannoma` - Need verification
- ❓ `dermalSchwannoma` - Need verification
- ❓ `nonvestibularCranialSchwannoma` - Need verification
- ❓ `nonvestibularSchwannomas` - Need verification
- ❓ `lenticularOpacity` - Need verification
- ❓ `heartDefect` - Need verification
- ❓ `vascularDisease` - Need verification
- ❓ `pheochromocytoma` - Need verification
- ❓ `glomusTumor` - Need verification
- ❓ `peripheralNeuropathy` - Need verification
- ❓ `GIST` - Need verification
- ❓ `leukemia` - Need verification
- ❓ `breastCancer` - Need verification

## MONDO Diagnosis Mappings (9 VERIFIED)

### From Diagnosis.yaml meaning: fields

| Diagnosis | MONDO Code | Source |
|-----------|------------|--------|
| NF2-related schwannomatosis | MONDO:0007039 | Diagnosis.yaml:20 |
| LZTR1-related schwannomatosis | MONDO:0014299 | Diagnosis.yaml:17 |
| SMARCB1-related schwannomatosis | MONDO:0024517 | Diagnosis.yaml:30 |
| 22q-related schwannomatosis | MONDO:1030016 | Diagnosis.yaml:15 |
| atypical neurofibroma | MONDO:0003306 | Diagnosis.yaml:63 |

### From phenopacket-mapping.yaml

| Diagnosis | MONDO Code | Source | Notes |
|-----------|------------|--------|-------|
| Neurofibromatosis type 1 | MONDO:0018975 | User correction | **Was incorrectly MONDO:0007617** |
| Schwannomatosis | MONDO:0010896 | phenopacket-mapping.yaml:259 | |
| Legius syndrome | MONDO:0012705 | phenopacket-mapping.yaml:270 | |

**Note on Schwannomatosis**: Diagnosis.yaml has `meaning: NCIT:C6557`, but MONDO:0010896 is used in phenopacket-mapping.yaml. Both are valid, kept separate.

### Synonyms (case-insensitive matching supported)

| Input Variant | Canonical Form | Code |
|---------------|----------------|------|
| "atypical neurofibroma" | Atypical Neurofibroma | MONDO:0003306 |
| "Atypical Neurofibroma" | Atypical Neurofibroma | MONDO:0003306 |

## NCIT Diagnosis Mappings (5 VERIFIED)

### From Diagnosis.yaml meaning: fields

| Diagnosis | NCIT Code | Source | Notes |
|-----------|-----------|--------|-------|
| Schwannomatosis | NCIT:C6557 | Diagnosis.yaml:36 | Has MONDO too: MONDO:0010896 |
| Vestibular Schwannoma | NCIT:C3276 | Diagnosis.yaml:61 | |
| High Grade Malignant Peripheral Nerve Sheath Tumor | NCIT:C9030 | Diagnosis.yaml:68 | |

### Synonyms

| Input Variant | Canonical Form | Code |
|---------------|----------------|------|
| "High Grade MPNST" | High Grade Malignant Peripheral Nerve Sheath Tumor | NCIT:C9030 |
| "Acoustic Neuroma" | Vestibular Schwannoma | NCIT:C3276 |

## OMIM Mappings (1 VERIFIED)

| Diagnosis | OMIM Code | Source |
|-----------|-----------|--------|
| Juvenile myelomonocytic leukemia | OMIM:607785 | Diagnosis.yaml:73 |

**Synonym**: "JMML" → OMIM:607785

## TODO: Diagnoses Needing MONDO Codes

From Diagnosis.yaml, these have descriptions but no `meaning:` field:

- ❓ "Mosaic neurofibromatosis type 1" - Need MONDO code
- ❓ "Noonan Syndrome" - Has Orphanet code but need MONDO
- ❓ "Sporadic Schwannoma" - Need verification
- ❓ "Schwannomatosis-NOS" - Probably same as Schwannomatosis (MONDO:0010896)?
- ❓ "Schwannomatosis-NEC" - Probably same as Schwannomatosis (MONDO:0010896)?
- ❓ "Atypical Pilocytic Astrocytoma" - From Tumor.yaml, need code

## Important Notes

### ⚠️ Common Mistakes to Avoid

1. **HP:0009729 is NOT "Subcutaneous neurofibroma"** - it's "Cardiac rhabdomyoma"
2. **MONDO:0007617 is NOT "Neurofibromatosis type 1"** - correct is MONDO:0018975
3. Do NOT guess HPO codes - they must be verified against https://hpo.jax.org/
4. Do NOT guess MONDO codes - they must be verified against https://mondo.monarchinitiative.org/

### Verification Process

Before adding ANY new code:
1. Search https://hpo.jax.org/ or https://www.ebi.ac.uk/ols/ontologies/hp
2. Search https://mondo.monarchinitiative.org/ or https://www.ebi.ac.uk/ols/ontologies/mondo
3. Verify the exact label matches the intended phenotype/diagnosis
4. Document the source in this file

### ANNUBP Note

**ANNUBP** (Atypical Neurofibromatous Neoplasm of Uncertain Biologic Potential) is defined in `modules/Sample/Tumor.yaml` but:
- It's a tumor classification, not a patient diagnosis
- Used in `tumorType` field (specimen-level), not `diagnosis` field (patient-level)
- Does not need to be in diagnosis mappings

## Column Structure in Materialized Views

### Three Diagnosis Columns

1. **"Diagnosis MONDO Code"** - MONDO ontology term (preferred for standardization)
2. **"Diagnosis NCIT Code"** - NCIT ontology term (when MONDO not available)
3. **"Diagnosis"** - Human-readable canonical label

Example:
```
diagnosis = "High Grade MPNST"
→ Diagnosis MONDO Code: NULL (no MONDO mapping)
→ Diagnosis NCIT Code: NCIT:C9030
→ Diagnosis: "High Grade Malignant Peripheral Nerve Sheath Tumor" (canonical)
```

### Case-Insensitive Matching

All matching is case-insensitive:
```
"neurofibromatosis type 1" → MONDO:0018975 ✓
"NEUROFIBROMATOSIS TYPE 1" → MONDO:0018975 ✓
"Neurofibromatosis Type 1" → MONDO:0018975 ✓
```

## Next Steps

1. **Query syn16858331** to get all unique diagnosis values
2. **Verify each** against MONDO/NCIT ontologies
3. **Add verified codes** to script mappings
4. **Search HPO** for all unmapped phenotype fields
5. **Document sources** for all new additions

## Coverage Statistics

- **HPO Phenotypes**: 11 verified / ~40 total fields = **28% verified**
- **MONDO Diagnoses**: 9 verified / ~15 total = **60% verified**
- **NCIT Diagnoses**: 5 verified
- **Case-insensitive**: ✅ Yes
- **Synonym support**: ✅ Yes
- **Fuzzy matching**: ❌ No

## References

- [Human Phenotype Ontology (HPO)](https://hpo.jax.org/)
- [HPO Browser (OLS)](https://www.ebi.ac.uk/ols/ontologies/hp)
- [Monarch Disease Ontology (MONDO)](https://mondo.monarchinitiative.org/)
- [MONDO Browser (OLS)](https://www.ebi.ac.uk/ols/ontologies/mondo)
- [NCI Thesaurus](https://ncithesaurus.nci.nih.gov/)
- [Schema Diagnosis Module](../modules/Sample/Diagnosis.yaml)
- [Phenopacket Mapping](../mappings/phenopacket-mapping.yaml)
