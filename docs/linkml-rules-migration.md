# LinkML Rules Migration Guide

## Overview

This guide documents the migration from custom `requiresDependency` annotations to LinkML's native rules framework with preconditions and postconditions.

## Background

### Previous Approach (Schematic-specific)

Previously, conditional slot dependencies were expressed using a custom `requiresDependency` annotation:

```yaml
# In modules/props.yaml
age:
  annotations:
    requiresDependency: ageUnit
  description: A numeric value representing age of the individual. Use with `ageUnit`.
  range: float
  required: false
```

This approach:
- Worked with schematic but was not part of the LinkML standard
- Was defined globally at the slot level
- Limited to simple one-to-one dependencies

### New Approach (LinkML Rules)

Now, dependencies are expressed using LinkML rules in template classes:

```yaml
# In modules/Template/Data.yaml
BiologicalAssayDataTemplate:
  abstract: true
  slots:
    - age
    - ageUnit
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

This approach:
- Uses LinkML's native rules framework ([documentation](https://linkml.io/linkml/schemas/advanced.html))
- Is standards-compliant and compatible with LinkML tooling
- Allows more expressive conditional logic
- Defines rules contextually where slots are used

## Migration Status

### Current State: Dual System

Both representations are currently maintained:

1. **LinkML rules** in template classes (`modules/Template/Data.yaml`)
2. **requiresDependency annotations** in slot definitions (`modules/props.yaml`)

This ensures:
- ✅ Backward compatibility with schematic
- ✅ Forward compatibility with LinkML-native tools
- ✅ Zero breaking changes during transition

### Migrated Dependencies

All 6 original `requiresDependency` relationships have been migrated to LinkML rules, plus 7 new conditional dependencies were added:

| Slot Dependency | LinkML Rules Added To |
|-----------------|----------------------|
| age → ageUnit | BiologicalAssayDataTemplate |
| **aliquotID → specimenID** | GeneralMeasureDataTemplate, MicroscopyAssayTemplate |
| compoundDose → compoundDoseUnit | BehavioralAssayTemplate, ClinicalAssayTemplate, GeneralMeasureDataTemplate, PharmacokineticsAssayTemplate, PlateBasedReporterAssayTemplate |
| **concentrationMaterial → concentrationMaterialUnit** | MaterialScienceAssayTemplate |
| **concentrationNaCl → concentrationNaClUnit** | MaterialScienceAssayTemplate, LightScatteringAssayTemplate |
| dataType → dataSubtype | BiologicalAssayDataTemplate |
| experimentalTimepoint → timepointUnit | BehavioralAssayTemplate, ElectrophysiologyAssayTemplate, GeneralMeasureDataTemplate, GenomicsAssayTemplateExtended, MRIAssayTemplate, PdxGenomicsAssayTemplate, PharmacokineticsAssayTemplate, PlateBasedReporterAssayTemplate |
| **genePerturbed → genePerturbationType, genePerturbationTechnology** | BehavioralAssayTemplate, GeneralMeasureDataTemplate, GenomicsAssayTemplateExtended, RNASeqTemplate, ScRNASeqTemplate |
| **genomicReference → genomicReferenceLink** | ProcessedAlignedReadsTemplate |
| **parentSpecimenID → specimenID** | GeneralMeasureDataTemplate, MicroscopyAssayTemplate |
| **transplantationType → transplantationRecipientSpecies, transplantationRecipientTissue** | PdxGenomicsAssayTemplate |
| workflow → workflowLink | ProcessedAlignedReadsTemplate, ProcessedExpressionTemplate, ProcessedMergedDataTemplate, ProcessedVariantCallsTemplate, WorkflowReport |
| workingDistance → workingDistanceUnit | MicroscopyAssayTemplate |

**New dependencies added** (shown in bold) improve data quality by ensuring:
- Specimen hierarchy is properly tracked (aliquotID/parentSpecimenID → specimenID)
- Gene perturbation experiments include complete metadata (type AND technology)
- Reference genomes are properly documented (genomicReference → link)
- PDX experiments include recipient details (transplantationType → species, tissue)
- Concentration measurements include units (concentrationMaterial/NaCl → units)

## For Contributors

### Adding a New Conditional Dependency

When you need to add a new conditional dependency between slots:

1. **Add the LinkML rule to the appropriate template:**

```yaml
# In modules/Template/Data.yaml (or appropriate template file)
MyTemplate:
  slots:
    - slotA
    - slotB
  rules:
    - description: If slotA is provided, slotB must be provided
      preconditions:
        slot_conditions:
          slotA:
            value_presence: PRESENT
      postconditions:
        slot_conditions:
          slotB:
            value_presence: PRESENT
