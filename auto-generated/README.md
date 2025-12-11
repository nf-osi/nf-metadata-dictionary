# Auto-Generated Research Tools Schemas

This directory contains automatically generated JSON Schema enumerations and attribute mappings derived from the NF research tools database on Synapse.

## ⚠️ WARNING: DO NOT EDIT MANUALLY

**All files in this directory are automatically generated and will be overwritten.**

- Manual edits will be lost on the next update
- To add custom entries, submit them to the source Synapse tables
- For questions or corrections, please open an issue

## Directory Structure

```
auto-generated/
├── README.md                    # This file
├── LAST_UPDATED.txt            # Timestamp and summary of last update
├── generation_metadata.json    # Detailed generation metadata
├── enums/                      # JSON Schema enumeration files
│   ├── modelSystemName_enum.json
│   ├── cellLineName_enum.json
│   ├── antibodyName_enum.json
│   ├── reagentName_enum.json
│   └── biobank_enum.json
├── mappings/                   # Attribute mapping files
│   ├── animal_models_mappings.json
│   ├── cell_lines_mappings.json
│   ├── antibodies_mappings.json
│   ├── genetic_reagents_mappings.json
│   └── biobanks_mappings.json
└── raw/                       # Raw data fetched from Synapse (ephemeral)
    ├── animal_models.json
    ├── cell_lines.json
    ├── antibodies.json
    ├── genetic_reagents.json
    ├── biobanks.json
    └── fetch_metadata.json
```

## What Are These Files?

### Enum Files (`enums/*.json`)

**Purpose:** Provide controlled vocabularies (dropdown options) for metadata fields.

**Format:** JSON Schema Draft 07 enumeration

