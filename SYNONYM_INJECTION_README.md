# Synonym Injection Automation

## Overview
This update enhances the GitHub workflow to automatically parse synonyms from a CSV file and inject them as `aliases` into the `dist/NF.yaml` file, with intelligent filtering to avoid redundant entries.

## Key Features

### 1. Parse & Inject Synonyms
- **New Script**: `utils/inject_synonyms.py` reads `term_synonyms.csv` and injects synonyms as `aliases` into YAML terms
- **Example Output**:
  ```yaml
  3D electron microscopy:
    description: Three-dimensional (3D) reconstruction of single, transparent objects...
    meaning: http://purl.obolibrary.org/obo/MI_0410
    aliases:
      - 3D-EM
      - electron tomog
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
2. **Inject synonyms** (new): `python utils/inject_synonyms.py --csv term_synonyms.csv --yaml dist/NF.yaml`
3. **Validate changes**: Check if YAML was modified and show diff statistics
4. **Commit changes**: Automatically commit and push the updated `dist/NF.yaml` back to the repository
5. **Upload artifacts**: Both CSV and updated YAML are now included in releases and artifacts

## Script Options

The injection script supports several command-line options:

```bash
python utils/inject_synonyms.py [options]

Options:
  --csv PATH              CSV file with synonyms (default: term_synonyms.csv)
  --yaml PATH             YAML file to modify (default: dist/NF.yaml)
  --output PATH           Output file (default: modify input YAML in place)
  --fuzzy-threshold FLOAT Similarity threshold 0.0-1.0 (default: 0.9)
```

## Benefits

1. **Automated synonym integration**: No more manual copying of synonyms
2. **Quality filtering**: Prevents low-quality aliases through intelligent deduplication
3. **Consistent format**: All aliases follow the same YAML structure
4. **Workflow integration**: Seamlessly fits into existing CI/CD pipeline
5. **Automatic updates**: Changes are automatically committed back to the repository
6. **Release assets**: Both CSV and updated YAML are available as release artifacts

## Example Processing Output

The script provides detailed feedback during processing:
```
=== Synonym Injection Tool ===
CSV file: term_synonyms.csv
YAML file: dist/NF.yaml
Fuzzy threshold: 0.9
Loaded synonyms for 159 terms from term_synonyms.csv
  Skipping case-only difference: '3D imaging' vs '3-D Imaging'
  Skipping fuzzy duplicate: 'Three-Dimensional Imaging' (similar to 'Three Dimensional Imaging')
Added 3 aliases to '3D imaging'
...
Completed! Modified 149 terms.
```

This automation ensures the metadata dictionary maintains high-quality synonym mappings while reducing manual maintenance overhead.
