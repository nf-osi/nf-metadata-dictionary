# Field Mapping and Normalization Guide

## Overview

This document explains how biological resources are referenced in the NF metadata schema and how they map to the NF Research Tools Database (syn51730943).

**Key Principle**: Use existing schema fields to reference syn51730943. Detailed metadata is displayed in tooltips, not duplicated in annotation fields.

## Field Mapping to syn51730943

| Schema Field | References | Lookup in syn51730943 | Tooltip Endpoint |
|--------------|------------|----------------------|------------------|
| `individualID` | Cell line (donor) | `toolType='cell_line'` | `/api/v1/tooltip/cell-line/{individualID}` |
| `modelSystemName` | Animal model | `toolType='animal'` | `/api/v1/tooltip/animal-model/{modelSystemName}` |
| `antibodyID` | Antibody | `toolType='antibody'` | `/api/v1/tooltip/antibody/{antibodyID}` |
| `geneticReagentID` | Genetic reagent | `toolType='genetic_reagent'` | `/api/v1/tooltip/genetic-reagent/{geneticReagentID}` |

**No new fields needed!** All references use existing schema fields.

## Field Semantics

### Donor/Individual Attributes

Describe the **original donor** (e.g., human patient from which tumor was derived):

| Field | Description | Example |
|-------|-------------|---------|
| `individualID` | Individual/donor identifier; for cell lines, this IS the cell line name | "JH-2-002" |
| `species` | Donor species | "Homo sapiens" |
| `sex` | Donor sex | "Male" |
| `age` | Donor age | 45 |
| `ageUnit` | Age unit | "years" |
| `diagnosis` | Donor diagnosis | "Glioblastoma multiforme" |
| `organ` | Donor organ/tissue | "Brain" |

**For cell lines**: Donor metadata comes from syn51730943 via `individualID` and is shown in **tooltips**.

### Animal Model Host Attributes

Describe the **animal model host** (for xenografts or model-only experiments):

| Field | Description | Example |
|-------|-------------|---------|
| `modelSystemName` | Genetic model name | "NSG", "B6.129(Cg)-Nf1tm1Par/J" |
| `modelSpecies` | Model species | "Mus musculus" |
| `modelSex` | Individual model animal sex | "Female" |
| `modelAge` | Individual model animal age | 8 |
| `modelAgeUnit` | Model age unit (required if modelAge specified) | "weeks" |

**Genetic information** (genotype, mutations) from `modelSystemName` is in syn51730943 and shown in **tooltips**.

### Treatment/Reagent Attributes

| Field | Description | Example |
|-------|-------------|---------|
| `antibodyID` | Antibody identifier | "AB-12345", "Anti-NF1-mAb" |
| `geneticReagentID` | Genetic reagent identifier | "CRISPR-NF1-KO", "shRNA-TP53-001" |

## Conditional Requirements

### Annotations in props.yaml

Fields can be conditionally required using the `requiresDependency` annotation:

```yaml
modelAge:
  annotations:
    requiresDependency: modelAgeUnit
  description: Age of the individual animal model at time of experiment.
  range: float
  required: false

modelAgeUnit:
  annotations:
    requiresDependency: modelAge
  description: Time unit for modelAge. Required when modelAge is specified.
  range: TimeUnit
  required: false
```

### Validation Rules

1. **If `modelAge` is specified** → `modelAgeUnit` MUST be specified
2. **If `age` is specified** → `ageUnit` MUST be specified
3. **For xenografts**: If `modelSystemName` is specified → should also specify `individualID` (cell line donor)
4. **For cell lines**: `individualID` references the cell line in syn51730943

### Recommended Practices

| Scenario | Required | Recommended |
|----------|----------|-------------|
| Cell line only | `individualID` | None |
| Xenograft | `individualID`, `modelSystemName` | `modelSex`, `modelAge`, `modelAgeUnit` |
| Animal model only | `modelSystemName` | `sex`, `age`, `ageUnit` for individual animal |
| With antibody | Base fields + `antibodyID` | None |
| With genetic reagent | Base fields + `geneticReagentID` | None |

## Usage Scenarios

### Scenario 1: Cell Line Only (Most Common)

Patient-derived cell line used for experiments.

