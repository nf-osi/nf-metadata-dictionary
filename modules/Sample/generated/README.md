# Filtered Enum Subsets for Conditional Filtering

This directory contains auto-generated filtered enum subsets used for conditional enum filtering in JSON schemas.

## Purpose

Synapse has a **100-value limit** for enum fields. The full `CellLineModel` enum has 638 values, which exceeds this limit. To work around this, we use **conditional filtering** with cascading dropdowns:

```
modelSystemType → modelSpecies → cellLineCategory → cellLineGeneticDisorder → modelSystemName
```

Based on the user's selections in the filter fields, the JSON schema shows only the relevant subset of model systems (always <100 values).

## Files

Each file contains a filtered subset of cell lines or animal models:

- `CellLineHomosapiensCancercelllineNeurofibromatosistype1Enum.yaml` - 54 human NF1 cancer cell lines
- `CellLineHomosapiensInducedpluripotentstemcellNeurofibromatosistype1Enum.yaml` - 32 human NF1 iPSCs
- etc. (29 files total)

## Build Process

These files are **source files** for the build process, not runtime files:

1. **Weekly Sync** (`weekly-model-system-sync.yml`)
   - Runs `utils/sync_model_systems.py`
   - Queries syn51730943 (NF Tools Central) for latest cell lines/models
   - Generates these filtered enum YAML files
   - Updates `CellLineModel.yaml`, `AnimalModel.yaml`, etc.

2. **Schema Generation** (manual or in CI)
   - Runs `utils/add_conditional_enum_filtering.py`
   - Reads these YAML files
   - Creates if/then conditional rules in JSON schemas
   - **Inlines enum values directly** (no $refs - Synapse doesn't support them)

3. **Upload to Synapse**
   - Only the final `registered-json-schemas/*.json` files are uploaded
   - These contain fully inlined enum values from this directory

## Data Source

- Table: **syn51730943** (NF Tools Central)
- Columns: `resourceName`, `species`, `cellLineCategory`, `cellLineGeneticDisorder`
- Maintained by the NFTC team

## Maintenance

These files are auto-generated weekly. **Do not edit manually.**

To regenerate:
```bash
python utils/sync_model_systems.py --synapse-id syn51730943
python utils/add_conditional_enum_filtering.py
python utils/gen-json-schema-class.py
```

## See Also

- [Conditional Enum Filtering Plan](../../../docs/conditional-enum-filtering-plan.md)
- Issue #797 (100-value enum limit)
