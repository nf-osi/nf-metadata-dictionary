# Conditional Enum Filtering Implementation Plan

## Problem Statement

Multiple schema fields have enum values exceeding Synapse's 100-value column limit:
- `modelSystemName`: 809 values (638 cell lines + 122 animal models + 49 other)
- `assay`: 202 values
- `fileFormat`: 118 values
- `platform`: 122 values
- `institutions`: 331 values (PortalStudy only)

**Current Issue**: Truncating to first 100 values loses most valid options and provides poor UX.

## Proposed Solution

Implement **conditional enum filtering** using progressive field dependencies that reduce available options based on user selections in prior fields.

### Strategy

Use multi-level cascading filters:

```
Level 1: modelSystemType → reduces 809 to ~638 or ~122
Level 2: modelSpecies → reduces further by species
Level 3: diagnosis/tumorType → optional additional filtering
Result: modelSystemName → <100 values shown
```

---

## Implementation Plan

### 1. Add Model System Type Field

Add a new `modelSystemType` field to distinguish resource categories:

```yaml
# In modules/Sample/props.yaml or similar
modelSystemType:
  description: "Type of model system used in the study"
  range: ModelSystemTypeEnum

enums:
  ModelSystemTypeEnum:
    permissible_values:
      cell line:
        description: "Cultured cell line"
      animal model:
        description: "Animal model organism"
      organoid:
        description: "3D cell culture model"
      patient-derived xenograft:
        description: "PDX model"
```

### 2. Enrich Truth Table Data

**Option A (Recommended)**: Add species column to syn26450069

Query Cellosaurus/MGI APIs to populate species for each resource:
- Cell lines → usually Homo sapiens or Mus musculus
- Animal models → extract from genotype name

**Option B**: Create species mapping file

Generate `utils/model_system_species_mapping.yaml`:
```yaml
species_mapping:
  "HEK293": "Homo sapiens"
  "Nf1+/-": "Mus musculus"
  # ... etc
```

### 3. Create Enum Subsets

Split `modelSystemName` into contextual subsets:

```yaml
# modules/Sample/CellLineModel.yaml (existing, enhance with species subsets)
enums:
  HumanCellLineModel:
    permissible_values:
      HEK293: {...}
      # ~434 human cell lines

  MouseCellLineModel:
    permissible_values:
      # ~150 mouse cell lines

  # Other species...
```

```yaml
# modules/Sample/AnimalModel.yaml (existing, enhance with species subsets)
enums:
  MouseAnimalModel:
    permissible_values:
      "Nf1+/-": {...}
      # ~100 mouse models

  RatAnimalModel:
    permissible_values:
      # ~15 rat models
```

### 4. Add Conditional Dependencies to JSON Schema

Update schema generation to add `if/then/else` conditionals:

```json
{
  "allOf": [
    {
      "if": {
        "properties": {
          "modelSystemType": { "const": "cell line" },
          "modelSpecies": { "const": "Homo sapiens" }
        },
        "required": ["modelSystemType", "modelSpecies"]
      },
      "then": {
        "properties": {
          "modelSystemName": {
            "items": {
              "enum": ["HEK293", "HeLa", "MCF-7", "..."]
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "modelSystemType": { "const": "animal model" },
          "modelSpecies": { "const": "Mus musculus" }
        },
        "required": ["modelSystemType", "modelSpecies"]
      },
      "then": {
        "properties": {
          "modelSystemName": {
            "items": {
              "enum": ["Nf1+/-", "Nf1fl/fl", "..."]
            }
          }
        }
      }
    }
  ]
}
```

### 5. Reorder Schema Fields

Ensure filter fields appear before filtered fields:

**Current order**:
```
1. platform
2. assayTarget
...
18. modelSpecies
19. modelSystemName
...
```

**Proposed order**:
```
1. modelSystemType (NEW - primary filter)
2. modelSpecies (moved up - secondary filter)
3. diagnosis (moved up - optional tertiary filter)
4. tumorType (moved up - optional tertiary filter)
5. modelSystemName (filtered by above)
6. platform
7. assayTarget
...
```

### 6. Update Entity View Code

Modify `utils/json_schema_entity_view.py` to handle conditional enums:

