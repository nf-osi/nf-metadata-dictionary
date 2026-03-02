# Design Docs

## Table of Contents

1. [Contextual Enum Subsets](#contextual-enum-subsets)
2. [Conditional Dependencies (LinkML Rules)](#conditional-dependencies-linkml-rules)
3. [Annotation Review Workflow](#annotation-review-workflow)

---

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

### When to Use

- Create enum subsets when a general enum exceeds ~30-50 values
- Apply slot_usage when templates have clear domain context (sequencing, imaging, clinical, etc.)
- Use `any_of` for cross-domain templates or generic base templates

---

## Conditional Dependencies (LinkML Rules)

### Background

Conditional slot dependencies (e.g., "if age is provided, ageUnit must also be provided") were originally expressed using a custom `requiresDependency` annotation specific to schematic. These have been migrated to LinkML's native [rules framework](https://linkml.io/linkml/schemas/advanced.html).

### Current State: Dual System

Both representations are maintained for backward compatibility:

1. **LinkML rules** in template classes (`modules/Template/*.yaml`) — standards-compliant
2. **`requiresDependency` annotations** in slot definitions (`modules/props.yaml`) — schematic compatibility

When schematic is updated to read LinkML rules natively, the duplicate annotations can be removed.

### Pattern

```yaml
# In modules/Template/Data.yaml
BiologicalAssayDataTemplate:
  rules:
    - description: If age is provided, ageUnit must be provided
      preconditions:
        slot_conditions:
          age:
            value_presence: PRESENT
      postconditions:
        slot_conditions:
          ageUnit:
            value_presence: PRESENT
```

We use `value_presence: PRESENT` (slot must have a non-null value) rather than `required: true` (slot key must exist) because our semantics are "if A has a value, B must have a value."

### Key Design Decisions

- **Rules defined contextually** in template classes where slots are used, not globally on slots
- **Rule inheritance:** Rules in abstract base classes (e.g., `BiologicalAssayDataTemplate`) automatically apply to all subclasses
- **Standards-compliant:** Compatible with LinkML validators and generators

### Migrated Dependencies

| Slot Dependency | Templates |
|-----------------|-----------|
| age → ageUnit | BiologicalAssayDataTemplate |
| aliquotID → specimenID | GeneralMeasureDataTemplate, MicroscopyAssayTemplate |
| compoundDose → compoundDoseUnit | BehavioralAssayTemplate, ClinicalAssayTemplate, GeneralMeasureDataTemplate, PharmacokineticsAssayTemplate, PlateBasedReporterAssayTemplate |
| concentrationMaterial → concentrationMaterialUnit | MaterialScienceAssayTemplate |
| concentrationNaCl → concentrationNaClUnit | MaterialScienceAssayTemplate, LightScatteringAssayTemplate |
| dataType → dataSubtype | BiologicalAssayDataTemplate |
| experimentalTimepoint → timepointUnit | BehavioralAssayTemplate, ElectrophysiologyAssayTemplate, GeneralMeasureDataTemplate, GenomicsAssayTemplateExtended, MRIAssayTemplate, PdxGenomicsAssayTemplate, PharmacokineticsAssayTemplate, PlateBasedReporterAssayTemplate |
| genePerturbed → genePerturbationType, genePerturbationTechnology | BehavioralAssayTemplate, GeneralMeasureDataTemplate, GenomicsAssayTemplateExtended, RNASeqTemplate, ScRNASeqTemplate |
| genomicReference → genomicReferenceLink | ProcessedAlignedReadsTemplate |
| parentSpecimenID → specimenID | GeneralMeasureDataTemplate, MicroscopyAssayTemplate |
| transplantationType → transplantationRecipientSpecies, transplantationRecipientTissue | PdxGenomicsAssayTemplate |
| workflow → workflowLink | ProcessedAlignedReadsTemplate, ProcessedExpressionTemplate, ProcessedMergedDataTemplate, ProcessedVariantCallsTemplate, WorkflowReport |
| workingDistance → workingDistanceUnit | MicroscopyAssayTemplate |

---

## Annotation Review Workflow

### Overview

The annotation review workflow automatically analyzes file annotations from Synapse to identify free-text values that could be standardized as enum values in the metadata dictionary. It runs as part of the **weekly model system sync** (`.github/workflows/weekly-model-system-sync.yml`) every Monday at 9:00 AM UTC.

Related issues: [#804](https://github.com/nf-osi/nf-metadata-dictionary/issues/804), [#805](https://github.com/nf-osi/nf-metadata-dictionary/issues/805)

### Design

**Custom enum values:** Some fields (e.g., `platform`) accept both predefined enum values and custom free-text via `any_of` with a `string` range. This allows users to enter new terms immediately while tracking them for potential standardization.

**Automated review** (`utils/review_annotations.py`):
1. Queries Synapse materialized view (syn52702673) for file annotations
2. Compares values against schema enum definitions (including synonyms/aliases)
3. Identifies free-text values not matching any enum
4. Automatically adds values appearing 2+ times to the appropriate YAML enum files
5. Generates summary files documenting additions

**Combined workflow:** The annotation review runs sequentially after model system sync, contributing to a single PR if either operation has updates. This keeps all weekly maintenance in one place.

### Tool-Related Fields

Tool-related annotation fields (e.g., `individualID`) are reviewed in a **separate workflow** in [nf-research-tools-schema](https://github.com/nf-osi/nf-research-tools-schema). This co-locates tool annotation review with existing tool database sync workflows and avoids duplicate review.

All other annotation fields with custom-value-capable enums are reviewed here.

### Workflow Coordination

| Workflow | Purpose | Frequency |
|----------|---------|-----------|
| **weekly-model-system-sync** | Sync model systems + review annotations | Weekly (Mon 9am UTC) |
| **synonyms** | Extract ontology synonyms → add as aliases | On release |
| **rebuild-artifacts-on-main** | Rebuild schema artifacts | On push to main |

Together these provide truth table synchronization, ontology-driven standardization, and user-driven vocabulary expansion.

### Reviewing Suggestions

When the workflow creates a PR:
1. Review `annotation_suggestions.md` for a summary of additions
2. Evaluate each suggestion — legitimate new term, typo, or alias for existing value?
3. Check whether adding values would approach Synapse's 100-value-per-enum limit
4. Merge, revise, or close with notes

### Configuration

Key settings in `utils/review_annotations.py`:
- `MATERIALIZED_VIEW_ID` — Synapse view to query (syn52702673)
- `CUSTOM_VALUE_FIELDS` — Fields that accept free-text (e.g., `platform`)
- `TOOL_RELATED_FIELDS` — Fields excluded from this review (handled by tools repo)
- `MIN_FREQUENCY` — Minimum occurrences for a suggestion (default: 2)

Manual trigger: `gh workflow run weekly-model-system-sync.yml`
