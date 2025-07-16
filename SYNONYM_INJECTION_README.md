# Synonym Injection Automation

## Overview
This update enhances the GitHub workflow to automatically parse synonyms from a CSV file and inject them as `aliases` into the `dist/NF.yaml` file, with intelligent filtering to avoid redundant entries. **Updated to support abbreviated URIs** (e.g., `NCIT:C18485`) instead of full URLs.

## Key Features

### 1. Parse & Inject Synonyms
- **Updated Script**: `utils/extract_synonyms.py` now supports abbreviated ontology URIs and converts them to full URLs for API calls
- **New Script**: `utils/inject_synonyms.py` reads `term_synonyms.csv` and injects synonyms as `aliases` into YAML terms
- **Example Output**:
  ```yaml
  3D electron microscopy:
    description: Three-dimensional (3D) reconstruction of single, transparent objects...
    meaning: MI:0410  # Now uses abbreviated URI format
    aliases:
      - 3D-EM
      - electron tomog
  ```

### 2. Abbreviated URI Support
The scripts now automatically handle the new abbreviated URI format used in `dist/NF.yaml`:

#### Supported Prefixes
- **NCIT**: National Cancer Institute Thesaurus (e.g., `NCIT:C18485`)
- **EFO**: Experimental Factor Ontology (e.g., `EFO:0009326`)
- **OBI**: Ontology for Biomedical Investigations (e.g., `OBI:0002039`)
- **GO**: Gene Ontology (e.g., `GO:0008150`)
- **MONDO**: Monarch Disease Ontology (e.g., `MONDO:0000001`)
- **MI**: Molecular Interactions Ontology (e.g., `MI:0410`)
- **BAO**: BioAssay Ontology (e.g., `BAO:0000453`)
- **And many more** (CHMO, MAXO, ERO, VT, UO, CL, UBERON, BTO, etc.)

#### URI Expansion
The extraction script automatically converts abbreviated URIs to full URLs:
- `NCIT:C18485` → `http://purl.obolibrary.org/obo/NCIT_C18485`
- `EFO:0009326` → `http://www.ebi.ac.uk/efo/EFO_0009326`
- `OBI:0002039` → `http://purl.obolibrary.org/obo/OBI_0002039`

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

The GitHub workflow now includes these enhanced steps for abbreviated URI support:

1. **Verify YAML format**: Check for abbreviated URIs vs. full URLs in the current `dist/NF.yaml`
2. **Extract synonyms** (updated): `python utils/extract_synonyms.py`
   - **Abbreviated URI support**: Automatically converts `NCIT:C18485` to full URLs for API calls
   - **Timeout protection**: 65-minute timeout with graceful handling
   - **Resume capability**: Can resume from partial CSV if interrupted
   - **Batch processing**: Processes terms in smaller batches for better reliability
   - **Reduced timeouts**: Individual requests limited to 15 seconds, terms to 30 seconds
3. **Preview CSV**: Shows first 10 entries from generated CSV for verification
4. **Inject synonyms** (updated): `python utils/inject_synonyms.py --csv term_synonyms.csv --yaml dist/NF.yaml`
5. **Validate changes**: Check if YAML was modified and validate syntax
6. **Commit changes**: Automatically commit and push the updated `dist/NF.yaml` back to the repository
7. **Upload artifacts**: Both CSV and updated YAML are now included in releases and artifacts

## CSV Format Update

The generated `term_synonyms.csv` now has an updated format:

```csv
Term,Meaning_URI,Synonyms
3D imaging,NCIT:C18485,3-Dimensional Imaging; Medical Imaging Three Dimensional; Three Dimensional Imaging
ATAC-seq,OBI:0002039,Assay for Transposase-Accessible Chromatin; ATAC sequencing
```

**Key Changes:**
- **Meaning_URI column**: Now stores the original abbreviated URI from the YAML (e.g., `NCIT:C18485`)
- **Backward compatibility**: The injection script still works with older CSV formats that had full URLs

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

1. **Abbreviated URI support**: Seamlessly works with the new YAML format using shortened ontology URIs
2. **Automated synonym integration**: No more manual copying of synonyms
3. **Quality filtering**: Prevents low-quality aliases through intelligent deduplication
4. **Consistent format**: All aliases follow the same YAML structure
5. **Workflow integration**: Seamlessly fits into existing CI/CD pipeline
6. **Automatic updates**: Changes are automatically committed back to the repository
7. **Release assets**: Both CSV and updated YAML are available as release artifacts
8. **Backward compatibility**: Scripts work with both old and new URI formats

## Example Processing Output

The updated scripts provide detailed feedback during processing:

**YAML Format Verification:**
```
Checking for abbreviated URIs in NF.yaml...
Found 1247 abbreviated URIs and 23 full URLs
✓ Ready to process abbreviated URI format
```

**Synonym Extraction:**
```
Found 1270 terms to process
Processing batch 1/26 (50 terms)
Converting NCIT:C18485 to http://purl.obolibrary.org/obo/NCIT_C18485
Converting EFO:0009326 to http://www.ebi.ac.uk/efo/EFO_0009326
...
Processing complete! Results saved to term_synonyms.csv
```

**Synonym Injection:**
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
✓ YAML syntax is valid after synonym injection
```

This automation ensures the metadata dictionary maintains high-quality synonym mappings while reducing manual maintenance overhead.
