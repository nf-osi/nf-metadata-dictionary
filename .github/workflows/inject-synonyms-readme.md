# Synonym Injection Workflow

## Quick Start

The synonym injection workflow is designed for fast, testable deployment of synonym data into module YAML files.

### Test Mode (Recommended First Step)
```bash
# Run in test mode to see what would change
gh workflow run inject-synonyms.yml -f test_mode=true
```

### Production Mode
```bash
# Apply changes and create PR for review
gh workflow run inject-synonyms.yml
```

### Custom CSV File
```bash
# Use a different CSV file
gh workflow run inject-synonyms.yml -f csv_file=custom_synonyms.csv
```

## Workflow Behavior

### When `test_mode=true`
- ✅ Validates CSV file exists and has content
- ✅ Shows what changes would be made (dry-run)
- ✅ No files are modified
- ✅ No pull request is created
- ⏱️ Completes in ~2 minutes

### When `test_mode=false` (default)
- ✅ Validates CSV file exists and has content  
- ✅ Injects synonyms into module YAML files
- ✅ Creates pull request if changes are detected
- ✅ Adds detailed PR description with change summary
- ⏱️ Completes in ~5 minutes

## Input Parameters

| Parameter | Description | Default | Required |
|-----------|-------------|---------|----------|
| `csv_file` | Path to synonym CSV file | `term_synonyms.csv` | No |
| `test_mode` | Run in dry-run mode | `false` | No |

## Output Scenarios

### ✅ Success with Changes
- Module files are updated with new aliases
- Pull request is created for review
- Workflow summary shows modified files

### ℹ️ Success with No Changes  
- All synonyms already present in module files
- No pull request is created
- Workflow summary reports "no changes needed"

### ❌ Failure Scenarios
- CSV file not found or empty
- Invalid YAML syntax in module files
- Permission issues writing to files

## Quality Filtering

The injection process applies intelligent filtering:

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

## Pull Request Details

When changes are detected, the workflow creates a PR with:

### Title
`"Inject synonyms: Update module files with synonym aliases"`

### Description Includes
- 📊 Summary of changes made
- 📁 List of modified module files  
- 🧹 Details of quality filtering applied
- ✅ Review checklist for maintainers
- 📈 Statistics (files processed, files modified)

### Labels
- `automated`
- `synonyms` 
- `injection`

### Branch Name
`synonym-injection-{workflow-run-id}` (auto-deleted after merge)

## Troubleshooting

### CSV File Not Found
```
Error: CSV file 'term_synonyms.csv' not found
Available files:
[list of CSV files in repository]
```
**Solution**: Ensure the CSV file exists or specify correct path with `csv_file` parameter

### No Changes Detected
```
ℹ️ No Changes: No synonym injection needed
- CSV file: term_synonyms.csv processed successfully  
- Module files: No updates required (synonyms already present)
```
**Solution**: This is normal if synonyms are already up-to-date

### YAML Syntax Errors
```
Error processing modules/Sample/Species.yaml: 
YAML syntax error at line 15
```
**Solution**: Fix YAML syntax errors in the indicated module file

## Integration with Extraction Workflow

1. **Extract synonyms**: Run `extract-synonyms.yml` to generate/update CSV
2. **Download artifacts**: Get the CSV file from workflow artifacts  
3. **Test injection**: Run `inject-synonyms.yml` with `test_mode=true`
4. **Apply changes**: Run `inject-synonyms.yml` to create PR
5. **Review & merge**: Review the PR and merge when ready

## Development Tips

### Quick Testing Cycle
```bash
# 1. Test your changes
gh workflow run inject-synonyms.yml -f test_mode=true

# 2. Check the workflow output
gh run list --workflow=inject-synonyms.yml --limit 1

# 3. Apply if satisfied  
gh workflow run inject-synonyms.yml
```

### Custom CSV Testing
```bash
# Create a small test CSV
echo "term,synonyms" > test_synonyms.csv
echo "3D imaging,3D-EM,electron tomography" >> test_synonyms.csv

# Commit and test
git add test_synonyms.csv && git commit -m "Add test CSV"
gh workflow run inject-synonyms.yml -f csv_file=test_synonyms.csv -f test_mode=true
```

### Local Testing
```bash
# Test locally before running workflow
cd /path/to/nf-metadata-dictionary
python utils/inject_synonyms.py --csv term_synonyms.csv --modules-dir modules --dry-run
```

This workflow provides a fast, reliable way to apply synonym data to the metadata dictionary with full testing capabilities and automatic PR creation for review.
