# Model System Sync Documentation

This directory contains utilities for syncing model system names (cell lines and animal models) from the NFTC truth table in Synapse.

## Overview

The modelSystemName field in the NF metadata dictionary is automatically synchronized with the authoritative data source: Synapse table `syn26450069`. This ensures that the dictionary always reflects the current set of available cell lines and animal models used in NF research.

## Files

- `sync_model_systems.py` - Main sync script that fetches data from Synapse and updates enum files
- `../tests/test_model_system_sync.py` - Test suite for the sync functionality
- `../.github/workflows/weekly-model-system-sync.yml` - GitHub Actions workflow for automated weekly syncing

## How It Works

1. **Data Source**: The script fetches data from Synapse table `syn26450069` using the following columns:
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

# Actual sync (requires Synapse authentication)
python utils/sync_model_systems.py

# Sync from a different table
python utils/sync_model_systems.py --synapse-id syn12345678
```

## Authentication

The script uses Synapse authentication through:
1. `SYNAPSE_AUTH_TOKEN` environment variable (preferred for CI/CD)
2. Synapse client auto-login (for local development)

## Automated Workflow

The GitHub Actions workflow runs every Monday at 9:00 AM UTC and:
1. Fetches the latest data from Synapse
2. Updates the enum files if changes are detected
3. Rebuilds the data model artifacts (NF.jsonld, dist/NF.yaml)
4. Creates a pull request with the changes

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