```python
def _create_columns_from_json_schema(json_schema: dict[str, Any]) -> list[Column]:
    """Creates columns, respecting conditional enum constraints."""

    # Extract conditional rules from allOf
    conditional_enums = _extract_conditional_enums(json_schema)

    for name, prop_schema in properties.items():
        # Check if this field has conditional enums
        if name in conditional_enums:
            # Strategy: Use the UNION of all conditional enum values
            # Or: Don't set enum constraint at column level (let DCA/validation handle it)
            all_possible_values = _get_union_of_conditional_enums(conditional_enums[name])
            if len(all_possible_values) > 100:
                # Too many even with conditionals - no column constraint
                enum_values = None
            else:
                enum_values = all_possible_values[:100]
        else:
            # Regular enum handling
            if "enum" in prop_schema:
                enum_list = prop_schema["enum"]
                enum_values = enum_list[:100] if len(enum_list) > 100 else enum_list
```

**Note**: Synapse columns don't support dynamic enums, so we have two options:
- **Option A**: Set no enum constraint on column (free text), rely on DCA validation
- **Option B**: Set union of all possible values (if <100), DCA shows contextual subset

### 7. Data Curator App Integration

The DCA needs to:
1. Parse `if/then/else` conditionals from JSON Schema
2. Update `modelSystemName` dropdown dynamically when `modelSystemType` or `modelSpecies` changes
3. Show only contextually relevant values

**This may require DCA updates** - check with DCA team.

---

## Expected Results

### Before
- `modelSystemName`: 809 values → truncated to 100 → users can't find their model

### After
- User selects `modelSystemType = "cell line"`
  - `modelSystemName` options reduce to 638 cell lines
- User selects `modelSpecies = "Homo sapiens"`
  - `modelSystemName` options reduce to ~87 human cell lines ✅ Under 100!
- User selects `modelSpecies = "Mus musculus"`
  - `modelSystemName` options reduce to ~150 mouse cell lines → still over 100
  - Need additional filter (diagnosis, or split further by category)

### Breakdown by Species (estimated):

**Cell Lines** (638 total):
- Homo sapiens: ~434 (still need filter)
- Mus musculus: ~150 (still need filter)
- Other: ~54 ✅

**Animal Models** (122 total):
- Mus musculus: ~100 ✅ (just under limit!)
- Other: ~22 ✅

**Still problematic**: Human cell lines. Need additional dimension:
- Could filter by cell line type (iPSC, primary, immortalized, cancer)
- Could filter by NF genotype (NF1+/-, NF1-/-, WT)
- Could filter by disease/tumor type

---

## Alternative Approaches

### Approach 1: No Column Enum Constraint
**Simplest**: Don't set `enum_values` on Synapse column for fields >100.
- ✅ Immediate fix
- ❌ No dropdown in Synapse UI
- ✅ DCA can still validate against full schema

### Approach 2: Separate Fields by Type
Create distinct fields instead of one polymorphic field:
- `cellLineModelSystemName` (638 values)
- `animalModelSystemName` (122 values)

**Pros**: Clearer semantics
**Cons**: Schema changes, backward compatibility issues

### Approach 3: Free Text + Autocomplete
Remove enum entirely, make modelSystemName free text with autocomplete hints.
- ✅ No limits
- ❌ Less validation, more typos

---

## Recommended Next Steps

1. **Validate approach with DCA team** - Confirm DCA can handle conditional enums
2. **Add species to truth table** - Coordinate with data stewards
3. **Implement for modelSystemName first** - Prove the pattern
4. **Apply to other large enums** - Extend to assay, fileFormat, platform
5. **Update documentation** - Add to DESIGN.md

---

## Questions for Discussion

1. **Can DCA parse and respect if/then/else conditionals from JSON Schema?**
2. **Should we add species column to syn26450069, or maintain a mapping file?**
3. **For human cell lines (434 values), what additional filter dimension makes sense?**
   - Cell line category (iPSC, cancer, primary, immortalized)?
   - NF genotype (NF1+/-, NF1-/-, NF2-/-, WT)?
   - Tumor/tissue type?
4. **Should we implement this for all templates, or start with a pilot (e.g., ImagingAssayTemplate)?**

---

## Success Criteria

✅ All filter fields appear before filtered fields in schema
✅ JSON Schema has valid if/then/else conditionals
✅ Each conditional branch has <100 enum values
✅ DCA shows contextual dropdown options
✅ Synapse entity view creation succeeds (no 400 errors)
✅ Users can search full list of valid values through progressive filtering
