# Revision Summary: LinkML Rules Approach

## Overview

This revision implements the feedback from PR #768 to use **LinkML rules** instead of pre-compiled JSON schemas with enums and mappings for auto-filling metadata fields.

Closed PR: https://github.com/nf-osi/nf-metadata-dictionary/pull/768

## What Was Changed

### Approach Shift

**From (PR #768):**
- Generate separate `enums/*.json` and `mappings/*.json` files
- Create `autofill-config.json` and `lookup-service.json`
- Require custom integration code in schematic/DCA

**To (This Revision):**
- Use LinkML native `rules` feature
- Define auto-fill logic directly in YAML schema
- Single source of truth in `AnimalIndividualTemplate.yaml`

### Files Created

1. **`modules/Template/AnimalIndividualTemplate.yaml`**
   - LinkML schema with 123 rules for animal models
   - Each rule auto-fills 8-10 fields based on `modelSystemName` selection
   - 2,653 lines total
   - Auto-generated from tools database

2. **`scripts/generate_animal_template_with_rules.py`**
   - Automation script to generate the YAML file
   - Reads from `auto-generated/mappings/animal_models_mappings.json`
   - Creates one rule per animal model (123 total)
   - Can be re-run when tools database is updated

3. **`scripts/test_linkml_rules.py`**
   - Validation and testing script
   - Validates YAML structure
   - Shows example rules
   - Simulates lookup behavior

4. **`LINKML_RULES_APPROACH.md`**
   - Comprehensive documentation
   - Explains the approach and rationale
   - Testing instructions
   - Comparison with PR #768

5. **`REVISION_SUMMARY.md`** (this file)
   - Quick summary of changes

## How It Works

### Example Rule

```yaml
rules:
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
        # ... 5 more fields
    description: "Auto-fill info for B6.129(Cg)-Nf1tm1Par/J mouse model"
```

### Statistics

- **Animal models:** 123
- **Rules generated:** 123
- **Slots defined:** 22
- **Auto-fill coverage:**
  - `species`: 100% (all 123 models)
  - `organism`: 100% (all 123 models)
  - `modelSystemType`: 100% (all 123 models)
  - `geneticModification`: 100% (all 123 models)
  - `genotype`: 59.3% (73 models)
  - `backgroundStrain`: 59.3% (73 models)
  - `description`: 58.5% (72 models)
  - `RRID`: 7.3% (9 models)

## Testing & Validation

### ✅ Completed
- YAML structure validation
- Rule syntax validation
- Test lookups for sample models
- Field coverage analysis

### ⏳ Pending (Next Steps)
1. **Install LinkML:** `pip install linkml`
2. **Build merged schema:** `make NF.yaml` (requires `yq`)
3. **Generate JSON schema:**
   ```bash
   python utils/gen-json-schema-class.py --class AnimalIndividualTemplate
   ```
4. **Test with Synapse:**
   - Upload JSON schema to Synapse
   - Test if rules enforce validation
   - Test if rules trigger auto-fill
   - Measure schema loading performance

## Key Questions to Resolve

1. **Does Synapse support LinkML rules?**
   - Do rules work for validation?
   - Do rules trigger auto-fill in forms?
   - Or are they just documentation?

2. **Performance with 123 rules?**
   - Is 2,653-line schema too large?
   - Schema loading time?
   - Form rendering performance?

3. **Scalability concerns?**
   - Works for 123 animal models
   - Would it work for 638 cell lines?
   - What about 1,000+ combined tools?

## Usage

### Generate the YAML (already done)
```bash
python scripts/generate_animal_template_with_rules.py
```

### Validate the YAML
```bash
python scripts/test_linkml_rules.py
```

### Regenerate when tools database updates
```bash
# 1. Fetch latest tools data
python scripts/fetch_synapse_tools.py --use-materialized-view

# 2. Generate mappings
python scripts/generate_tool_schemas_from_view.py

# 3. Regenerate YAML with rules
python scripts/generate_animal_template_with_rules.py
```

## Advantages

✅ **Single source of truth** - All logic in one YAML file
✅ **Native LinkML** - Uses built-in rules feature
✅ **Maintainable** - One script regenerates everything
✅ **Clear structure** - Easy to review and understand
✅ **Automated** - Script generates all 123 rules

## Limitations

⚠️ **Scalability** - May not work for 1,000+ models
⚠️ **File size** - 2,653 lines (manageable but large)
⚠️ **Synapse support** - Unknown if Synapse uses rules
⚠️ **Experimental** - LinkML rules are marked as experimental

## Comparison: Rules vs. Enums/Mappings

| Aspect | Enums/Mappings (PR #768) | LinkML Rules (This) |
|--------|--------------------------|---------------------|
| **Files** | 12+ files | 1 YAML file |
| **Complexity** | High | Low |
| **Integration** | Custom code | Native LinkML |
| **Scalability** | Good (1,000+) | Limited (100s) |
| **Synapse** | Requires DCA mods | Possibly native |
| **Maintenance** | Complex | Simple |

## Next Actions

### Immediate
1. ✅ Create AnimalIndividualTemplate.yaml with rules
2. ✅ Create automation script
3. ✅ Create test/validation script
4. ✅ Document approach

### After Review
1. ⏳ Install dependencies (LinkML, yq)
2. ⏳ Generate JSON schema
3. ⏳ Test with Synapse
4. ⏳ Gather feedback on performance
5. ⏳ Decide if this approach is viable

### If Successful
1. Update build process
2. Add to CI/CD workflow
3. Document for curators
4. Consider extending to other templates

### If Not Viable
1. Return to PR #768 approach
2. Or explore hybrid approaches
3. Or work with Synapse team on native database support

## Files Modified/Created

### New Files
- `modules/Template/AnimalIndividualTemplate.yaml` (2,653 lines)
- `scripts/generate_animal_template_with_rules.py` (213 lines)
- `scripts/test_linkml_rules.py` (178 lines)
- `LINKML_RULES_APPROACH.md` (comprehensive docs)
- `REVISION_SUMMARY.md` (this file)

### Existing Files Used
- `auto-generated/mappings/animal_models_mappings.json` (from PR #768 branch)

### No Files Deleted
- All PR #768 files remain on that branch
- Can easily switch back if needed

## References

- **LinkML Rules Docs:** https://linkml.io/linkml/schemas/advanced.html#rules
- **Original Issue:** https://github.com/nf-osi/2025-sage-hack-ideas/issues/27
- **Previous PR:** https://github.com/nf-osi/nf-metadata-dictionary/pull/768

## Contact

For questions about this implementation:
- Review `LINKML_RULES_APPROACH.md` for detailed explanation
- Run `python scripts/test_linkml_rules.py` to see examples
- Check LinkML documentation for rules syntax
