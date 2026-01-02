# Schema Update Scripts

This directory contains scripts for adding NF Tools Central links to schema enum values.

## Overview

These scripts query the NF Research Tools Central database (syn51730943) and automatically add `see_also` links to enum values in the schema YAML files. This allows the webdev team to access resource detail page URLs directly from the schema without needing to call a REST API.

## Prerequisites

```bash
# Install required Python packages
pip install synapseclient pandas pyyaml

# Set your Synapse auth token (optional for public table syn51730943)
export SYNAPSE_AUTH_TOKEN=your_token_here  # Optional
```

## Automated Updates via GitHub Actions

A GitHub workflow (`.github/workflows/update-tool-links.yml`) automatically runs weekly to keep the links up-to-date:

- **Schedule:** Every Monday at 10:00 AM UTC
- **Manual trigger:** Available via GitHub Actions UI
- **What it does:**
  1. Queries syn51730943 for latest resource data
  2. Updates `see_also` links in schema files
  3. Rebuilds data model artifacts
  4. Creates a pull request if changes are detected

**To trigger manually:**
1. Go to: `Actions` → `Update NF Tools Central Links` → `Run workflow`
2. Review the generated PR
3. Merge if everything looks correct

The workflow will automatically create a PR like: `Update NF Tools Central Links - 2026-01-02`

## Step 1: Explore the Table Structure

First, run the exploration script to identify the correct column name for resource IDs:

```bash
python scripts/explore_tools_table.py
```

This will:
- Show all column names in syn51730943
- Display sample data
- Look for the JH-2-002 example
- Help you identify which column contains the resource ID (the UUID in the URL)

## Step 2: Update Configuration

Based on the exploration output, update `scripts/add_tool_links.py` if needed:

```python
# Line 28: Update this if the column name is different
RESOURCE_ID_COLUMN = 'resourceId'  # or 'id', 'uuid', 'ROW_ID', etc.
```

## Step 3: Test with Dry Run

Run the script in dry-run mode to see what changes would be made:

```bash
python scripts/add_tool_links.py --dry-run
```

This will:
- Query syn51730943 for all cell lines and animal models
- Build URL mappings
- Show which enum values would be updated
- NOT write any changes to files

## Step 4: Add the Links

If the dry-run looks good, run the script to add the links:

```bash
python scripts/add_tool_links.py
```

This will update:
- `modules/Sample/CellLineModel.yaml` - adds `see_also` links to cell line enum values
- `modules/Sample/AnimalModel.yaml` - adds `see_also` links to animal model enum values

## Example Output

### Before:
```yaml
enums:
  CellLineEnum:
    permissible_values:
      "JH-2-002":
        description: "Collected during surgical resection from patients with NF1-MPNST"
```

### After:
```yaml
enums:
  CellLineEnum:
    permissible_values:
      "JH-2-002":
        description: "Collected during surgical resection from patients with NF1-MPNST"
        see_also:
        - https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=1bc84ef2-208f-4f0e-8045-6be47fd968de
```

## What About Antibodies and Genetic Reagents?

These resource types don't have predefined enums in the schema - they use free-text fields (`antibodyID` and `geneticReagentID`). For these, you have a few options:

### Option 1: Create a Separate Mapping File

Create a JSON file with the mappings:

```bash
python scripts/generate_resource_mapping.py > resources/tool_links.json
```

Then the webdev team can load this file to get the URLs.

### Option 2: Build URLs Dynamically

If the resource IDs follow a pattern or can be looked up from an index, the webdev team can build URLs dynamically.

### Option 3: Use the REST API

Continue using the tooltip service API endpoints for these resource types.

## Generated JSON Schemas

After running the script, regenerate the JSON schemas to include the new links:

```bash
# Your schema generation command here
# e.g., make schemas or python build.py
```

The `see_also` links will be included in the generated JSON schemas and accessible to the webdev team.

## Troubleshooting

### "Column 'resourceId' not found"

Run `explore_tools_table.py` to find the correct column name, then update `RESOURCE_ID_COLUMN` in `add_tool_links.py`.

### "Enum not found in YAML file"

Check that the `enum_name` in `RESOURCE_CONFIG` matches the actual enum name in the YAML file.

### "Access denied to syn51730943"

The syn51730943 table is open access and should work without authentication. If you encounter access issues:

1. Try with authentication:
   ```bash
   export SYNAPSE_AUTH_TOKEN=your_token_here
   python scripts/add_tool_links.py
   ```

2. Verify the table is accessible: https://www.synapse.org/#!Synapse:syn51730943

3. Check if your Synapse account has the necessary permissions

## Future Enhancements

- Support for antibody and genetic reagent enums (if they're added to the schema)
- Automatic detection of resource ID column name
- Validation that URLs are accessible
- Integration with CI/CD to keep links up-to-date
