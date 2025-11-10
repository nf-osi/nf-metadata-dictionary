# Development Guide

Developer-oriented documentation for the NF Metadata Dictionary. For general overview, see the root [README](../README.md).

## Quick Reference

| Task | Command |
|------|---------|
| **Build all artifacts** | `make all` |
| **Generate single schema** | `python utils/gen-json-schema-class.py --class DataLandscape --skip-validation` |
| **Validate all schemas** | `python utils/gen-json-schema-class.py` |
| **Register schemas** | `python utils/register-schemas.py` |
| **Create file-based task** | `python utils/create_curation_task.py --folder-id syn123 --template RNASeqTemplate` |
| **Create record-based task** | `python utils/create_recordset_task.py --project-id syn123 --folder-id syn456 --recordset-name "Study_2025" --template DataLandscape` |

---

## Table of Contents

1. [Background & Architecture](#background--architecture)
2. [JSON Schema Integration with Synapse](#json-schema-integration-with-synapse)
3. [Schema Generation & Management](#schema-generation--management)
4. [Curation Task Management](#curation-task-management)

---

## Background & Architecture

### Evolution of the Data Model

**CSV Era (Original)**
Single `.csv` file compiled to JSONLD for schematic framework validation.

**Modular CSV Era**
CSV files split into modules for easier development.

**LinkML Era (Current)**
YAML source files using the LinkML framework, compiled to:
- **NF.jsonld** - Schematic-compatible format (legacy support)
- **JSON schemas** - Synapse platform validation (primary)
- **dist/NF.yaml** - Merged LinkML YAML
- **dist/NF.ttl** - RDF/Turtle format

### Current Validation Approach

Validation is now handled directly by the **Synapse platform** using standard JSON schemas, rather than the schematic Python package. The JSONLD format remains useful for semantic data model comparison.

---

## JSON Schema Integration with Synapse

### Schema Registration and Binding

**Registration:** Schemas must be registered with Synapse before use.

**Binding:** Registered schemas are "bound" to Synapse entities (folders, RecordSets) to enable validation. Child entities inherit parent schema bindings (similar to sharing settings).

**Reference:** [Synapse JSON Schema Docs](https://help.synapse.org/docs/JSON-Schemas.3107291536.html)

### $refs (Schema References)

Synapse supports `$refs` in a limited way:
- ✅ References to definitions **within** the same schema
- ✅ References to **other Synapse-registered** schemas
- ❌ References to non-registered schemas

Our conversion pipeline uses dereferencing for simplicity.

**Reference:** [Synapse REST API Docs](https://rest-docs.synapse.org/rest/POST/schema/type/create/async/start.html)

### If-Then-Else (Conditional Schemas)

JSON Schema's `if-then-else` enables:
1. **Derived annotations** - Auto-populate fields based on other values
2. **Dynamic schema application** - Apply different schemas based on field values (e.g., different validation for `dataType: "image"` vs `dataType: "gene expression"`)

Complex conditional rules are stored in `rules/` directory.

**Example use case:** When `dataType` changes, appropriate assay options, file formats, and required fields update automatically.

<details>
<summary>Example: Dynamic schema based on dataType (click to expand)</summary>

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-data",
  "properties": {
    "dataType": {
      "enum": ["gene expression", "aligned reads", "image", "clinical data", "workflow report"]
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "dataType": { "const": "gene expression" }
        }
      },
      "then": {
        "$ref": "org.synapse.nf-genomicsassaytemplate"
      }
    },
    {
      "if": {
        "properties": {
          "dataType": { "const": "image" }
        }
      },
      "then": {
        "$ref": "org.synapse.nf-imagingassaytemplate"
      }
    }
  ]
}
```
</details>

---

## Schema Generation & Management

### CI/CD Workflows

**PR Validation** (`.github/workflows/main-ci.yml`)
1. Generates JSON schemas from LinkML sources
2. Validates against Synapse API (dry-run)
3. Reports results in PR comment
4. Blocks merge if validation fails

**Schema Registration**
Typically performed on versioned releases using `register-schemas.py`.

### Development Scripts

#### gen-json-schema-class.py

Generate and validate JSON schemas from LinkML sources.

**Usage:**
```bash
# Generate all schemas with validation
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/gen-json-schema-class.py

# Generate single schema without validation (fast, for testing)
python utils/gen-json-schema-class.py --class DataLandscape --skip-validation

# Generate single schema with validation
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/gen-json-schema-class.py --class DataLandscape

# Generate with version (esp. if intended for official release)
python utils/gen-json-schema-class.py --version 0.2.0
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--schema-yaml` | Path to LinkML YAML schema | `dist/NF.yaml` |
| `--output-dir` | Output directory for schemas | `registered-json-schemas` |
| `--class` | Generate only specific class | All classes |
| `--skip-validation` | Skip Synapse validation | False |
| `--version` | Semantic version for schema URIs | None |
| `--log-file` | Validation log file path | `schema-validation-log.md` |

#### register-schemas.py

Register validated JSON schemas with Synapse.

**Usage:**
```bash
# Register all schemas
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/register-schemas.py

# Register specific schemas only
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/register-schemas.py \
  --include DataLandscape.json PortalDataset.json

# Register all *except* specific schemas
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/register-schemas.py \
  --exclude Superdataset.json Template.json
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--schema-dir` | Directory with JSON schemas | `registered-json-schemas` |
| `--log-file` | Registration log file path | `schema-registration-log.md` |
| `--include` | Only register these files | All files |
| `--exclude` | Exclude these files | None |

**Note:** `--include` overrides `--exclude` if both provided.

---

## Curation Task Utilities (Downstream Schema Setup and Testing)

Synapse curation tasks enable structured metadata collection using the registered JSON schemas. Two task types are supported:

### Dependencies

Scripts require synapsePythonClient develop branch:

```bash
pip install git+https://github.com/Sage-Bionetworks/synapsePythonClient.git@develop
```

### File-Based Curation Tasks

**Use case:** Associate metadata with uploaded files in a folder (e.g., sequencing data, images).

**Script:** `utils/create_curation_task.py`

**What it creates:**
- EntityView (file view) with schema-derived columns
- CurationTask bound to the folder
- Auto-generated dataType: `{template_base}-{folder_id}`

**Usage:**
```bash
# Basic file-based task
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_curation_task.py \
  --folder-id syn12345678 \
  --template RNASeqTemplate

# With custom instructions
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_curation_task.py \
  --folder-id syn12345678 \
  --template ImagingAssayTemplate \
  --instructions "Please curate microscopy data with complete experimental metadata"
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--folder-id` | Upload folder Synapse ID (required) | - |
| `--template` | Template name or schema URI (required) | - |
| `--instructions` | Instructions for contributors | "Please add metadata for your files" |
| `--bind-schema` / `--no-bind-schema` | Bind schema to folder | True |
| `--output-format` | `json` or `github` | `json` |

**Output:** `task_id`, `fileview_id`, `data_type`, `schema_uri`, `project_id`

### Record-Based Curation Tasks

**Use case:** Structured metadata records not tied to individual files (e.g., data landscape, publication records, cohort info).

**Script:** `utils/create_recordset_task.py`

**What it creates:**
- RecordSet with schema binding
- CurationTask for the record workflow
- DataGrid interface for editing records

**Usage:**
```bash
# Basic recordset task with upsert keys (defines record uniqueness)
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_recordset_task.py \
  --project-id syn12345678 \
  --folder-id syn87654321 \
  --recordset-name "DDI_Doe_2026" \
  --template DataLandscape \
  --upsert-keys study name
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--project-id` | Synapse project ID (required) | - |
| `--folder-id` | Folder ID for RecordSet (required) | - |
| `--recordset-name` | RecordSet name/identifier (required) | - |
| `--template` | Template name or schema URI (required) | - |
| `--description` | RecordSet description | Auto-generated |
| `--task-name` | Curation task name | Auto-generated |
| `--upsert-keys` | Fields that uniquely identify records | None |
| `--instructions` | Instructions for contributors | "Please add metadata records" |
| `--bind-schema` / `--no-bind-schema` | Bind schema to RecordSet | True |
| `--output-format` | `json` or `github` | `json` |

**Output:** `recordset_id`, `task_id`, `data_grid_session_id`, `schema_uri`, `project_id`, `folder_id`, `record_set_name`

**Note on upsert keys:** Specify field names that uniquely identify each record. This enables updates to existing records rather than creating duplicates. Common choices: `study`, `name`, `individualID`, etc.

---

## Additional Resources

- **LinkML Documentation:** https://linkml.io
- **Synapse JSON Schema Docs:** https://help.synapse.org/docs/JSON-Schemas.3107291536.html
- **Schematic Tooling (in development):** https://sagebionetworks.jira.com/wiki/x/QIBD-/
