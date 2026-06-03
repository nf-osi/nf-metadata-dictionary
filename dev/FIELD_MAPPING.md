# Field Mapping and Normalization Guide

## Overview

This document explains how biological resources are referenced in the NF metadata schema and how they map to the NF Research Tools Database (syn51730943).

**Key Principle**: Use existing schema fields to reference syn51730943. Resource detail page links are stored directly in the schema using `see_also` fields, making them accessible to the webdev team without requiring REST API calls.

## Field Mapping to syn51730943

| Schema Field | References | Resource Type in syn51730943 | Link Location |
|--------------|------------|------------------------------|---------------|
| `individualID` | Cell line (donor) | `resourceType='Cell Line'` | Schema `see_also` field |
| `modelSystemName` | Animal model | `resourceType='Animal Model'` | Schema `see_also` field |
| `antibodyID` | Antibody | `resourceType='Antibody'` | Schema `see_also` field |
| `geneticReagentID` | Genetic reagent | `resourceType='Genetic Reagent'` | Schema `see_also` field |

**No new fields needed!** All references use existing schema fields.

## Resource Links in Schema

### How Links Are Stored

For enum-based fields (Cell Line, Animal Model), resource detail page links are stored directly in the schema:

```yaml
# Example: CellLineModel.yaml
enums:
  CellLineEnum:
    permissible_values:
      "JH-2-002":
        description: "Collected during surgical resection from patients with NF1-MPNST"
        see_also:
          - https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=1bc84ef2-208f-4f0e-8045-6be47fd968de
```

### How Links Are Maintained

A GitHub Actions workflow (`.github/workflows/update-tool-links.yml`) automatically:
1. Queries syn51730943 weekly for all resources
2. Updates `see_also` links in schema files
3. Creates a pull request with changes

**Manual update:**
```bash
python scripts/add_tool_links.py
```

### Accessing Links from JSON Schema

The webdev team can access these links directly from the generated JSON schemas:

```json
{
  "enums": {
    "CellLineEnum": {
      "JH-2-002": {
        "description": "Collected during surgical resection from patients with NF1-MPNST",
        "see_also": [
          "https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=1bc84ef2-208f-4f0e-8045-6be47fd968de"
        ]
      }
    }
  }
}
```

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

**For cell lines**: Donor metadata comes from syn51730943 via `individualID`. The detail page link is in the schema's `see_also` field.

### Animal Model Host Attributes

Describe the **animal model host** (for xenografts or model-only experiments):

| Field | Description | Example |
|-------|-------------|---------|
| `modelSystemName` | Genetic model name | "NSG", "B6.129(Cg)-Nf1tm1Par/J" |
| `modelSpecies` | Model species | "Mus musculus" |
| `modelSex` | Individual model animal sex | "Female" |
| `modelAge` | Individual model animal age | 8 |
| `modelAgeUnit` | Model age unit (required if modelAge specified) | "weeks" |

**Genetic information** (genotype, mutations) from `modelSystemName` is in syn51730943. The detail page link is in the schema's `see_also` field.

### Treatment/Reagent Attributes

| Field | Description | Example |
|-------|-------------|---------|
| `antibodyID` | Antibody identifier (enum + custom values) | "Anti-NF1 monoclonal antibody", "Rabbit anti-NF1 Antibody, Affinity Purified" |
| `geneticReagentID` | Genetic reagent identifier (enum + custom values) | "lentiCRISPRv2.sgNf1.4", "pLV-H1-SGIPZ_NF1 sh1miR" |

**Resource details** come from syn51730943. The detail page link is in the schema's `see_also` field for values in the controlled vocabulary. Custom values outside the enum are also permitted.

## Conditional Requirements

### modelAge → modelAgeUnit

If `modelAge` is specified, `modelAgeUnit` is **required**.

```yaml
# ✅ Valid
modelAge: 8
modelAgeUnit: "weeks"

# ❌ Invalid - missing modelAgeUnit
modelAge: 8
```

## Usage Examples

### Example 1: Cell Line Only

Cultured cell line experiment:

```yaml
individualID: "JH-2-002"              # Cell line name
specimenID: "JH-2-002-rep1"           # Technical replicate
assay: "western blot"
```

**Resource Link**: Available in schema `see_also` for "JH-2-002" enum value

**User Experience**:
- Select `individualID: "JH-2-002"` from dropdown
- Hover over field → tooltip shows preview and link
- Click → opens NF Tools Central detail page

### Example 2: Xenograft (Human Cell Line in Mouse)

Human tumor cells implanted in mouse host:

```yaml
individualID: "JH-2-002"              # Human donor cell line
modelSystemName: "NSG"                # Mouse model host
modelSex: "Female"                    # Individual mouse
modelAge: 8
modelAgeUnit: "weeks"
specimenID: "JH-2-002-NSG-001"
assay: "bulk RNA-seq"
```

**Two Resource Links**:
- Cell line: `see_also` in "JH-2-002" enum value
- Animal model: `see_also` in "NSG" enum value