**Example:** `modelSystemName_enum.json`
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Animal Model Names (Auto-generated)",
  "type": "string",
  "enum": [
    "Nf1flox/flox;Dhh-Cre (MGI:3056727)",
    "Nf2flox/flox;Plp-CreERT (MGI:5473891)",
    ...
  ],
  "meta:sourceTable": "syn26486808",
  "meta:lastUpdated": "2025-01-15T06:00:00Z",
  "meta:recordCount": 127
}
```

**Usage:**
- Validation systems (schematic, DCA) use these to constrain user input
- Dropdown menus and autocomplete fields populated from these values
- Ensures consistent naming across metadata submissions

### Mapping Files (`mappings/*.json`)

**Purpose:** Enable auto-fill of related metadata fields when a tool is selected.

**Format:** JSON object mapping tool names to attribute dictionaries

**Example:** `animal_models_mappings.json`
```json
{
  "Nf1flox/flox;Dhh-Cre (MGI:3056727)": {
    "species": "Mus musculus",
    "organism": "Mouse",
    "genotype": "Nf1tm1Par/tm1Par",
    "backgroundStrain": "C57BL/6J",
    "RRID": "MGI:3056727",
    "modelSystemType": "animal",
    "geneticModification": "conditional knockout",
    "targetGene": "NF1",
    "sourceURL": "https://www.jax.org/strain/024738",
    "repository": "JAX"
  }
}
```

**Usage:**
- When user selects `modelSystemName: "Nf1flox/flox;Dhh-Cre (MGI:3056727)"`, the system can auto-fill:
  - `species: "Mus musculus"`
  - `genotype: "Nf1tm1Par/tm1Par"`
  - `RRID: "MGI:3056727"`
  - etc.

## Source Data

Data is fetched from the following Synapse tables:

| Tool Type | Synapse Table ID | Schema Field |
|-----------|------------------|--------------|
| Animal Models | `syn26486808` | `modelSystemName` |
| Cell Lines | `syn26486823` | `cellLineName` |
| Antibodies | `syn26486811` | `antibodyName` |
| Genetic Reagents | `syn26486832` | `reagentName` |
| Biobanks | `syn26486821` | `biobank` |

**Materialized View:** `syn51730943` (contains essential info from all tables)

## Update Process

### Automated Updates

Files are automatically updated via GitHub Actions:

- **Schedule:** Every Monday at 6:00 AM UTC
- **Workflow:** `.github/workflows/update-tool-enums.yml`
- **Process:**
  1. Fetch latest data from Synapse tables
  2. Generate enums and mappings
  3. Validate all schemas
  4. Create pull request if changes detected
  5. Manual review and merge

### Manual Trigger

You can manually trigger an update:

1. Go to **Actions** → **Update Research Tool Enums**
2. Click **Run workflow**
3. Wait for the workflow to complete
4. Review and merge the generated PR

### Local Generation

To regenerate locally (for testing):

```bash
# 1. Install dependencies
pip install synapseclient pandas jsonschema pyyaml

# 2. Set up Synapse authentication
export SYNAPSE_AUTH_TOKEN="your-token-here"

# 3. Fetch data from Synapse
python scripts/fetch_synapse_tools.py \
  --tables syn26486808,syn26486823,syn26486811,syn26486832,syn26486821 \
  --output auto-generated/raw/

# 4. Generate enums and mappings
python scripts/generate_tool_schemas.py \
  --input auto-generated/raw/ \
  --output auto-generated/

# 5. Validate generated files
python scripts/validate_generated_schemas.py \
  --directory auto-generated/
```

## Integration with Downstream Systems

### Schematic Integration

Schematic reads these files to:
- Populate dropdown menus in Data Curator App
- Validate metadata submissions
- Auto-fill related fields based on mappings

**Integration points:**
- Enum files referenced in data model validation rules
- Mappings used for intelligent form auto-fill
- RRID validation against known tools

### Data Curator App (DCA)

DCA configuration uses these files to:
- Constrain picklist options
- Enable "Quick Fill" functionality
- Provide tool suggestions during metadata entry

### Synapse Upload Forms

- Form builders use enums for dropdown constraints
- Backend validation checks against current enums
- Auto-population of tool attributes

## Field Mappings

### Animal Models

| Source Column | Schema Field | Notes |
|---------------|--------------|-------|
| `resourceName` | `modelSystemName` | Primary identifier |
| `rrid` | `RRID` | Research Resource Identifier |
| `species` | `species` | Full species name |
| `species` (first word) | `organism` | Common name (e.g., "Mouse") |
| `genotype` | `genotype` | Genetic notation |
| `backgroundStrain` | `backgroundStrain` | Strain background |
| `geneticModification` | `geneticModification` | Type of modification |
| `targetGene` | `targetGene` | Gene targeted |
| `resourceURL` | `sourceURL` | Reference URL |
| `repository` | `repository` | Source repository (JAX, MMRRC, etc.) |
| — | `modelSystemType` | Always "animal" |

### Cell Lines

| Source Column | Schema Field | Notes |
|---------------|--------------|-------|
| `resourceName` | `cellLineName` | Primary identifier |
| `rrid` | `RRID` | Research Resource Identifier |
| `species` | `species` | Species of origin |
| `tissue` | `tissue` | Tissue type |
| `organ` | `organ` | Organ of origin |
| `cellType` | `cellType` | Cell type classification |
| `disease` | `disease` | Associated disease |
| `strProfile` | `STRProfile` | STR authentication status |
| `vendor` | `vendor` | Vendor/supplier |
| `catalogNumber` | `catalogNumber` | Catalog ID |
| `resourceURL` | `sourceURL` | Reference URL |
| — | `modelSystemType` | Always "cell line" |

### Antibodies

| Source Column | Schema Field | Notes |
|---------------|--------------|-------|
| `resourceName` | `antibodyName` | Primary identifier |
| `antibodyID` | `antibodyID` | Unique ID |
| `targetProtein` | `targetProtein` | Target antigen |
| `hostSpecies` | `hostSpecies` | Host organism |
| `clonality` | `clonality` | Monoclonal/polyclonal |
| `applications` | `applications` | Validated applications |
| `rrid` | `RRID` | Research Resource Identifier |
| `vendor` | `vendor` | Vendor/supplier |
| `catalogNumber` | `catalogNumber` | Catalog ID |
| `resourceURL` | `sourceURL` | Product URL |

### Genetic Reagents

| Source Column | Schema Field | Notes |
|---------------|--------------|-------|
| `resourceName` | `reagentName` | Primary identifier |
| `reagentID` | `reagentID` | Unique ID |
| `reagentType` | `reagentType` | Plasmid/shRNA/CRISPR/etc. |
| `targetGene` | `targetGene` | Target gene |
| `vectorBackbone` | `vectorBackbone` | Vector backbone |
| `rrid` | `RRID` | Research Resource Identifier |
| `repository` | `repository` | Source (Addgene, DNASU, etc.) |
| `catalogNumber` | `catalogNumber` | Catalog ID |
| `resourceURL` | `sourceURL` | Repository URL |

### Biobanks

| Source Column | Schema Field | Notes |
|---------------|--------------|-------|
| `resourceName` | `biobank` | Primary identifier |
| `biobankID` | `biobankID` | Unique ID |
| `sampleType` | `sampleType` | Type of samples |
| `tissue` | `tissue` | Tissue types available |
| `biospecimenType` | `biospecimenType` | Specimen classification |
| `accessProcedure` | `accessProcedure` | How to request samples |
| `institution` | `institution` | Hosting institution |
| `resourceURL` | `sourceURL` | Biobank website |

## Validation Rules

Generated schemas are validated to ensure:

### JSON Schema Compliance
- ✅ Valid JSON Schema Draft 07 format
- ✅ Required fields present (`type`, `enum`, etc.)
- ✅ Correct data types

### Data Quality
- ✅ No duplicate enum values
- ✅ No null/empty values in enums
- ✅ Consistent RRID formatting
- ✅ Enum/mapping consistency (all enum values have mappings)

### Metadata Integrity
- ⚠️ Warning if RRID duplicates detected
- ⚠️ Warning if mappings have null attributes
- ⚠️ Warning if record counts mismatch

## Changelog

Changes are tracked in pull requests:
- Each update creates a new PR with detailed change summary
- PR body includes counts of new/modified/removed entries
- Reviewers can inspect diffs before merging

**Recent Updates:** See `LAST_UPDATED.txt` and recent PRs with label `auto-generated`

## Troubleshooting

### No Changes Detected But Data Changed

**Possible causes:**
- Changes only affected internal IDs (ROW_ID, ROW_VERSION)
- Changes to columns not mapped to schema fields
- Duplicate entries filtered out

**Solution:** Check raw data files in `auto-generated/raw/`

### Validation Errors

**Common issues:**
- Malformed RRIDs → Check source table data
- Duplicate tool names → Ensure unique names in Synapse
- Missing required columns → Verify table schema

**Solution:** Review validation output and correct source data

### Missing Tools

**Possible causes:**
- Tool lacks required fields (name, type)
- Tool filtered as duplicate
- Wrong `resourceType` classification in source table

**Solution:** Check `scripts/generate_tool_schemas.py` field mappings

## Contributing

To improve this system:

1. **Report issues:** [GitHub Issues](https://github.com/nf-osi/nf-metadata-dictionary/issues)
2. **Update source tables:** Submit corrections to Synapse tables
3. **Enhance scripts:** Modify generation scripts in `scripts/`
4. **Adjust mappings:** Edit `FIELD_MAPPINGS` in `generate_tool_schemas.py`

## Related Documentation

- [Main README](../README.md) - Overview of metadata dictionary
- [Contributing Guide](../CONTRIBUTING.md) - How to contribute
- [GitHub Issue #27](https://github.com/nf-osi/2025-sage-hack-ideas/issues/27) - Original feature request
- [Schematic Documentation](https://github.com/Sage-Bionetworks/schematic) - Data validation framework

## Questions?

For questions or support:
- Open an [issue](https://github.com/nf-osi/nf-metadata-dictionary/issues)
- Contact: NF-OSI Data Team

---

**Last Updated:** See `LAST_UPDATED.txt`
**Automation:** `.github/workflows/update-tool-enums.yml`
**Scripts:** `scripts/fetch_synapse_tools.py`, `scripts/generate_tool_schemas.py`
