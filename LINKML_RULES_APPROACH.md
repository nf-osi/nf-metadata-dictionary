# LinkML Rules Approach for Auto-Fill

This document describes the revised approach for implementing auto-fill functionality using LinkML rules instead of pre-compiled JSON schemas with enums and mappings.

## Overview

Instead of generating separate enum and mapping files that need to be manually integrated, this approach uses **LinkML rules** to define auto-fill behavior directly in the schema definition. When a user selects a `modelSystemName`, LinkML rules automatically enforce (or suggest) values for related fields like `species`, `genotype`, `backgroundStrain`, etc.

## What Changed from PR #768

### Previous Approach (PR #768)
- Generated separate `enums/*.json` and `mappings/*.json` files
- Required `autofill-config.json` and `lookup-service.json`
- JSON schemas contained enum lists but no auto-fill logic
- Schematic/DCA needed custom integration code to handle auto-fill

### New Approach (LinkML Rules)
- Uses LinkML's native `rules` feature with `preconditions` and `postconditions`
- All logic is contained in the LinkML YAML schema
- JSON schema generated from YAML includes the rule constraints
- Potentially works with Synapse validation natively (needs testing)

## Implementation

### 1. AnimalIndividualTemplate.yaml

Created at `modules/Template/AnimalIndividualTemplate.yaml` with structure:

```yaml
classes:
  AnimalIndividualTemplate:
    description: Template for non-human individual-level data with auto-fill rules...
    slots:
      - specimenID
      - individualID
      - species
      - genotype
      - backgroundStrain
      - RRID
      - modelSystemName
      # ... other slots
    rules:
      # Example rule for B6.129(Cg)-Nf1tm1Par/J
      - preconditions:
          slot_conditions:
            modelSystemName:
              any_of:
                - equals_string: "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
        postconditions:
          slot_conditions:
            species:
              equals_string: "Mus musculus"
            genotype:
              equals_string: "C57BL/6"
            backgroundStrain:
              equals_string: "C57BL/6"
            RRID:
              equals_string: "rrid:IMSR_JAX:017640"
            # ... other auto-filled fields
        description: "Auto-fill info for B6.129(Cg)-Nf1tm1Par/J mouse model"

      # ... 122 more rules (one per model)
```

### 2. Automation Script

Created `scripts/generate_animal_template_with_rules.py` to automatically generate the YAML file with all 123 animal model rules from the tools database.

**Usage:**
```bash
python scripts/generate_animal_template_with_rules.py
```

**What it does:**
1. Reads `auto-generated/mappings/animal_models_mappings.json`
2. Creates a LinkML rule for each of the 123 animal models
3. Writes `modules/Template/AnimalIndividualTemplate.yaml` with all rules
4. Each rule auto-fills 8-10 fields based on the selected model

### 3. Statistics

- **Total animal models:** 123
- **Total LinkML rules:** 123
- **Auto-filled fields per model:** 8-10 fields (species, genotype, backgroundStrain, RRID, organism, modelSystemType, geneticModification, manifestation, institution, description)
- **File size:** 2,653 lines

## Testing the Approach

### Step 1: Install LinkML

```bash
pip install linkml
```

### Step 2: Build Merged Schema

```bash
make NF.yaml
```

This creates `dist/NF.yaml` which merges all modules including the new AnimalIndividualTemplate.

### Step 3: Generate JSON Schema

```bash
python utils/gen-json-schema-class.py --class AnimalIndividualTemplate --skip-validation
```

This generates `registered-json-schemas/AnimalIndividualTemplate.json` from the LinkML YAML.

### Step 4: Test with Synapse

Test if Synapse recognizes and enforces the rules:

1. Upload the JSON schema to Synapse
2. Create a test submission form
3. Select a `modelSystemName` value
4. Verify if Synapse:
   - Automatically fills in the related fields, OR
   - Validates that the related fields match the expected values

## How LinkML Rules Work