**Data Flow**:
1. `individualID: "JH-2-002"` → schema → human donor link
2. `modelSystemName: "NSG"` → schema → mouse model genetic link
3. `modelSex`, `modelAge` → specific to individual mouse used

### Example 3: Animal Model Only

Mouse with genetic modification:

```yaml
modelSystemName: "B6.129(Cg)-Nf1tm1Par/J"
modelSex: "Male"
modelAge: 12
modelAgeUnit: "weeks"
specimenID: "NF1-mouse-001"
assay: "bulk RNA-seq"
```

**Resource Link**: Available in schema `see_also` for "B6.129(Cg)-Nf1tm1Par/J" enum value

### Example 4: Western Blot (Multiple Resources)

Western blot of xenograft sample:

```yaml
individualID: "JH-2-002"              # Cell line
modelSystemName: "NSG"                # Animal model
antibodyID: "Anti-NF1-mAb"            # Antibody (free-text)
assay: "western blot"
specimenID: "JH-2-002-NSG-WB-001"
```

**Resource Links**:
- Cell line "JH-2-002": Link in schema `see_also`
- Animal model "NSG": Link in schema `see_also`
- Antibody (if from controlled vocabulary): Link in schema `see_also`

### Example 5: CRISPR Knockout

Genetically modified cell line:

```yaml
individualID: "HEK293"                # Parent cell line
geneticReagentID: "CRISPR-NF1-KO"     # CRISPR construct (free-text)
specimenID: "HEK293-NF1KO-clone3"
assay: "western blot"
```

**Resource Links**:
- Cell line "HEK293": Link in schema `see_also`
- Genetic reagent (if from controlled vocabulary): Link in schema `see_also`

## Schema Benefits

### 1. No Data Duplication
- Single source of truth: syn51730943
- Schema only stores names/IDs and links
- Detailed metadata lives in NF Tools Central

### 2. Easy Access for Webdev
- Links embedded directly in schema/JSON schema
- No REST API calls needed
- Can parse schema once and cache

### 3. Always Up-to-Date
- Weekly automated sync via GitHub Actions
- PRs show exactly what changed
- Easy to review and merge

### 4. Multiple Resources Per Record
- Western blot can reference: cell line + animal model + antibody
- Each field has its own link
- No need to choose one "primary" resource

## Validation Rules

### Required Fields

**Base requirements** (all records):
- `individualID` OR `modelSystemName` (at least one required)
- `specimenID` (unique identifier)

**Conditional requirements**:
- If `modelAge` specified → `modelAgeUnit` required

### Valid Combinations

```yaml
# ✅ Cell line only
individualID: "JH-2-002"

# ✅ Animal model only
modelSystemName: "NSG"
modelAge: 8
modelAgeUnit: "weeks"

# ✅ Both (xenograft)
individualID: "JH-2-002"
modelSystemName: "NSG"
modelAge: 8
modelAgeUnit: "weeks"

# ❌ Neither
# Must have at least one
```

## Implementation Details

### Workflow Files

- **`.github/workflows/update-tool-links.yml`**: Automated weekly sync
- **`scripts/add_tool_links.py`**: Script to add new tools and links

### How It Works

1. **Query syn51730943**: Get all resources with their `resourceId` values
2. **Build URLs**: `https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId={resourceId}`
3. **Update YAML**: Add `see_also` links to enum values
4. **Rebuild**: Regenerate JSON schemas with links
5. **PR**: Create pull request with changes

### Manual Sync

```bash
# Dry run (preview changes)
python scripts/add_tool_links.py --dry-run

# Add new tools and links
python scripts/add_tool_links.py
```

## UI Integration Ideas

### Tooltip with Link Preview

```html
<div class="field">
  <label>Individual ID</label>
  <select id="individualID">
    <option value="JH-2-002" data-link="https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=...">
      JH-2-002
    </option>
  </select>
  <span class="info-icon" data-field="individualID">ℹ️</span>
</div>

<script>
// Show tooltip on hover
document.querySelector('.info-icon').addEventListener('mouseenter', (e) => {
  const select = document.getElementById('individualID');
  const option = select.selectedOptions[0];
  const link = option.dataset.link;

  showTooltip({
    name: option.value,
    link: link,
    preview: "Click to view details in NF Tools Central"
  });
});
</script>
```

### Direct Link Button

```html
<div class="field-with-link">
  <label>Individual ID</label>
  <select id="individualID">...</select>
  <a href="#" class="view-details" onclick="openResourceLink(this)">View Details</a>
</div>

<script>
function openResourceLink(button) {
  const select = button.previousElementSibling;
  const option = select.selectedOptions[0];
  const link = option.dataset.link;
  window.open(link, '_blank');
}
</script>
```

## Questions?

- See `.github/workflows/README.md` for workflow details
- See `scripts/README.md` for script usage
- See syn51730943 for the research tools database
- See `props.yaml` for field definitions and conditional requirements
