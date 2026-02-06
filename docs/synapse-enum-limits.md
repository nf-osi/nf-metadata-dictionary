# Synapse Enum Value Limits

## Overview

Synapse has a **limit of 100 values per annotation field enum**. This is a hard API limit that affects how metadata can be annotated in Synapse.

## Current Status

As of 2026-02-05, the NF Metadata Dictionary has **5 enums that exceed this limit**:

| Enum | File | Count | Exceeds By |
|------|------|-------|------------|
| **CellLineModel** | `modules/Sample/CellLineModel.yaml` | 638 | 538 values |
| **Institution** | `modules/Other/Organization.yaml` | 331 | 231 values |
| **AntibodyEnum** | `modules/Experiment/Antibody.yaml` | 175 | 75 values |
| **AnimalModel** | `modules/Sample/AnimalModel.yaml` | 122 | 22 values |
| **GeneticReagentEnum** | `modules/Experiment/GeneticReagent.yaml` | 110 | 10 values |

## Why These Enums Exceed the Limit

These enums represent **comprehensive research tool catalogs** synced from the NF Research Tools Database:

- **CellLineModel**: All NF-related cell lines in the research tools database
- **AnimalModel**: All animal models used in NF research
- **AntibodyEnum**: Comprehensive antibody catalog
- **GeneticReagentEnum**: Full genetic reagent inventory
- **Institution**: All institutions involved in NF research

These are legitimate large vocabularies that serve as **reference catalogs** rather than typical annotation enums.

## Impact

### What Works
✅ Schema validation and documentation
✅ Data model generation (NF.jsonld, dist/NF.yaml)
✅ Local data validation with schematic
✅ Reading/querying existing data

### Potential Issues
⚠️ Creating new Synapse annotations with these fields via API
⚠️ Synapse web UI dropdowns (may be slow or truncated)
⚠️ Schematic manifest validation against Synapse (depending on implementation)

## Solutions & Workarounds

### For Large Research Tool Catalogs

These enums are **intentionally comprehensive** and serve as reference lists. Recommended approaches:

1. **Use Resource IDs Instead** (Preferred)
   ```yaml
   # Instead of large enums, use resource ID fields
   animalModelID:
     description: UUID for animal model from NF Research Tools Database
     range: string
   ```

2. **External Reference Tables**
   - Keep comprehensive lists in dedicated Synapse tables
   - Reference by ID in annotations
   - Query tables when needed

3. **Subset Enums**
   - Create smaller "commonly used" subsets for annotation dropdowns
   - Maintain comprehensive lists separately

### For New Fields

When adding new annotation fields:

1. **Check Current Size**
   ```bash
   python utils/check_enum_sizes.py
   ```

2. **Keep Under 100 Values**
   - If approaching limit, consider restructuring
   - Use free-text for large vocabularies
   - Create hierarchical or grouped enums

3. **Monitor Growth**
   - Watch enums approaching 80 values
   - Plan alternatives before hitting limit

## Automated Checking

The weekly model system sync workflow automatically checks enum sizes:

```yaml
# .github/workflows/weekly-model-system-sync.yml
- name: Check enum sizes (Synapse API limits)
  run: python utils/check_enum_sizes.py --output enum_size_report.md
```

PRs will include warnings when enums exceed or approach the limit.

## Checking Manually

```bash
# Full report in markdown format
python utils/check_enum_sizes.py

# Save report to file
python utils/check_enum_sizes.py --output report.md

# JSON format for parsing
python utils/check_enum_sizes.py --format json

# Brief text summary
python utils/check_enum_sizes.py --format text

# Include safe enums in report
python utils/check_enum_sizes.py --verbose

# Fail if any enum exceeds limit (for CI)
python utils/check_enum_sizes.py --fail-on-exceed
```

## Best Practices

### ✅ DO
- Use resource ID fields for large catalogs (animalModelID, cellLineID, etc.)
- Keep annotation enums focused and manageable (<100 values)
- Use external reference tables for comprehensive lists
- Monitor enum growth with automated checks
- Document when exceeding limit is intentional

### ❌ DON'T
- Add hundreds of values to annotation enums
- Use enums for unbounded vocabularies
- Ignore warnings about approaching limits
- Assume Synapse will support unlimited enum values

## References

- [Synapse Annotations Documentation](https://help.synapse.org/docs/Annotations-and-Queries.2011070649.html)
- [Weekly Model System Sync Workflow](../.github/workflows/weekly-model-system-sync.yml)
- [Enum Size Checker Script](../utils/check_enum_sizes.py)
- [NF Research Tools Schema](https://github.com/nf-osi/nf-research-tools-schema)

## Related Issues

- Consider splitting large enums into subsets
- Evaluate alternative annotation strategies for large catalogs
- Coordinate with Synapse team on limit implications

---

*Last Updated: 2026-02-05*
*Checked by: Automated enum size checker*