From the [LinkML documentation](https://linkml.io/linkml/schemas/advanced.html#rules):

> Any class can have a rules block, consisting of (optional) preconditions and postconditions. This can express basic if-then logic.

**Example from docs:**
```yaml
rules:
  - preconditions:
      slot_conditions:
        country:
          any_of:
            - equals_string: USA
    postconditions:
      slot_conditions:
        postal_code:
          pattern: "[0-9]{5}(-[0-9]{4})?"
```

**Our implementation:**
- **Precondition:** `modelSystemName` equals a specific animal model name
- **Postcondition:** Related fields (species, genotype, etc.) must equal specific values

## Advantages

### 1. Single Source of Truth
- All auto-fill logic lives in the LinkML schema
- No need for separate mapping files or configuration

### 2. Native LinkML Feature
- Uses LinkML's built-in rules system
- JSON schema generation includes the rules
- Potentially works with Synapse validation natively

### 3. Maintainable
- Run one script to regenerate from tools database
- Clear YAML structure is easy to review
- Auto-generated file with clear provenance

### 4. Scalable (with caveats)
- Can handle 123 animal models ✅
- File is 2,653 lines (manageable for this use case)
- May have performance issues with 1000+ models

## Potential Issues to Test

### 1. Synapse Compatibility
**Question:** Does Synapse's JSON schema validator understand and enforce LinkML rules?

**Testing needed:**
- Does Synapse auto-fill fields when a model is selected?
- Does Synapse validate that filled fields match the rules?
- Or do rules only work as documentation?

### 2. Schema Loading Performance
**Question:** Will Synapse have issues loading a 2,653-line schema with 123 rules?

**From PR feedback:**
> "...which would not be scalable in the long term or for some other templates, but it's worth experimenting with until we have a better (real) solution where Synapse could reference databases more dynamically -- basically you are giving Synapse the animal models part of the database as a large schema file, which could potentially have schema loading issues"

**Testing needed:**
- Load time in Synapse
- Form rendering performance
- Validation performance

### 3. Rule Semantics
**Question:** Are rules meant for validation or for auto-population?

**From LinkML docs:** Rules define postconditions that "must hold" when preconditions are met - this suggests **validation** rather than **auto-fill**.

**Implications:**
- Rules might **validate** that if you select model X, species must be Y
- Rules might **not** automatically populate species when you select model X
- Need to test actual behavior

## Next Steps

### Immediate
1. ✅ Create AnimalIndividualTemplate.yaml with LinkML rules
2. ✅ Create automation script
3. ⏳ Install LinkML and generate JSON schema (requires `yq` or alternative)
4. ⏳ Test JSON schema with Synapse

### If Synapse Test Succeeds
1. Integrate into main schema build process
2. Update GitHub Actions workflow to regenerate on schedule
3. Document for data curators
4. Consider extending to other templates (cell lines, antibodies, etc.)

### If Synapse Test Fails
1. Investigate Synapse's support for LinkML rules
2. Consider alternative approaches:
   - Custom Synapse annotations
   - Client-side auto-fill logic in DCA
   - Hybrid approach with enums + custom logic
3. Engage with Synapse team about rule support

## Files Created/Modified

### New Files
- `modules/Template/AnimalIndividualTemplate.yaml` - LinkML schema with 123 rules
- `scripts/generate_animal_template_with_rules.py` - Automation script
- `LINKML_RULES_APPROACH.md` - This documentation

### Dependencies
- `auto-generated/mappings/animal_models_mappings.json` - Source data (from PR #768 work)

## Comparison: This Approach vs. PR #768

| Aspect | PR #768 (Enums/Mappings) | This Approach (LinkML Rules) |
|--------|--------------------------|------------------------------|
| **Files generated** | 12+ files (enums, mappings, configs) | 1 file (YAML schema) |
| **Integration complexity** | High (custom code needed) | Low (native LinkML) |
| **Synapse compatibility** | Requires DCA customization | Potentially native (needs testing) |
| **Scalability** | Good (1000+ models) | Limited (123 models OK, 1000+ may be slow) |
| **Maintainability** | Complex (many files to sync) | Simple (one YAML file) |
| **Auto-fill mechanism** | Client-side (DCA/schematic) | Server-side validation (possibly) |

## Questions for Team

1. **Does Synapse support LinkML rules in JSON schemas?**
   - Can we test this with a sample schema?

2. **What's the acceptable schema size limit for Synapse?**
   - Is 2,653 lines / 123 rules too large?

3. **Should rules enforce validation or trigger auto-fill?**
   - Or both?

4. **Is this approach acceptable as a prototype?**
   - Even if not scalable to 1000+ models?

## References

- [LinkML Rules Documentation](https://linkml.io/linkml/schemas/advanced.html#rules)
- Original Issue: https://github.com/nf-osi/2025-sage-hack-ideas/issues/27
- Previous PR: https://github.com/nf-osi/nf-metadata-dictionary/pull/768