```yaml
# Cell line donor
individualID: "JH-2-002"                 # → Lookup in syn51730943
specimenID: "JH-2-002-rep1"              # Technical replicate 1
specimenID: "JH-2-002-rep2"              # Technical replicate 2

# Donor metadata from syn51730943 (shown in tooltip):
# - species: "Homo sapiens"
# - diagnosis: "Glioblastoma multiforme"
# - age: "45 years"
# - sex: "Male"
# - tissue: "Brain"
# - organ: "Cerebrum"
```

**Tooltip Lookup**:
```
GET /api/v1/tooltip/cell-line/JH-2-002
```

**User Experience**:
- Select `individualID: "JH-2-002"` from dropdown
- Hover over field → tooltip shows donor metadata
- Click → view full details in syn51730943

### Scenario 2: Cell Line in Animal Model (Xenograft)

Human cell line implanted in immunocompromised mouse.

```yaml
# Cell line (donor)
individualID: "JH-2-002"                 # Human tumor donor

# Animal model host
modelSystemName: "NSG"                   # NOD scid gamma mouse
modelSpecies: "Mus musculus"
modelSex: "Female"                       # Individual mouse sex
modelAge: 8                              # Individual mouse age
modelAgeUnit: "weeks"                    # Required with modelAge

# Specimen from xenograft
specimenID: "JH-2-002-NSG-001-tumor"    # Tumor grown in mouse
```

**Multiple Tooltips**:
```
GET /api/v1/tooltip/cell-line/JH-2-002      # Human donor info
GET /api/v1/tooltip/animal-model/NSG        # Mouse model genetic info
```

**Data Flow**:
1. `individualID: "JH-2-002"` → syn51730943 → human donor metadata (tooltip)
2. `modelSystemName: "NSG"` → syn51730943 → mouse model genetic info (tooltip)
3. `modelSex`, `modelAge` → specific to individual mouse used

### Scenario 3: Animal Model Only

Genetically engineered mouse model.

```yaml
# Animal model
modelSystemName: "B6.129(Cg)-Nf1tm1Par/J"
individualID: "mouse-001"                # Specific animal
sex: "Male"                              # Individual animal
age: 12                                  # Individual animal
ageUnit: "weeks"                         # Required with age
species: "Mus musculus"                  # Can be inferred from model

# Specimen
specimenID: "mouse-001-liver"
specimenID: "mouse-001-brain"
```

**Tooltip Lookup**:
```
GET /api/v1/tooltip/animal-model/B6.129(Cg)-Nf1tm1Par%2FJ
```

**Model genetic info from syn51730943**:
- genotype
- backgroundStrain
- geneticModification
- manifestation

### Scenario 4: Western Blot with Multiple Resources

Xenograft sample analyzed with Western blot using antibody.

```yaml
# Cell line (donor)
individualID: "JH-2-002"                 # Human cell line

# Animal model host
modelSystemName: "NSG"
modelSex: "Female"
modelAge: 8
modelAgeUnit: "weeks"

# Antibody used
antibodyID: "Anti-NF1-mAb"               # Primary antibody

# Specimen
specimenID: "JH-2-002-NSG-001-lysate"
assay: "western blot"
```

**Multiple Tooltips** (3 resources):
```
GET /api/v1/tooltip/cell-line/JH-2-002      # Cell line donor
GET /api/v1/tooltip/animal-model/NSG        # Animal model
GET /api/v1/tooltip/antibody/Anti-NF1-mAb   # Antibody
```

**User Experience**:
- Three ℹ️ icons appear (one for each resource)
- Hover over `individualID` → cell line donor metadata
- Hover over `modelSystemName` → animal model genetic metadata
- Hover over `antibodyID` → antibody metadata

### Scenario 5: CRISPR Knockout Cell Line

Cell line with genetic modification using CRISPR.

```yaml
# Cell line
individualID: "HEK293"                   # Parent cell line

# Genetic reagent used
geneticReagentID: "CRISPR-NF1-KO"        # CRISPR construct

# Specimen
specimenID: "HEK293-NF1-KO-clone1"
```

**Multiple Tooltips**:
```
GET /api/v1/tooltip/cell-line/HEK293             # Parent cell line
GET /api/v1/tooltip/genetic-reagent/CRISPR-NF1-KO  # CRISPR construct
```

