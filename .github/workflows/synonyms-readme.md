# Unified Synonyms Workflow

## Overview

The unified synonyms workflow (`synonyms.yml`) provides comprehensive synonym management for the NF metadata dictionary. It combines extraction and injection capabilities into a single, flexible workflow.

## Quick Start

### Extract and Inject (Full Pipeline)
```bash
# Run full pipeline: extract synonyms then inject into modules
gh workflow run synonyms.yml -f action=extract-and-inject
```

### Extract Only
```bash
# Extract synonyms and create CSV file only
gh workflow run synonyms.yml -f action=extract-only
```

### Inject Only
```bash
# Inject existing CSV into modules
gh workflow run synonyms.yml -f action=inject-only

# Inject with custom CSV file
gh workflow run synonyms.yml -f action=inject-only -f csv_file=custom_synonyms.csv
```

### Test Mode
```bash
# Test any action without making changes (dry-run)
gh workflow run synonyms.yml -f action=extract-and-inject -f test_mode=true
```

## Workflow Actions

### `extract-and-inject` (Default)
- ✅ Extracts synonyms from external ontology sources
- ✅ Creates/updates `term_synonyms.csv` 
- ✅ Injects synonyms into module YAML files
- ✅ Creates pull request if changes detected
- ⏱️ Duration: 60-70 minutes

### `extract-only`
- ✅ Extracts synonyms from external ontology sources
- ✅ Creates/updates `term_synonyms.csv`
- ✅ Uploads CSV as workflow artifact
- ❌ No module injection
- ⏱️ Duration: 60-65 minutes

### `inject-only`
- ✅ Uses existing CSV file (specify with `csv_file` parameter)
- ✅ Injects synonyms into module YAML files
- ✅ Creates pull request if changes detected
- ❌ No extraction performed
- ⏱️ Duration: 5-10 minutes

## Input Parameters

| Parameter | Description | Options | Default | Required |
|-----------|-------------|---------|---------|----------|
| `action` | What to perform | `extract-and-inject`, `extract-only`, `inject-only` | `extract-and-inject` | Yes |
| `csv_file` | CSV file path (for inject modes) | Any CSV file in repo | `term_synonyms.csv` | No |
| `test_mode` | Run in dry-run mode | `true`, `false` | `false` | No |

## Automatic Triggers

### Release Publication
When a new release is published, the workflow automatically runs with:
- Action: `extract-and-inject`
- Test mode: `false`
- CSV file: `term_synonyms.csv`

This ensures synonyms are always up-to-date for new releases.

## Test Mode Behavior

When `test_mode=true`:

### Extraction (if enabled)
- ✅ Shorter timeout (30 minutes vs 60 minutes)
- ✅ Creates CSV file
- ✅ Shows extraction progress
- ❌ No commits or PRs created

### Injection (if enabled)  
- ✅ Validates CSV file exists and has content
- ✅ Shows what changes would be made (dry-run mode)
- ✅ Reports filtering and matching statistics
- ❌ No files are modified
- ❌ No pull request is created

## Production Mode Behavior

When `test_mode=false` (default):

### Extraction (if enabled)
- ✅ Full 60-minute extraction timeout
- ✅ Processes all available terms
- ✅ Creates comprehensive CSV file
- ✅ Uploads CSV as artifact

### Injection (if enabled)
- ✅ Validates CSV file exists and has content
- ✅ Injects synonyms into module YAML files  
- ✅ Creates pull request if changes are detected
- ✅ Adds detailed PR description with change summary

## Output Scenarios

### ✅ Success with Changes
- Files are updated with new synonyms/aliases
- Pull request is created for review
- Workflow summary shows modified files
- CSV artifact uploaded (if extraction performed)

### ℹ️ Success with No Changes
- All synonyms already present in files
- No pull request is created
- Workflow summary reports "no changes needed"
- CSV artifact still uploaded (if extraction performed)

### ❌ Failure Scenarios
- CSV file not found or empty (inject modes)
- Extraction timeout without usable results
- Invalid YAML syntax in module files
- Permission issues writing to files

## Quality Filtering

The injection process applies intelligent filtering to ensure high-quality synonyms:

### Case-Only Differences
Skips synonyms that differ only by capitalization/punctuation:
- `"3D imaging"` vs `"3-D Imaging"` → Skipped
- `"RNA-seq"` vs `"RNA seq"` → Skipped

