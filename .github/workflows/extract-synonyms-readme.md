# Synonym Automation Workflows

## Overview
This update provides two separate GitHub workflows for managing synonym data in the NF metadata dictionary:

1. **Synonym Extraction** (`extract-synonyms.yml`): Long-running process to extract synonyms from ontology sources
2. **Synonym Injection** (`inject-synonyms.yml`): Fast, testable process to inject synonyms into source module YAML files

This separation allows for better reliability, testing, and workflow management.

## Workflows

### 1. Synonym Extraction Workflow (`extract-synonyms.yml`)

**Purpose**: Extract synonyms from external ontology sources and create/update `term_synonyms.csv`

**Triggers**:
- Manual execution (`workflow_dispatch`)
- Release publication (automatic)

**Features**:
- **Long-running**: Can take 60+ minutes to process all terms
- **Timeout handling**: 65-minute job timeout with graceful degradation
- **Resume capability**: Can continue from existing CSV file if interrupted
- **Batch processing**: Processes terms in batches of 50 for better reliability
- **Artifact preservation**: Always uploads CSV results, even on timeout

**Usage**:
```bash
**Usage**:
```bash
# Manual trigger with default CSV
gh workflow run inject-synonyms.yml

# Manual trigger with test mode (dry-run)
gh workflow run inject-synonyms.yml -f test_mode=true

# Manual trigger with custom CSV file
gh workflow run inject-synonyms.yml -f csv_file=custom_synonyms.csv
```

## Key Features

### 1. Source-Level Synonym Injection
```

### 2. Synonym Injection Workflow (`inject-synonyms.yml`)

**Purpose**: Inject synonyms from CSV file into source module YAML files and create PR for review

**Triggers**:
- Manual execution only (`workflow_dispatch`)

**Features**:
- **Fast execution**: Typically completes in under 5 minutes  
- **Test mode**: Dry-run capability to preview changes without modifications
- **Configurable CSV source**: Can specify custom CSV file path
- **Automatic PR creation**: Creates pull requests for review when changes are detected
- **Quality filtering**: Intelligent deduplication and fuzzy matching
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

## Updated Workflows

### Synonym Extraction Workflow Steps

1. **Setup Environment**: Install Python dependencies (`pyyaml`, `requests`, `rdflib`, `tqdm`)
2. **Extract synonyms**: `python utils/extract_synonyms.py`
   - **Timeout protection**: 60-minute timeout with graceful handling
   - **Resume capability**: Can resume from partial CSV if interrupted
   - **Batch processing**: Processes terms in smaller batches for better reliability
   - **Reduced timeouts**: Individual requests limited to 15 seconds, terms to 30 seconds
3. **Upload artifacts**: CSV file available as workflow artifact (30-day retention)
4. **Workflow summary**: Detailed report of extraction progress and results

### Synonym Injection Workflow Steps

1. **Setup Environment**: Install Python dependencies (`pyyaml`)
2. **Verify CSV**: Check that the specified CSV file exists and has content
3. **Test Mode** (if enabled): `python utils/inject_synonyms.py --dry-run`
   - Shows what changes would be made without modifying files
   - Useful for validation and testing
4. **Inject synonyms**: `python utils/inject_synonyms.py --csv term_synonyms.csv --modules-dir modules`
5. **Check changes**: Detect if any module files were modified
6. **Create Pull Request**: Automatically creates a PR with updated module files for review
7. **Workflow summary**: Report of injection results and PR creation

## Review Process

### Extraction Workflow
The extraction workflow produces artifacts but does not create pull requests:
- **CSV artifact**: `term_synonyms.csv` available for download (30-day retention)
- **Manual review**: Users can download and inspect the extracted synonyms
- **Next step**: Use the injection workflow to apply the synonyms

### Injection Workflow
When the injection workflow runs with actual changes, it creates a pull request with:
- **Modified modules**: Source YAML files with injected aliases
- **Detailed description**: Summary of changes and quality filtering applied
- **Review checklist**: Guide for reviewers to validate the changes
- **Change summary**: List of modified files and statistics

This ensures that all synonym additions are reviewed before being merged into the main branch.

## Script Options

### Extraction Script (`utils/extract_synonyms.py`)

```bash
python utils/extract_synonyms.py [options]

Options:
  --max-terms INT         Maximum number of terms to process (for testing)
  --batch-size INT        Number of terms per batch (default: 50)
  --timeout INT           Overall script timeout in seconds (default: 3300)
  --output PATH           Output CSV file path (default: term_synonyms.csv)
```