**Reagent metadata from syn51730943**:
- reagentType: "CRISPR/Cas9"
- target: "NF1"
- vector: "pX459"
- sequence: "..."

## syn51730943 Lookup Details

### Cell Line Lookup

```sql
SELECT * FROM syn51730943
WHERE toolType = 'cell_line'
AND toolName = 'JH-2-002'
```

**Returns**:
```json
{
  "toolName": "JH-2-002",
  "toolType": "cell_line",
  "species": "Homo sapiens",
  "diagnosis": "Glioblastoma multiforme",
  "age": "45 years",
  "sex": "Male",
  "tissue": "Brain",
  "organ": "Cerebrum",
  "cellType": "Tumor",
  "RRID": "CVCL_1234",
  "institution": "Johns Hopkins University"
}
```

### Animal Model Lookup

```sql
SELECT * FROM syn51730943
WHERE toolType = 'animal'
AND toolName = 'B6.129(Cg)-Nf1tm1Par/J'
```

**Returns**:
```json
{
  "toolName": "B6.129(Cg)-Nf1tm1Par/J",
  "toolType": "animal",
  "species": "Mus musculus",
  "genotype": "Nf1 tm1Par/+",
  "backgroundStrain": "C57BL/6",
  "geneticModification": "Nf1 knockout",
  "manifestation": "Neurofibromas",
  "RRID": "IMSR_JAX:017640"
}
```

### Antibody Lookup

```sql
SELECT * FROM syn51730943
WHERE toolType = 'antibody'
AND toolName = 'Anti-NF1-mAb'
```

**Returns**:
```json
{
  "toolName": "Anti-NF1-mAb",
  "toolType": "antibody",
  "target": "NF1",
  "host": "Mouse",
  "clonality": "Monoclonal",
  "clone": "NF1-123",
  "isotype": "IgG1",
  "RRID": "AB_12345",
  "vendor": "Abcam"
}
```

### Genetic Reagent Lookup

```sql
SELECT * FROM syn51730943
WHERE toolType = 'genetic_reagent'
AND toolName = 'CRISPR-NF1-KO'
```

**Returns**:
```json
{
  "toolName": "CRISPR-NF1-KO",
  "toolType": "genetic_reagent",
  "reagentType": "CRISPR/Cas9",
  "target": "NF1",
  "vector": "pX459",
  "guideSequence": "AGCTAGCTAGCTAGCTAGCT",
  "PAM": "NGG",
  "vendor": "Addgene",
  "catalogNumber": "62988"
}
```

## Tooltip Service API

### Endpoints

| Endpoint | Schema Field | Example |
|----------|--------------|---------|
| `GET /api/v1/tooltip/cell-line/{individualID}` | individualID | `/api/v1/tooltip/cell-line/JH-2-002` |
| `GET /api/v1/tooltip/animal-model/{modelSystemName}` | modelSystemName | `/api/v1/tooltip/animal-model/NSG` |
| `GET /api/v1/tooltip/antibody/{antibodyID}` | antibodyID | `/api/v1/tooltip/antibody/AB-12345` |
| `GET /api/v1/tooltip/genetic-reagent/{geneticReagentID}` | geneticReagentID | `/api/v1/tooltip/genetic-reagent/CRISPR-NF1-KO` |

### Response Format

All endpoints return:

```json
{
  "display_name": "JH-2-002",
  "type": "Cell Line",
  "metadata": {
    "Species": "Homo sapiens",
    "Diagnosis": "Glioblastoma multiforme",
    "Age": "45 years",
    "Sex": "Male",
    "Tissue": "Brain",
    "Organ": "Cerebrum",
    "RRID": "CVCL_1234"
  },
  "detail_url": "https://synapse.org/...",
  "edit_url": "https://synapse.org/.../edit",
  "last_updated": "2025-12-22T10:30:00Z"
}
```

## UI Integration

### Form with Multiple Tooltips

