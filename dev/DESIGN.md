# Design Docs

## Table of Contents

1. [Contextual Enum Subsets](#contextual-enum-subsets)
2. [Enum Value Sourcing: Curated Sync vs. Dynamic Ontology Enums](#enum-value-sourcing-curated-sync-vs-dynamic-ontology-enums)
3. [Conditional Dependencies (LinkML Rules)](#conditional-dependencies-linkml-rules)
4. [Annotation Review Workflow](#annotation-review-workflow)

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

### When the subset relation can't be expressed in LinkML

`slot_usage` points a slot at a *different, separately declared* enum; it does not derive one enum's values from another's.
That is a problem when two enums have to agree on their labels rather than merely coexist.

The case that prompted recording this is `ManifestationEnum` (`modules/DCC/Portal.yaml`), the facet vocabulary for dataset- and study-level `manifestation`, which is a curated subset of the file-level `Tumor` enum (`modules/Sample/Tumor.yaml`) plus a handful of non-neoplasm phenotype values.
`manifestation` is populated by rolling up the `tumorType` annotations of a dataset's member files, and that rollup carries no vocabulary crosswalk, so a shared concept spelled differently in the two enums simply fails to roll up.

`EnumDefinition`'s `inherits`, `include`, `minus`, and `reachable_from` were each evaluated as a way to state the relation once.
None of them is implemented by `gen-json-schema`, and an enum whose values come only from `inherits` generates a bare `{"type": "string"}` with no `enum` key at all - silently accepting any string instead of constraining the field.
So the shared values are **duplicated by hand** in both files.
That is a deliberate choice, not an oversight; do not refactor it into enum inheritance.

Duplication trades a schema-language guarantee for a drift risk, so the relation is enforced by a test instead: [`tests/test_enum_harmonization.py`](../tests/test_enum_harmonization.py) checks label identity in both directions, plus agreement on `meaning:` and on deprecation status, and requires every `Tumor` value left out of the facet vocabulary to be listed with a stated reason.
See [CONTRIBUTING.md](../CONTRIBUTING.md#relationship-between-tumortype-and-manifestation) for the contributor-facing version of the rule.

A related limitation is worth recording: `is_a` between permissible values is accepted by LinkML and survives into `dist/NF.yaml`, but `gen-rdf` serializes it incorrectly and `sssomgen` drops it, so it is not used here.
Faceted sibling entities therefore do not roll into a shared parent facet.

---

## Enum Value Sourcing: Curated Sync vs. Dynamic Ontology Enums

### Background

LinkML supports [dynamic enums](https://linkml.io/linkml/schemas/enums.html) that materialize permissible values from an ontology branch at build time via `reachable_from` (`source_ontology`, `source_nodes`, `relationship_types`, `is_direct`). A periodic schema review ([#923](https://github.com/nf-osi/nf-metadata-dictionary/issues/923)) recommended adopting this pattern for our large value sets — disease/tumor (MONDO/NCIT), cell lines (Cellosaurus), institutions (ROR), species (NCBITaxon).

While this feature *sounds* good, it does not fit this model's constraints. Our conscious design decision is to **deliberately not adopt `reachable_from`** for our large enums, recorded here to help disabuse contributors missing context.   

### Many of our large enums are **not** ontology branches

The two largest synced enums are **not** "all descendants of an ontology node," so `reachable_from` cannot generate them in the first place:

- **`CellLineModel`** (`modules/Sample/CellLineModel.yaml`) and **`AntibodyEnum`** (`modules/Experiment/Antibody.yaml`) are **auto-generated from the NF Research Tools Central truth tables in Synapse** (`syn26450069`, `syn51730943`) by `utils/sync_model_systems.py`. Their members are the specific reagents and cell lines that NF investigators have registered — each carrying a curated `source` link back to its Tools Central detail page (and, where known, an RRID / `rrid:CVCL_*` `meaning`). This is *already* a dynamic sync; it just sources from *our community's* authoritative registry rather than a public ontology branch. There is no Cellosaurus subtree that corresponds to "NF cell lines," so `reachable_from` would either under-cover (miss unregistered/community lines) or over-cover (pull in thousands of irrelevant lines).

New reagents and cell lines are added to the Tools Central registry and flow into these enums through the weekly sync. A build-time `reachable_from` materialization would have no place to absorb that community-driven vocabulary growth.

### Why we don't pull whole ontology branches even where one exists

For value sets that *do* map to an ontology branch, two hard constraints still rule out materializing the full branch:

1. **Downstream UI limits.** The model is instantiated in a web application (the Synapse Curator UI) where each enum becomes a dropdown. Consider the size limits in the total JSON schema and performance considerations.

2. **We don't want the whole branch — we want the relevant slice.** Pulling every descendant optimizes for completeness of the ontology but not usefulness/good experience to an NF curator:
   - **`Institution` / `Organization`** (`modules/Other/Organization.yaml`): ROR contains **110,000+** institutions. NF data comes from a small, known set of contributing sites. A dropdown seeded from all of ROR is worse than the curated list, not better.
   - **`Tumor`** (`modules/Sample/Tumor.yaml`): ~61 hand-picked, NF-relevant tumor types (curated from OncoTree / NCIT / MONDO). The full NCIT/MONDO neoplasm branch is thousands of terms, the vast majority of which are irrelevant to NF and would bury the ~61 needed.

### The value we'd lose

Our permissible values carry **bespoke, curated context** that a generated branch does not reproduce:

- `Tumor` entries carry hand-written `description`s (e.g., the ANNUBP provisional-classification note, "Atypical MPNST" positioning between neurofibroma and high-grade MPNST) plus `aliases` for how NF investigators actually refer to them.
- Synced reagent enums carry `source` links into Tools Central and RRIDs.

`reachable_from` would replace these with generic ontology labels and definitions, losing the curation that makes the dropdowns usable in an NF context.

### Our approach instead

We get the maintainability benefit that dynamic enums promise, without the downsides, by:

- **Syncing from authoritative sources we control the scope of** — Tools Central truth tables via `utils/sync_model_systems.py`, ontology synonyms via `utils/extract_synonyms.py` / `inject_synonyms.py`.
- **Curating the relevant slice by hand** where an ontology branch is too broad (`Tumor`, `Institution`), keeping `source`/`meaning` links to the ontology for provenance without inheriting the whole branch.
- **Absorbing real-world vocabulary** through registry updates (and, planned, annotation review; see [Annotation Review Workflow](#annotation-review-workflow)) rather than a static branch snapshot.
- **Splitting large enums into [contextual subsets](#contextual-enum-subsets)** so any single dropdown stays small.

### When `reachable_from` *would* be appropriate

If a future value set is genuinely "every descendant of node X," is small enough to satisfy the ~100-value UI limit, needs no NF-specific descriptions/aliases, and has no community-registry or free-text feedback loop, then `reachable_from` is the right tool and should be used. None of our current large enums meet all four conditions.

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

**Status: removed (November 2026).** `utils/review_annotations.py` used to run in the weekly model system sync and add free-text annotation values (2+ uses) to enum YAML automatically. It was removed in [#904](https://github.com/nf-osi/nf-metadata-dictionary/issues/904) because it required a login token that lacked download scope, it queried a view (syn52702673) that has none of the reviewed columns, it put every new `platform` value into `SequencingPlatformEnum`, and its `antibodyID`/`geneticReagentID` additions were overwritten by the Tools Central sync.

Follow-up work:
- `platform` review (anonymous access, correct source view and target enum, report instead of auto-edit): [#1048](https://github.com/nf-osi/nf-metadata-dictionary/issues/1048)
- `antibodyID` / `geneticReagentID` review against Tools Central: [nf-research-tools-schema#381](https://github.com/nf-osi/nf-research-tools-schema/issues/381)
- `individualID` is already reviewed in nf-research-tools-schema (`scripts/review_tool_annotations.py`).

### Workflow Coordination

| Workflow | Purpose | Frequency |
|----------|---------|-----------|
| **weekly-model-system-sync** | Sync model systems and tools from Tools Central (anonymous Synapse access) | Weekly (Mon 9am UTC) |
| **synonyms** | Extract ontology synonyms → add as aliases | On release |
| **rebuild-artifacts-on-main** | Rebuild schema artifacts | On push to main |

Manual trigger: `gh workflow run weekly-model-system-sync.yml`