```

2. **Add the annotation for schematic compatibility:**

```yaml
# In modules/props.yaml
slotA:
  annotations:
    requiresDependency: slotB
  description: ...
  required: false
```

3. **Update the README documentation:**

Add your new dependency to the table in README.md (after line 204).

4. **Test your changes:**

```bash
# Validate YAML syntax
python3 -c "import yaml; yaml.safe_load(open('modules/Template/Data.yaml'))"

# Build the schema (requires full dev environment)
make all
```

### Understanding `value_presence: PRESENT`

We use `value_presence: PRESENT` instead of `required: true` because:

- `required: true` → slot key must exist in instance
- `value_presence: PRESENT` → slot must have a non-null value
- Our semantics: "if A has a value, B must have a value"

This is more precise and matches the current behavior of `requiresDependency`.

### Rule Inheritance

Rules defined in abstract base classes (like `BiologicalAssayDataTemplate`) are inherited by all subclasses. This means:

- Define common rules once in the base template
- They automatically apply to all derived templates
- No need to duplicate rules across similar templates

## Benefits of LinkML Rules

1. **Standards-compliant:** Native LinkML feature, not custom annotation
2. **More expressive:** Can handle complex conditional logic beyond simple dependencies
3. **Better tooling:** Compatible with standard LinkML validators and generators
4. **Contextual:** Rules defined where slots are used, making relationships clear
5. **Self-documenting:** Rule descriptions explain the dependency logic

## Enum Validation for Conditional Dependencies

All slots involved in conditional dependencies now have proper enum validation to ensure data quality:

| Slot | Enum | Values |
|------|------|--------|
| genePerturbationType | GenePerturbationEnum | knockdown, knockout, overexpression, non-targeting control |
| genePerturbationTechnology | GenePerturbationTechnologyEnum | CRISPR, RNAi, CRE Recombinase |
| genomicReference | GenomicReferenceEnum | GRCh37, GRCh38, GRCh38_Verily_v1, HRC, MMUL1.0, mm10, mm39, rn6 |
| transplantationType | TransplantationType | xenograft, allograft, autograft, isograft |
| transplantationRecipientSpecies | (inline) | Human, Mouse |
| concentrationMaterialUnit | ConcentrationUnit | mM, mg/mL, particles/mL |
| concentrationNaClUnit | ConcentrationUnit | mM, mg/mL, particles/mL |
| workingDistanceUnit | WorkingDistanceUnitEnum | angstrom, nanometer, micrometer, millimeter, centimeter |

**Note:** All enum values include ontology mappings (`meaning`) or source references where available, ensuring semantic interoperability.

## Future Roadmap

### Phase 1 (Current): Dual System

- ✅ LinkML rules added to all templates
- ✅ requiresDependency annotations maintained in props.yaml
- ✅ Both systems kept in sync
- ✅ Zero breaking changes

### Phase 2 (Future): Single System

When schematic is updated to read LinkML rules natively, or when retold is enhanced to convert rules to annotations:

1. Remove duplicate `requiresDependency` annotations from props.yaml
2. Rely solely on LinkML rules
3. Simplify maintenance (single source of truth)

**Timeline:** TBD based on schematic/retold development

## References

- [LinkML Rules Documentation](https://linkml.io/linkml/schemas/advanced.html)
- [LinkML value_presence](https://linkml.io/linkml-model/latest/docs/PresenceEnum/)
- [Schematic Validation Rules](https://sagebionetworks.jira.com/wiki/spaces/SCHEM/pages/2645262364/Data+Model+Validation+Rules)
- [NF Metadata Dictionary README](../README.md)

## Questions?

If you have questions about LinkML rules or need help with the migration:

1. Check the [LinkML documentation](https://linkml.io/linkml/schemas/advanced.html)
2. Review existing rules in `modules/Template/Data.yaml` for examples
3. Open an issue in the repository with the `question` label