```html
<form>
  <!-- Cell line -->
  <div class="field">
    <label>Individual ID</label>
    <input id="individualID" value="JH-2-002">
    <span class="tooltip-icon" data-field="individualID" data-type="cell-line">ℹ️</span>
  </div>

  <!-- Animal model -->
  <div class="field">
    <label>Model System Name</label>
    <input id="modelSystemName" value="NSG">
    <span class="tooltip-icon" data-field="modelSystemName" data-type="animal-model">ℹ️</span>
  </div>

  <!-- Antibody -->
  <div class="field">
    <label>Antibody ID</label>
    <input id="antibodyID" value="Anti-NF1-mAb">
    <span class="tooltip-icon" data-field="antibodyID" data-type="antibody">ℹ️</span>
  </div>
</form>

<script>
// Attach tooltips to all fields
document.querySelectorAll('.tooltip-icon').forEach(icon => {
  const field = icon.dataset.field;
  const type = icon.dataset.type;
  const value = document.getElementById(field).value;

  icon.addEventListener('mouseenter', async () => {
    const response = await fetch(`/api/v1/tooltip/${type}/${encodeURIComponent(value)}`);
    const data = await response.json();
    showTooltip(data, icon);
  });
});
</script>
```

## Validation Rules

### Required Dependencies

Implement these validation rules:

```javascript
// 1. modelAge requires modelAgeUnit
if (modelAge && !modelAgeUnit) {
  error("modelAgeUnit required when modelAge is specified");
}

// 2. age requires ageUnit
if (age && !ageUnit) {
  error("ageUnit required when age is specified");
}

// 3. Xenografts should have both
if (modelSystemName && !individualID) {
  warning("For xenografts, specify individualID (cell line donor)");
}

// 4. Model age/sex are for individual animals
if (modelSex && !modelSystemName) {
  warning("modelSex specified but no modelSystemName");
}
```

### LinkML Annotations

Already defined in props.yaml:

```yaml
modelAge:
  annotations:
    requiresDependency: modelAgeUnit  # Validation enforced
```

## Benefits of This Approach

### 1. Uses Existing Fields
- ✅ No new `biologicalResourceType`/`biologicalResourceName` fields
- ✅ Leverages `individualID`, `modelSystemName`, `antibodyID`, `geneticReagentID`
- ✅ Cleaner schema

### 2. Multiple Resources Per Record
- ✅ Western blot can have: cell line + animal model + antibody
- ✅ Each field gets its own tooltip
- ✅ No need to choose one "primary" resource

### 3. No Data Duplication
- ✅ Donor metadata stored once in syn51730943
- ✅ Referenced via existing fields
- ✅ Reduces data errors

### 4. Conditional Requirements
- ✅ `modelAge` requires `modelAgeUnit` (enforced via annotations)
- ✅ `age` requires `ageUnit`
- ✅ Clear dependency relationships

### 5. Always Up-to-Date
- ✅ Corrections to syn51730943 immediately reflected
- ✅ No need to update individual records
- ✅ Centralized curation

### 6. Clear Separation
- **Donor attributes** (species, sex, age, diagnosis): Original patient/cell line
- **Model attributes** (modelSpecies, modelSex, modelAge): Animal host
- **individualID**: Cell line reference
- **modelSystemName**: Animal model reference
- **antibodyID**: Antibody reference
- **geneticReagentID**: Genetic reagent reference

## Migration Guide

### From Previous Approach

If you have `biologicalResourceType`/`biologicalResourceName`:

```yaml
# OLD (remove these)
biologicalResourceType: "Cell Line"
biologicalResourceName: "JH-2-002"

# NEW (use existing fields)
individualID: "JH-2-002"
```

```yaml
# OLD (remove these)
biologicalResourceType: "Animal Model"
biologicalResourceName: "NSG"

# NEW (use existing fields)
modelSystemName: "NSG"
```

### Field Mapping Table

| Old Field | New Field | Notes |
|-----------|-----------|-------|
| `biologicalResourceType: "Cell Line"` | (remove) | Use `individualID` directly |
| `biologicalResourceName` (cell line) | `individualID` | Same value |
| `biologicalResourceType: "Animal Model"` | (remove) | Use `modelSystemName` directly |
| `biologicalResourceName` (animal) | `modelSystemName` | Same value |
| `biologicalResourceType: "Antibody"` | (remove) | Use `antibodyID` directly |
| `biologicalResourceName` (antibody) | `antibodyID` | Same value |

## Questions?

- See `services/TOOLTIP_APPROACH.md` for tooltip implementation details
- See `services/README.md` for service deployment
- See syn51730943 for the research tools database
- See props.yaml for field definitions and conditional requirements
