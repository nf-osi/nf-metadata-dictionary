# Utilities Documentation

This directory contains utilities for maintaining the NF metadata dictionary, including syncing model systems from Synapse.

## Overview

The modelSystemName field in the NF metadata dictionary is automatically synchronized with the authoritative data source: the NF Research Tools Central view `syn51730943` (the legacy Resource table `syn26450069` was retired). This ensures that the dictionary always reflects the current set of available cell lines and animal models used in NF research.

## Scripts

### sync_model_systems.py

Main sync script that fetches model system data from Synapse and updates enum files.

**Related files:**
- `../tests/test_model_system_sync.py` - Test suite for the sync functionality
- `../.github/workflows/weekly-model-system-sync.yml` - GitHub Actions workflow for automated weekly syncing

### Annotation review (removed)

`review_annotations.py` was removed in [#904](https://github.com/nf-osi/nf-metadata-dictionary/issues/904). Follow-up: `platform` review in [#1048](https://github.com/nf-osi/nf-metadata-dictionary/issues/1048); `antibodyID`/`geneticReagentID` review in [nf-research-tools-schema#381](https://github.com/nf-osi/nf-research-tools-schema/issues/381). `individualID` is reviewed in nf-research-tools-schema.

## How It Works

1. **Data Source**: The script fetches data from Synapse view `syn51730943` using the following columns:
   - `resourceName` - The name of the cell line or animal model
   - `rrid` - Research Resource Identifier (RRID) for linking to external databases
   - `resourceType` - Categorizes as "cell line" or "animal model"

2. **Categorization**: Resources are automatically categorized based on the `resourceType` field:
   - Resources with "cell line" in the type go to `modules/Sample/CellLineModel.yaml`
   - Resources with "animal model" or "mouse" in the type go to `modules/Sample/AnimalModel.yaml`

3. **Formatting**: Each resource entry includes:
   - Resource name as the YAML key
   - Description (defaults to resource name if not provided)
   - Source URL generated from RRID when available

## Manual Usage

To manually run the sync script:

```bash
# Dry run to see what would be changed
python utils/sync_model_systems.py --dry-run

# Actual sync
python utils/sync_model_systems.py

# Sync from a different table
python utils/sync_model_systems.py --synapse-id syn12345678
```

## Authentication

None required. The source view (`syn51730943`) is open access, so the script queries Synapse anonymously and does not log in.

## Automated Workflow

The GitHub Actions workflow runs every Monday at 9:00 AM UTC and:
1. Fetches the latest data from Synapse
2. Updates the enum files if changes are detected
3. Creates a pull request with the `modules/` changes only (build artifacts are regenerated after the PR is merged into main)

## Testing

Run the test suite to validate sync functionality:

```bash
python tests/test_model_system_sync.py
```

The tests verify:
- Enum entry formatting
- File update functionality  
- Existing file structure validity

## Architecture Changes

As part of issue #668, the following changes were made:

1. **MouseModel → AnimalModel**: Generalized the concept from mouse-specific to any animal model
2. **File rename**: `modules/Sample/MouseModel.yaml` → `modules/Sample/AnimalModel.yaml`
3. **Reference updates**: Updated `modules/props.yaml` and other files to reference `AnimalModel`
4. **Weekly sync**: Added automated synchronization with the NFTC truth table

This ensures the metadata dictionary stays current with the research community's available resources while generalizing the model system concept beyond just mouse models.