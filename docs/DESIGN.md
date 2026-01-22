# Design Docs

## Contextual Enum Subsets

### Overview

The data model uses **contextual enum subsets** to provide users with relevant, focused dropdown options rather than presenting large monolithic enumerations containing hundreds of values.

This pattern leverages LinkML's [slot_usage](https://linkml.io/linkml/schemas/slots.html#slot-usage) feature to refine slot definitions within specific class contexts.

### Design Pattern

**Enum Organization:**
- Large enums (assays, platforms, file formats) are split into domain-specific subsets
- Each subset groups semantically related values (e.g., sequencing assays vs. imaging assays)
- Base slot definitions (in `props.yaml`) use `any_of` to effectively define a union, accepting values from all relevant subsets

**Template Constraints:**
Templates apply `slot_usage` to restrict slots to contextually appropriate enum subsets:

```yaml
SequencingTemplate:
  slot_usage:
    assay:
      range: SequencingAssayEnum
    platform:
      range: SequencingPlatformEnum
    fileFormat:
      range: SequencingFileFormatEnum
```

**Multiple Context Support:**
When templates span multiple contexts, use `any_of` in slot_usage to define a union of enum subsets:

```yaml
EpigenomicsAssayTemplate:
  slot_usage:
    platform:
      any_of:
      - range: SequencingPlatformEnum
      - range: ArrayPlatformEnum
```

### Benefits

- **Better UX**: Users see only relevant options for their context
- **Performance**: Templates are smaller and faster to load with constrained enum ranges
- **Type Safety**: Templates enforce appropriate value constraints
- **Maintainability**: Logical grouping makes enums easier to extend
- **Backward Compatibility**: Generic templates remain flexible via `any_of`

### When to Use

- Create enum subsets when a general enum exceeds ~30-50 values
- Apply slot_usage when templates have clear domain context (sequencing, imaging, clinical, etc.)
- Use `any_of` for cross-domain templates or generic base templates

---

## Conditional Enum Filtering (Synapse 100-Value Limit)

### Problem

Synapse enforces a **100-value limit** on enum fields in entity views and file views. Some enums exceed this limit:
- `modelSystemName`: 638 cell lines + 123 animal models = 761 values
- Other large enums: `assay`, `fileFormat`, `platform`, `institutions`

### Solution

**Cascading filter fields** that progressively narrow options before showing the final enum field. This keeps all subsets under 100 values.

### Implementation for modelSystemName

Four filter fields cascade to reduce options:

```
modelSystemType → modelSpecies → cellLineCategory → cellLineGeneticDisorder → modelSystemName
   (4 values)         (10+)            (8)                  (3)                  (<100)
```

**Example flow:**
1. User selects `modelSystemType: "cell line"` → narrows to 638 values
2. User selects `modelSpecies: "Homo sapiens"` → narrows to ~400 values
3. User selects `cellLineCategory: "Cancer cell line"` → narrows to ~100 values
4. User selects `cellLineGeneticDisorder: "Neurofibromatosis type 1"` → narrows to 54 values ✅
5. `modelSystemName` dropdown shows only the 54 relevant options

### JSON Schema Implementation

Implemented using `if/then` conditionals with **fully inlined enum values** (no `$defs`):

```json
{
  "allOf": [
    {
      "if": {
        "properties": {
          "modelSystemType": {"const": "cell line"},
          "modelSpecies": {"const": "Homo sapiens"},
          "cellLineCategory": {"const": "Cancer cell line"},
          "cellLineGeneticDisorder": {"const": "Neurofibromatosis type 1"}
        },
        "required": ["modelSystemType", "modelSpecies", "cellLineCategory", "cellLineGeneticDisorder"]
      },
      "then": {
        "properties": {
          "modelSystemName": {
            "items": {
              "enum": ["90-8", "ST88-14", "...54 values total..."],
              "type": "string"
            }
          }
        }
      }
    }
  ]
}
```

**Note:** Synapse doesn't support `$defs` keyword, so all enum values are inlined directly in each conditional.

### Data Source and Maintenance

**Source:** `modules/Sample/generated/*.yaml` files (29 filtered subsets)
- Auto-generated weekly from syn51730943 (NF Tools Central)
- Updated by `.github/workflows/weekly-model-system-sync.yml`

**Build process:**
1. `utils/sync_model_systems.py` - Fetches data, generates filtered YAML files
2. `utils/add_conditional_enum_filtering.py` - Reads YAMLs, creates if/then conditionals
3. `utils/gen-json-schema-class.py` - Generates final JSON schemas with inlined values

**Scripts:**
```bash
# Regenerate everything
python utils/sync_model_systems.py --synapse-id syn51730943
python utils/add_conditional_enum_filtering.py
python utils/gen-json-schema-class.py
```

### Verification

All 28 unique conditionals maintain subsets under 100 values:
- Largest: 54 values (Human NF1 cancer cell lines)
- Smallest: 1 value
- Average: ~15 values

This ensures Synapse compatibility while maintaining full data coverage (all 761 model systems remain accessible).
