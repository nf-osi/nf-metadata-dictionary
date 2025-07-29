# Synonym Injection Automation

## Overview
This update enhances the GitHub workflow to automatically parse synonyms from a CSV file and inject them as `aliases` into the source module YAML files in the `modules/` directory, with intelligent filtering to avoid redundant entries.

## Key Features

### 1. Source-Level Synonym Injection
- **New Script**: `utils/inject_synonyms.py` reads `term_synonyms.csv` and injects synonyms as `aliases` directly into source module YAML files
- **Persistent**: Changes are made to source files in `modules/` directory, ensuring they survive build processes
- **Example Output**:
  ```yaml
  3D electron microscopy:
    description: Three-dimensional (3D) reconstruction of single, transparent objects...
    meaning: http://purl.obolibrary.org/obo/MI_0410
    aliases:
      - 3D-EM
      - electron tomography
  ```

### 2. Improve Case-Only Matches
The script implements sophisticated filtering to avoid redundant aliases:

#### Case-Only Filtering
- Skips synonyms that differ only by capitalization, spacing, or punctuation
- Example: Skips "3-D Imaging" and "3D Imaging" when the term is "3D imaging"

#### Fuzzy Matching
- Uses sequence matching to detect near-duplicates (default threshold: 90% similarity)
- Example: Skips "Three-Dimensional Imaging" as a duplicate of "Three Dimensional Imaging"
- Prevents aliases that are too similar to the original term name

## Timeout and Robustness Improvements

To address timeout issues during synonym extraction, the following improvements have been implemented:

### Performance Optimizations
- **Reduced timeouts**: HTTP requests limited to 15 seconds (down from 30)
- **Per-term timeout**: Individual term processing limited to 30 seconds (down from 60)
- **Batch processing**: Terms processed in batches of 50 for better memory management
- **Reduced parallelism**: Maximum 5 concurrent workers (down from 10) to reduce server load

### Timeout Handling
- **Script timeout**: 55-minute script timeout with graceful shutdown
- **Workflow timeout**: 60-minute timeout with proper error handling
- **Resume capability**: Can resume processing from existing CSV file if interrupted
- **Progress preservation**: Results saved after each batch to prevent data loss

### Error Resilience
- **Graceful degradation**: Script continues even if individual terms fail
- **Partial results**: Always produces usable CSV output, even with timeouts
- **Clear error reporting**: Detailed logging of which terms timeout or fail

## Updated Workflow

The GitHub workflow now includes these enhanced steps:

1. **Extract synonyms** (improved): `python utils/extract_synonyms.py`
   - **Timeout protection**: 60-minute timeout with graceful handling
   - **Resume capability**: Can resume from partial CSV if interrupted
   - **Batch processing**: Processes terms in smaller batches for better reliability
   - **Reduced timeouts**: Individual requests limited to 15 seconds, terms to 30 seconds
2. **Inject synonyms** (new): `python utils/inject_synonyms.py --csv term_synonyms.csv --modules-dir modules`
3. **Create Pull Request**: Automatically creates a PR with the updated CSV and module files for review
4. **Upload artifacts**: CSV file and processing logs available as workflow artifacts

## Review Process

When the workflow runs, it creates a pull request with:
- **Updated CSV**: `term_synonyms.csv` with newly extracted synonyms
- **Modified modules**: Source YAML files with injected aliases
- **Detailed description**: Summary of changes and quality filtering applied
- **Review checklist**: Guide for reviewers to validate the changes

This ensures that all synonym additions are reviewed before being merged into the main branch.

## Script Options

The injection script supports several command-line options:

```bash
python utils/inject_synonyms.py [options]

Options:
  --csv PATH              CSV file with synonyms (default: term_synonyms.csv)
  --yaml PATH             Single YAML file to modify (alternative to --modules-dir)
  --modules-dir PATH      Directory containing module YAML files (default: modules)
  --output PATH           Output file (only works with --yaml option)
  --fuzzy-threshold FLOAT Similarity threshold 0.0-1.0 (default: 0.9)
```

## Benefits

1. **Source-level integration**: Synonyms are injected directly into source module files
2. **Build-process compatibility**: Changes survive the automatic build process that generates `dist/NF.yaml`
3. **Persistent synonyms**: Synonyms become part of the authoritative source metadata
4. **Quality filtering**: Prevents low-quality aliases through intelligent deduplication
5. **Consistent format**: All aliases follow the same YAML structure
6. **Review workflow**: All changes go through PR review process for quality control
7. **Automatic updates**: Workflow can be triggered manually or on releases
8. **Traceable changes**: Git history shows exactly which module files were updated
9. **Artifact preservation**: CSV files and logs are preserved for 30 days

## Example Processing Output

The script provides detailed feedback during processing:
```
=== Synonym Injection Tool ===
CSV file: term_synonyms.csv
Mode: Modules directory - modules
Fuzzy threshold: 0.9
Loaded synonyms for 159 terms from term_synonyms.csv
Found 25 YAML files in modules directory

Processing: modules/Assay/Assay.yaml
  Skipping case-only difference: '3D imaging' vs '3-D Imaging'
  Skipping fuzzy duplicate: 'Three-Dimensional Imaging' (similar to 'Three Dimensional Imaging')
Added 3 aliases to '3D imaging'
...
Processing: modules/Sample/Species.yaml
Added 2 aliases to 'Homo sapiens'
...

=== Summary ===
Processed 25 files
Modified 8 files

Modified files:
  modules/Assay/Assay.yaml
  modules/Sample/Species.yaml
  ...
```

This automation ensures the metadata dictionary maintains high-quality synonym mappings at the source level while reducing manual maintenance overhead.