### Fuzzy Matching (90% similarity threshold)
Skips near-duplicate synonyms:
- `"Three-Dimensional Imaging"` vs `"Three Dimensional Imaging"` → Skipped
- `"Mass Spectrometry"` vs `"mass spectrometry"` → Skipped

### Term Similarity
Skips synonyms too similar to the original term:
- Term: `"3D imaging"`, Synonym: `"3D-imaging"` → Skipped

### Existing Alias Check
Skips synonyms already present in the module file:
- Prevents duplicate aliases
- Preserves manually added aliases

## Pull Request Details

When changes are detected, the workflow creates a PR with:

### Title
`"Update synonyms: {action}"`

### Description Includes
- 🔄 Action performed (`extract-and-inject`, `inject-only`, etc.)
- 📊 Summary of changes made
- 📁 List of modified files
- 🧹 Details of quality filtering applied
- ✅ Review checklist for maintainers
- 📈 Statistics and workflow details

### Labels
- `automated`
- `synonyms`
- Action-specific label (`extract-and-inject`, `inject-only`, etc.)

### Branch Name
`synonyms-update-{workflow-run-id}` (auto-deleted after merge)

## Common Usage Patterns

### Regular Synonym Updates
```bash
# Monthly synonym refresh
gh workflow run synonyms.yml -f action=extract-and-inject

# Test first, then apply
gh workflow run synonyms.yml -f action=extract-and-inject -f test_mode=true
gh workflow run synonyms.yml -f action=extract-and-inject
```

### Custom Synonym Integration
```bash
# 1. Create custom CSV file
echo "term,synonyms" > custom_terms.csv
echo "3D imaging,3D-EM,electron tomography,cryo-EM" >> custom_terms.csv

# 2. Commit the file
git add custom_terms.csv && git commit -m "Add custom synonyms"

# 3. Test injection
gh workflow run synonyms.yml -f action=inject-only -f csv_file=custom_terms.csv -f test_mode=true

# 4. Apply if satisfied
gh workflow run synonyms.yml -f action=inject-only -f csv_file=custom_terms.csv
```

### Extract for External Use
```bash
# Extract synonyms without modifying modules
gh workflow run synonyms.yml -f action=extract-only

# Download the CSV artifact for external processing
gh run list --workflow=synonyms.yml --limit 1
gh run download [RUN_ID] --name synonym-csv-[RUN_ID]
```

## Troubleshooting

### CSV File Not Found (inject modes)
```
❌ Error: CSV file 'custom_file.csv' not found
Available CSV files:
term_synonyms.csv
```
**Solution**: Ensure the CSV file exists in the repository root or specify correct path

### Extraction Timeout
```
⏰ Extraction timed out after 60 minutes, but partial results may be available
```
**Solution**: This is normal for large extractions. The partial CSV will still be useful and uploaded as an artifact

### No Changes Detected
```
ℹ️ No Changes: No synonym updates needed
- CSV file: term_synonyms.csv processed successfully
- Module files: No updates required (synonyms already up-to-date)
```
**Solution**: This is normal if synonyms are already current. No action needed.

### YAML Syntax Errors
```
❌ Error processing modules/Sample/Species.yaml: 
YAML syntax error at line 15
```
**Solution**: Fix YAML syntax errors in the indicated module file before running workflow

## Local Testing

Before running the workflow, you can test locally:

### Test Extraction
```bash
cd /path/to/nf-metadata-dictionary
python utils/extract_synonyms.py
```

### Test Injection
```bash
# Dry-run mode
python utils/inject_synonyms.py --csv term_synonyms.csv --modules-dir modules --dry-run

# Production mode
python utils/inject_synonyms.py --csv term_synonyms.csv --modules-dir modules
```

## Migration from Separate Workflows

If you were using the separate `extract-synonyms.yml` and `inject-synonyms.yml` workflows:

### Replace Extract-Only Usage
```bash
# Old
gh workflow run extract-synonyms.yml

# New  
gh workflow run synonyms.yml -f action=extract-only
```

### Replace Inject-Only Usage
```bash
# Old
gh workflow run inject-synonyms.yml

# New
gh workflow run synonyms.yml -f action=inject-only
```

### Replace Combined Usage
```bash
# Old (manual coordination)
gh workflow run extract-synonyms.yml
# wait for completion, download artifact
gh workflow run inject-synonyms.yml

# New (automatic coordination)
gh workflow run synonyms.yml -f action=extract-and-inject
```

This unified workflow provides better coordination, simpler management, and more flexible synonym processing options.
