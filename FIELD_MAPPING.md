# Field Mapping and Normalization Guide

## Overview

This document explains how biological resources (cell lines, animal models, antibodies, genetic reagents) are referenced in the NF metadata schema and how they map to the NF Research Tools Database (syn51730943).

## Key Principle

**Donor information is stored once in syn51730943 and referenced via biologicalResourceName**, which typically maps to `individualID`. Detailed metadata is displayed in tooltips, not duplicated in annotation fields.

## Field Mappings

### Core Reference Fields

| Field | Description | Example Values |
|-------|-------------|----------------|
| `biologicalResourceType` | Type of resource from syn51730943 | "Cell Line", "Animal Model", "Antibody", "Genetic Reagent" |
| `biologicalResourceName` | Name of the resource | "JH-2-002" (cell line), "Anti-NF1-mAb" (antibody) |
| `individualID` | Individual/donor identifier | "JH-2-002" (same as cell line name) |
| `specimenID` | Specimen/replicate identifier | "JH-2-002-rep1", "JH-2-002-rep2" |

### Donor/Individual Attributes

These describe the **original donor** (e.g., human patient from which tumor was derived):

| Field | Description | Source |
|-------|-------------|--------|
| `species` | Donor species | "Homo sapiens" (human donor) |
| `sex` | Donor sex | "Male", "Female" |
| `age` | Donor age | 45 (years) |
| `ageUnit` | Age unit | "years" |
| `diagnosis` | Donor diagnosis | "Glioblastoma multiforme" |
| `organ` | Donor organ/tissue | "Brain" |

**For cell lines**: These are looked up from syn51730943 via `biologicalResourceName` and shown in **tooltips**.

### Animal Model Attributes

These describe the **animal model host** (for xenografts or model-only experiments):

| Field | Description | Source |
|-------|-------------|--------|
| `modelSystemName` | Genetic model name | "NSG", "B6.129(Cg)-Nf1tm1Par/J" |
| `modelSpecies` | Model species | "Mus musculus" |
| `modelSex` | Individual model animal sex | "Female" |
| `modelAge` | Individual model animal age | 8 (weeks) |
| `modelAgeUnit` | Model age unit | "weeks" |

**Genetic information** (genotype, mutations) from `modelSystemName` is in syn51730943 and shown in **tooltips**.

### Legacy Field Mapping

| Legacy Field | Maps To | Notes |
|--------------|---------|-------|
| `antibodyID` | `biologicalResourceName` | When `biologicalResourceType: "Antibody"` |
| `modelSystemName` (for cell lines) | `biologicalResourceName` | When `biologicalResourceType: "Cell Line"` |

## Usage Scenarios

### Scenario 1: Cell Line Only (Most Common)

Patient-derived cell line used for experiments.

```yaml
# Minimal required fields
biologicalResourceType: "Cell Line"
biologicalResourceName: "JH-2-002"      # → maps to individualID
individualID: "JH-2-002"                 # Same as cell line name
specimenID: "JH-2-002-rep1"              # Technical replicate 1
specimenID: "JH-2-002-rep2"              # Technical replicate 2

# Donor info from syn51730943 (shown in tooltip):
# - species: "Homo sapiens"
# - diagnosis: "Glioblastoma multiforme"
# - age: "45 years"
# - sex: "Male"
# - tissue: "Brain"
# - organ: "Cerebrum"
```

**User Experience**:
- Select `biologicalResourceName: "JH-2-002"` from dropdown
- Hover over selection → tooltip shows donor metadata
- Click → view full details in syn51730943

### Scenario 2: Cell Line in Animal Model (Xenograft)

Human cell line implanted in immunocompromised mouse.

```yaml
# Cell line (donor)
biologicalResourceType: "Cell Line"
biologicalResourceName: "JH-2-002"      # Human tumor donor
individualID: "JH-2-002"

# Animal model host
modelSystemName: "NSG"                   # NOD scid gamma mouse
modelSpecies: "Mus musculus"
modelSex: "Female"                       # Individual mouse sex
modelAge: 8                              # Individual mouse age
modelAgeUnit: "weeks"

# Specimen from xenograft
specimenID: "JH-2-002-NSG-001-tumor"    # Tumor grown in mouse

# Donor info (human tumor) from syn51730943 via JH-2-002
# Model genetic info from syn51730943 via NSG
```

