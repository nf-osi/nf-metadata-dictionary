# Annotation Review Workflow

## Overview

The annotation review workflow automatically analyzes file annotations from Synapse to identify free-text values that could be standardized as enum values in the metadata dictionary. This workflow helps maintain and improve the schema by capturing real-world usage patterns.

**Integration:** As of 2026-02-03, the annotation review functionality is integrated into the weekly model system sync workflow (`.github/workflows/weekly-model-system-sync.yml`) rather than running as a separate workflow. Both operations run sequentially every Monday at 9:00 AM UTC.

**Tool Field Separation:** As of 2026-02-05, tool-related annotation fields (e.g., animalModelID, cellLineID, antibodyID, tumorType, tissue, organ, species) are reviewed in a separate workflow in the [nf-research-tools-schema](https://github.com/nf-osi/nf-research-tools-schema) repository. This improves efficiency by co-locating tool annotation review with the existing tool database sync workflows. See [Tool-Related Fields](#tool-related-fields) section below for details.

## Related Issues

- **Issue #804:** Enable custom values for platform and other fields
- **Issue #805:** Automated curation of free-text entries

## Features

### 1. Custom Enum Values

The `platform` field (and potentially others) now accepts custom free-text values in addition to predefined enum values.

**Implementation:**
```yaml
platform:
  description: A sequencing platform, microscope, spectroscope/plate reader, or other platform for collecting data.
    Select from the recommended list when available, or enter a custom platform name
    (e.g., new microscope models like Zeiss Axio series).
  any_of:
    - range: SequencingPlatformEnum
    - range: ArrayPlatformEnum
    - range: MicroscopyImagingPlatformEnum
    - range: MRIPlatformEnum
    - range: MassSpectrometryPlatformEnum
    - range: PlateReaderPlatformEnum
    - range: FlowCytometryPlatformEnum
    - range: ImagingSystemPlatformEnum
    - range: OtherPlatformEnum
    - range: string  # ← Allows custom values
```

**Benefits:**
- Users can enter new technology/instrument names immediately
- No need to wait for schema updates for emerging technologies
- Custom values are tracked for potential standardization

### 2. Automated Annotation Review

**Script:** `utils/review_annotations.py`

This script:
1. Queries Synapse materialized view (syn52702673)
2. Extracts all file annotations (excluding tool-related fields - see below)
3. Compares annotation values against schema enum definitions (including synonyms/aliases)
4. Identifies free-text values that don't match any enum
5. **Automatically adds new values to the appropriate YAML enum files** (frequency ≥ 2)
6. Generates summary files documenting the additions
7. Suggests portal search filters based on field diversity

**Automatic Editing Logic:**
- Values are added to the correct enum based on field-to-enum mapping
- For fields with multiple enums (e.g., `platform`), prefers non-"Other" enums
- Only adds values that appear at least 2 times (configurable threshold)
- Skips values that already exist in the schema
- Adds basic metadata: `description: "Added from annotation review (used N times)"`

**Usage:**

```bash
# Basic usage - automatically edits YAML files
export SYNAPSE_AUTH_TOKEN=your_token
python utils/review_annotations.py

# Test with limited records
python utils/review_annotations.py --limit 1000

# Dry run - preview without modifying anything
python utils/review_annotations.py --dry-run

# Only generate suggestions, don't edit YAML files
python utils/review_annotations.py --no-edit

# Custom output files
python utils/review_annotations.py \
  --output suggestions.json \
  --markdown summary.md
```

**Output:**

1. **Modified YAML files** - Enum values automatically added:
   - `modules/Assay/Platform.yaml` (if platform values added)
   - `modules/Sample/Species.yaml` (if species values added)
   - etc.

2. **`annotation_suggestions.json`** - Structured data with:
   - Field names → suggested values → frequency counts
   - Portal filter suggestions
   - Files modified and count of values added

3. **`annotation_suggestions.md`** - Human-readable summary:
   - List of files modified
   - Details about values added
   - Portal filter suggestions

**Example Output:**

```markdown
# Annotation Review - Schema Updates from Synapse Annotations

## Files Modified

**2 enum file(s) updated** with values from annotations:

- `modules/Assay/Platform.yaml` - Added 3 value(s)
- `modules/Assay/Assay.yaml` - Added 2 value(s)

## Suggested Enum Value Additions

### Field: `platform`

- `Zeiss Axio Imager.Z2` (used 15 times) ✅ Added to MicroscopyImagingPlatformEnum
- `Zeiss LSM 880` (used 12 times) ✅ Added to MicroscopyImagingPlatformEnum
- `Nikon A1R Confocal` (used 8 times) ✅ Added to MicroscopyImagingPlatformEnum

### Field: `assay`

- `spatial transcriptomics` (used 23 times) ✅ Added to ImagingAssayEnum
- `CyTOF mass cytometry` (used 6 times) ✅ Added to CellBasedAssayEnum

## Suggested Portal Search Filters

- `studyName` (47 unique values)
- `tissue` (23 unique values)
- `cellType` (18 unique values)
```

**YAML Changes Example:**

```yaml
# modules/Assay/Platform.yaml
MicroscopyImagingPlatformEnum:
  permissible_values:
    # ... existing values ...
    Zeiss Axio Imager.Z2:
      description: Added from annotation review (used 15 times)
    Zeiss LSM 880:
      description: Added from annotation review (used 12 times)
```

### 3. Integrated Workflow

**Workflow:** `.github/workflows/weekly-model-system-sync.yml`

**Schedule:** Runs weekly on Mondays at 9:00 AM UTC

**Workflow Structure:**
The workflow runs two operations sequentially and creates a **single combined PR**:
1. **Model System Sync** - Updates enums from Synapse tables
2. **Annotation Review** - Analyzes annotations and suggests additions

Both operations contribute to the same PR if either has updates. This keeps all weekly maintenance in one place for easier review.

**Workflow Steps for Annotation Review:**
1. Query Synapse materialized view for annotations
2. Run `review_annotations.py` analysis script
3. Check for new suggestions
4. Create a branch with suggestion files
5. Open a pull request with findings

**Manual Triggering:**

```bash
# Via GitHub CLI - run both operations
gh workflow run weekly-model-system-sync.yml

# Run annotation review only (skip model sync)
gh workflow run weekly-model-system-sync.yml \
  -f skip_model_sync=true \
  -f annotation_limit=1000

# Run model sync only (skip annotation review)
gh workflow run weekly-model-system-sync.yml \
  -f skip_annotation_review=true
```

**Via GitHub UI:**
1. Go to Actions tab
2. Select "Weekly Model System Sync and Annotation Review"
3. Click "Run workflow"
4. Set parameters (optional):
   - `annotation_limit`: Number of records to query (for testing)
   - `skip_model_sync`: Skip model system sync (annotations only)
   - `skip_annotation_review`: Skip annotation review (model sync only)

## How It Works

### Schema Loading

The script loads all enum definitions from YAML files in `modules/`:

```python
# Loads all enums with their permissible values and aliases
enums = load_schema_enums()
# Example: enums['SequencingPlatformEnum']['values'] = {'Illumina NovaSeq 6000', ...}

# Maps slot names to enum types
slot_enum_map = load_slot_to_enum_mapping()
# Example: slot_enum_map['platform'] = ['SequencingPlatformEnum', 'ArrayPlatformEnum', ...]
```

### Annotation Analysis

For each annotation record:
1. Extract field name and value
2. Check if field maps to an enum type
3. Check if value exists in enum (including aliases)
4. If not, track as a suggestion with frequency count

```python
# Pseudo-code
for record in synapse_annotations:
    for field, value in record.items():
        if field in slot_enum_map:
            enum_types = slot_enum_map[field]
            if value not in any_enum_values(enum_types):
                suggestions[field][value] += 1
```

### Frequency Thresholds

- **Enum suggestions:** Minimum 2 occurrences (configurable via `MIN_FREQUENCY`)
- **Filter suggestions:** Minimum 5 unique values (configurable via `MIN_FILTER_FREQUENCY`)

These thresholds prevent one-off typos from being suggested while capturing meaningful patterns.

## Reviewing and Accepting Suggestions

### When a PR is Created

1. **Review the suggestions:**
   - Check `annotation_suggestions.md` for summary
   - Review `annotation_suggestions.json` for full details

2. **Evaluate each suggestion:**
   - Is this a legitimate new term or a typo?
   - Should it be added to existing enum?
   - Should it map to an existing value (as alias)?
   - Does it need a new enum category?

3. **Make schema updates:**
   ```yaml
   # Example: Adding to Platform.yaml
   MicroscopyImagingPlatformEnum:
     permissible_values:
       # ... existing values ...
       Zeiss Axio Imager.Z2:
         description: Automated microscope system for fluorescence imaging
         source: https://www.zeiss.com/microscopy/en/products/light-microscopes/axio-imager-2.html
   ```

4. **Update portal filters (if suggested):**
   - Coordinate with portal development team
   - Update materialized view faceting configuration
   - Test filter functionality

5. **Merge the PR** or create a follow-up PR with actual schema changes

### Handling False Positives

Common cases:
- **Typos:** "Illumina NovaSeq600" vs "Illumina NovaSeq 6000"
- **Variations:** "RNAseq" vs "RNA-seq" vs "RNA sequencing"
- **Deprecated terms:** Old platform names

**Solutions:**
1. Add aliases for minor variations
2. Document preferred spellings
3. Update data at source if possible
4. Use synonym workflow to capture variations

## Integration with Other Workflows

The annotation review functionality is now part of the weekly model system sync workflow, which also integrates with other workflows:

| Workflow | Purpose | Source | Frequency |
|----------|---------|--------|-----------|
| **weekly-model-system-sync** | Sync model systems + review annotations | Synapse tables & views | Weekly (Mon 9am) |
| **synonyms** | Extract ontology synonyms → add as aliases | External ontologies (OBO) | On release |
| **rebuild-artifacts-on-main** | Rebuild schema artifacts | Main branch changes | On push to main |

**Workflow Sequence:**
1. **Model System Sync** runs first → updates enums from truth tables
2. **Annotation Review** runs second → suggests additions based on usage
3. **Combined PR** created if either operation has updates

**Benefits of Combined PR:**
- Single review for all weekly maintenance
- All Synapse-related updates in one place
- Easier to track weekly changes
- Fewer PRs to manage

**Together they provide:**
- Truth table synchronization (model system sync)
- Ontology-driven standardization (synonyms)
- User-driven vocabulary expansion (annotation review)

## Tool-Related Fields

### Separation of Concerns

As of 2026-02-06, the `individualID` annotation field is reviewed in a **separate workflow** in the [nf-research-tools-schema](https://github.com/nf-osi/nf-research-tools-schema) repository.

**Field reviewed in nf-research-tools-schema:**
- `individualID` - Individual/specimen identifiers are analyzed from file annotations (syn52702673) and compared against tools in the NF Research Tools Central database (syn51730943). New individualID values are suggested as cell lines (resourceName) or synonyms based on fuzzy matching.

**Why separate?**
1. **Efficiency**: Individual ID annotations are reviewed alongside tool database syncs
2. **Organization**: Tool schema updates (including cell lines identified via individualID) are managed in the tools repository
3. **No duplication**: Avoids reviewing the same field in two places
4. **Clear separation**: Metadata dictionary focuses on file/dataset metadata fields, while tools schema handles resource identifiers

**All other annotation fields** (including tool-related fields like `animalModelID`, `cellLineID`, `antibodyID`, `geneticReagentID`, `tumorType`, `tissue`, `organ`, `species`, etc.) are reviewed in this metadata dictionary workflow, provided they have enums that allow custom values.

**Workflow Coordination:**
- **Metadata Dictionary** (Monday 9:00 AM UTC): Reviews non-individualID annotation fields
- **NF Research Tools Schema** (PR-triggered chain starting Sunday 9:00 AM UTC): Reviews individualID annotations as part of the PubMed mining → tool annotation review → coverage check workflow sequence

See [nf-research-tools-schema workflows](https://github.com/nf-osi/nf-research-tools-schema/blob/main/.github/workflows/README.md) for details on the tool annotation review workflow.

## Configuration

### Script Configuration

Edit `utils/review_annotations.py`:

```python
# Synapse materialized view ID
MATERIALIZED_VIEW_ID = "syn52702673"

# Fields that allow custom values
CUSTOM_VALUE_FIELDS = ['platform']

# Tool-related fields (excluded from this review)
TOOL_RELATED_FIELDS = {
    'animalModelID', 'cellLineID', 'antibodyID', 'geneticReagentID',
    'tumorType', 'tissue', 'organ', 'species',
    'cellLineManifestation', 'animalModelOfManifestation',
    # ... see script for complete list
}

# Minimum frequency for suggestions
MIN_FREQUENCY = 2

# Minimum diversity for filter suggestions
MIN_FILTER_FREQUENCY = 5
```

### Workflow Configuration

Edit `.github/workflows/weekly-model-system-sync.yml`:

```yaml
# Schedule (cron format)
schedule:
  - cron: '0 9 * * 1'  # Monday 9:00 AM UTC

# Environment variables
env:
  SYNAPSE_TABLE_ID: syn26450069
  SYNAPSE_TOOLS_TABLE_ID: syn51730943
  SYNAPSE_MATERIALIZED_VIEW: syn52702673

# Required secret
secrets:
  DATA_MODEL_SERVICE: # Synapse auth token
```

## Troubleshooting

### Issue: Script fails with authentication error

**Solution:**
```bash
# Ensure token is set
export SYNAPSE_AUTH_TOKEN=your_token

# Verify token is valid
synapse login -p $SYNAPSE_AUTH_TOKEN
```

### Issue: No suggestions generated

**Possible causes:**
1. All annotations match schema (good!)
2. Frequency threshold too high
3. Slot-to-enum mapping incomplete

**Debug:**
```bash
# Run with lower threshold
python utils/review_annotations.py --dry-run --limit 1000

# Check slot mappings
python -c "
from utils.review_annotations import load_slot_to_enum_mapping
mapping = load_slot_to_enum_mapping()
print(f'Mapped {len(mapping)} slots')
print(mapping)
"
```

### Issue: Too many false positive suggestions

**Solutions:**
1. Increase `MIN_FREQUENCY` threshold
2. Add common variations as aliases in schema
3. Improve data quality at source
4. Filter specific fields in script

## Synapse Enum Limits

⚠️ **Important:** Synapse has a limit of **100 values per annotation field enum**.

The weekly workflow automatically checks enum sizes and includes warnings in PRs when enums exceed or approach this limit. See [synapse-enum-limits.md](./synapse-enum-limits.md) for details.

**When reviewing annotation suggestions:**
- Check if adding values would exceed 100-value limit
- Consider alternative approaches for large vocabularies (resource IDs, external tables)
- Monitor enums approaching 80+ values

## Best Practices

### 1. Regular Review Cadence
- Review PRs weekly when they're generated
- Don't let suggestions accumulate
- Merge or close PRs promptly with notes
- Monitor enum sizes to stay within Synapse limits

### 2. Documentation
- Document rationale for accepting/rejecting suggestions
- Add comments to enum values explaining their source
- Update this guide as patterns emerge

### 3. Communication
- Share suggestions with data contributors
- Provide feedback on common issues
- Celebrate schema improvements

### 4. Quality Control
- Verify sources for new terms
- Add ontology mappings where possible
- Maintain consistent naming conventions

## Future Enhancements

See [`future-enhancements.md`](./future-enhancements.md) for planned improvements:

- GEO metadata extraction
- Clinical data model alignment
- Advanced filtering
- Validation levels
- ML-based term matching

## Reference

### Files
- `utils/review_annotations.py` - Main analysis script
- `.github/workflows/weekly-model-system-sync.yml` - Integrated workflow (contains both model sync and annotation review)
- `modules/props.yaml` - Slot definitions (line 1045: platform field)
- `modules/Assay/Platform.yaml` - Platform enum definitions

### Documentation
- [Issue #804](https://github.com/nf-osi/nf-metadata-dictionary/issues/804) - Enable custom values
- [Issue #805](https://github.com/nf-osi/nf-metadata-dictionary/issues/805) - Curation workflow
- [Reference PR](https://github.com/nf-osi/nf-research-tools-schema/pull/99) - Similar workflow example

### Related Workflows
- `weekly-model-system-sync.yml` - **Main workflow** containing both model sync and annotation review
- `synonyms.yml` - Ontology synonym extraction
- `rebuild-artifacts-on-main.yml` - Schema artifact generation

---

*Last Updated: 2026-02-03*
