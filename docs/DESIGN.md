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