**Data Flow**:
1. `biologicalResourceName: "JH-2-002"` → syn51730943 → human donor metadata (tooltip)
2. `modelSystemName: "NSG"` → syn51730943 → mouse model genetic info (tooltip)
3. `modelSex`, `modelAge` → specific to individual mouse used

### Scenario 3: Animal Model Only

Genetically engineered mouse model.

```yaml
# No cell line involved
biologicalResourceType: null             # Or omit
biologicalResourceName: null             # Or omit

# Animal model
modelSystemName: "B6.129(Cg)-Nf1tm1Par/J"
individualID: "mouse-001"                # Specific animal
sex: "Male"                              # Individual animal
age: 12                                  # Individual animal
ageUnit: "weeks"
species: "Mus musculus"                  # Can be inferred from model

# Specimen
specimenID: "mouse-001-liver"
specimenID: "mouse-001-brain"

# Model genetic info from syn51730943 via modelSystemName:
# - genotype
# - backgroundStrain
# - geneticModification
# - manifestation
```

**Note**: In this case, individual-level attributes (sex, age) are specified directly since there's no cell line donor.

### Scenario 4: With Antibodies

Experiment using antibody treatment or detection.

```yaml
# Option A: Use antibodyID (legacy, still supported)
antibodyID: "AB-12345"                   # References antibody in syn51730943

# Option B: Use generic pattern (recommended)
biologicalResourceType: "Antibody"
biologicalResourceName: "Anti-NF1-mAb"   # References antibody in syn51730943

# Antibody metadata from syn51730943 (shown in tooltip):
# - target: "NF1"
# - host: "Mouse"
# - clonality: "Monoclonal"
# - RRID: "AB_12345"
```

### Scenario 5: With Genetic Reagents

CRISPR, shRNA, or other genetic manipulation tools.

```yaml
# Genetic reagent used
biologicalResourceType: "Genetic Reagent"
biologicalResourceName: "CRISPR-NF1-KO"  # References reagent in syn51730943

# Cell line or model
biologicalResourceType: "Cell Line"
biologicalResourceName: "HEK293"

# Reagent metadata from syn51730943 (shown in tooltip):
# - reagentType: "CRISPR/Cas9"
# - target: "NF1"
# - vector: "pX459"
# - sequence: "AGCT..."
```

## Data Validation Rules

### Required Relationships

1. If `biologicalResourceName` is specified → `biologicalResourceType` must be specified
2. For cell lines: `biologicalResourceName` should equal `individualID`
3. If `modelAge` is specified → `modelAgeUnit` must be specified
4. If `modelSystemName` is specified for xenografts → `biologicalResourceName` should also be specified

### Field Priority

When both donor and model fields exist:

1. **Donor attributes** (species, sex, age, diagnosis) = original donor/cell line
2. **Model attributes** (modelSpecies, modelSex, modelAge) = animal host
3. Donor info takes precedence for biological interpretations

## syn51730943 Lookup Examples

### Cell Line Lookup

```
Query: SELECT * FROM syn51730943
       WHERE toolType = 'cell_line'
       AND toolName = 'JH-2-002'

Returns:
  toolName: "JH-2-002"
  species: "Homo sapiens"
  diagnosis: "Glioblastoma multiforme"
  age: "45 years"
  sex: "Male"
  tissue: "Brain"
  organ: "Cerebrum"
  cellType: "Tumor"
  RRID: "CVCL_1234"
  institution: "Johns Hopkins University"
```

### Animal Model Lookup