### Injection Script (`utils/inject_synonyms.py`)

```bash
python utils/inject_synonyms.py [options]

Options:
  --csv PATH              CSV file with synonyms (default: term_synonyms.csv)
  --yaml PATH             Single YAML file to modify (alternative to --modules-dir)
  --modules-dir PATH      Directory containing module YAML files (default: modules)
  --output PATH           Output file (only works with --yaml option)
  --fuzzy-threshold FLOAT Similarity threshold 0.0-1.0 (default: 0.9)
  --dry-run               Show what would be changed without making modifications
```

## Benefits

### Separation of Concerns
1. **Extraction isolation**: Long-running extraction doesn't block injection testing
2. **Independent testing**: Can test injection logic without waiting for extraction
3. **Workflow reliability**: Injection failures don't affect extraction results
4. **Resource optimization**: Shorter jobs use fewer GitHub Actions minutes

### Development and Testing
1. **Fast iteration**: Test injection changes in minutes, not hours
2. **Dry-run capability**: Preview changes before applying them
3. **Configurable inputs**: Test with different CSV files or parameters
4. **Clear separation**: Easier to debug and maintain individual workflows

### Production Benefits
1. **Source-level integration**: Synonyms are injected directly into source module files
2. **Build-process compatibility**: Changes survive the automatic build process that generates `dist/NF.yaml`
3. **Persistent synonyms**: Synonyms become part of the authoritative source metadata
4. **Quality filtering**: Prevents low-quality aliases through intelligent deduplication
5. **Consistent format**: All aliases follow the same YAML structure
6. **Review workflow**: All changes go through PR review process for quality control
7. **Automatic updates**: Workflows can be triggered manually or on releases
8. **Traceable changes**: Git history shows exactly which module files were updated
9. **Artifact preservation**: CSV files and logs are preserved for 30 days

## Example Processing Output

### Extraction Script Output
```
Reading YAML file...
Loaded 42 prefixes
Found 1486 terms to process
Found existing CSV file, checking for already processed terms...
Found 162 already processed terms
Processing 1311 remaining terms...

Processing batch 1/27 (50 terms)
Batch 1: 100%|██████████| 50/50 [02:30<00:00,  3.05s/it]

Processing batch 2/27 (50 terms)
Batch 2: 100%|██████████| 50/50 [01:45<00:00,  2.10s/it]
...

Synonym extraction completed!
Total terms processed: 1311
Total synonyms found: 2847
CSV file saved: term_synonyms.csv
```

### Injection Script Output
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

### Injection Script Output (Dry-Run Mode)
```
=== Synonym Injection Tool ===
CSV file: term_synonyms.csv
Mode: DRY-RUN (no files will be modified)
Fuzzy threshold: 0.9
Loaded synonyms for 159 terms from term_synonyms.csv
Found 25 YAML files in modules directory

Processing: modules/Assay/Assay.yaml
  [DRY-RUN] Would add 3 aliases to '3D imaging'
  [DRY-RUN] Would add 1 alias to 'proteomics'
...

[DRY-RUN] Would write changes to: modules/Assay/Assay.yaml
[DRY-RUN] Would modify 8 terms

=== Summary ===
Processed 25 files
Would modify 8 files
```

This automation ensures the metadata dictionary maintains high-quality synonym mappings at the source level while providing flexible, testable workflows for both extraction and injection processes.

## Workflow Recommendations

### For Development/Testing
1. **Test injection first**: Use `inject-synonyms.yml` with `test_mode=true` to validate changes
2. **Use existing CSV**: Test with the current `term_synonyms.csv` before running extraction
3. **Small iterations**: Test injection changes quickly without waiting for extraction

### For Production Updates  
1. **Run extraction**: Execute `extract-synonyms.yml` to get latest synonyms (can be done periodically)
2. **Review CSV**: Download and review the extraction artifacts
3. **Run injection**: Execute `inject-synonyms.yml` to apply synonyms and create PR
4. **Review PR**: Validate module file changes before merging

### For Maintenance
- **Monitor timeouts**: Check extraction workflow logs for timeout patterns
- **Update CSV manually**: Can manually edit `term_synonyms.csv` and run injection
- **Adjust thresholds**: Modify fuzzy matching thresholds based on quality feedback