```
Query: SELECT * FROM syn51730943
       WHERE toolType = 'animal'
       AND toolName = 'B6.129(Cg)-Nf1tm1Par/J'

Returns:
  toolName: "B6.129(Cg)-Nf1tm1Par/J"
  species: "Mus musculus"
  genotype: "Nf1 tm1Par/+"
  backgroundStrain: "C57BL/6"
  geneticModification: "Nf1 knockout"
  manifestation: "Neurofibromas"
  RRID: "IMSR_JAX:017640"
```

### Antibody Lookup

```
Query: SELECT * FROM syn51730943
       WHERE toolType = 'antibody'
       AND toolName = 'Anti-NF1-mAb'

Returns:
  toolName: "Anti-NF1-mAb"
  target: "NF1"
  host: "Mouse"
  clonality: "Monoclonal"
  clone: "NF1-123"
  isotype: "IgG1"
  RRID: "AB_12345"
  vendor: "Abcam"
```

## Migration from Existing Data

### Step 1: Identify Cell Lines

For records with `modelSystemName` matching cell lines in syn51730943:

```
# Before
modelSystemName: "JH-2-002"
individualID: "JH-2-002"

# After
biologicalResourceType: "Cell Line"
biologicalResourceName: "JH-2-002"
individualID: "JH-2-002"
modelSystemName: null  # (or remove)
```

### Step 2: Identify Xenografts

For records with both cell line and animal model:

```
# Before
modelSystemName: ["JH-2-002", "NSG"]
individualID: "JH-2-002"

# After
biologicalResourceType: "Cell Line"
biologicalResourceName: "JH-2-002"
individualID: "JH-2-002"
modelSystemName: "NSG"
modelSpecies: "Mus musculus"
```

### Step 3: Handle Antibodies

```
# Before
antibodyID: "AB-12345"

# After (both are valid)
antibodyID: "AB-12345"  # Legacy, still works
# OR
biologicalResourceType: "Antibody"
biologicalResourceName: "Anti-NF1-mAb"
```

## Benefits of This Approach

### 1. No Data Duplication
- Donor metadata stored once in syn51730943
- Referenced via `biologicalResourceName`
- Reduces data errors and inconsistencies

### 2. Minimal Schema
- Only 2 reference fields (`biologicalResourceType` + `biologicalResourceName`)
- vs. 20+ fields if metadata was duplicated
- 90% reduction in schema complexity

### 3. Always Up-to-Date
- Corrections to syn51730943 immediately reflected
- No need to update individual records
- Centralized curation

### 4. Better User Experience
- Hover tooltip shows rich context
- Click to view full details
- Easy to suggest edits
- Consistent across all datasets

### 5. Clear Separation of Concerns
- **Donor attributes**: Original patient/cell line (in syn51730943)
- **Model attributes**: Animal host used in experiment (specified per record)
- **Individual attributes**: Specific animal or sample characteristics

## Implementation

### Tooltip Service API

The tooltip service provides metadata lookups:

```bash
# Cell line
GET /api/v1/tooltip/Cell%20Line/JH-2-002

# Animal model
GET /api/v1/tooltip/Animal%20Model/B6.129(Cg)-Nf1tm1Par%2FJ

# Antibody
GET /api/v1/tooltip/Antibody/Anti-NF1-mAb
```

### UI Integration

1. User selects `biologicalResourceType` dropdown
2. User selects/types `biologicalResourceName` (autocomplete from syn51730943)
3. Info icon (ℹ️) appears next to selection
4. Hover → tooltip shows metadata
5. Click → opens detail page

### Form Validation

```javascript
// Validate biologicalResource fields
if (biologicalResourceName && !biologicalResourceType) {
  error("biologicalResourceType required when biologicalResourceName is specified");
}

// For cell lines, ensure individualID matches
if (biologicalResourceType === "Cell Line") {
  if (individualID && individualID !== biologicalResourceName) {
    warning("For cell lines, individualID should match biologicalResourceName");
  }
}

// Ensure model age has units
if (modelAge && !modelAgeUnit) {
  error("modelAgeUnit required when modelAge is specified");
}
```

## Questions?

- See `services/TOOLTIP_APPROACH.md` for detailed tooltip implementation
- See `services/README.md` for tooltip service deployment
- See syn51730943 for the research tools database
