# Development Guide

Developer-oriented documentation for the NF Metadata Dictionary. For general overview, see the [README](../README.md).

## Quick Reference

| Task | Command |
|------|---------|
| **Build all artifacts** | `make all` |
| **Generate single schema** | `python utils/gen-json-schema-class.py --class DataLandscape --skip-validation` |
| **Validate all schemas** | `python utils/gen-json-schema-class.py` |
| **Register schemas** | `python utils/register-schemas.py` |
| **Create file-based task** | `python utils/create_curation_task.py --folder-id syn123 --template RNASeqTemplate` |
| **Create record-based task** | `python utils/create_recordset_task.py --folder-id syn456 --recordset-name "Study_2025" --template DataLandscape` |

---

## Table of Contents

A. [Background & Architecture](#background--architecture)  
B. [Synapse Curation Integration](#synapse-curation-integration)  
  - [JSON Schema Support](#json-schema-support)     
  - [Schema Generation & Management](#schema-generation--management)
  - [Schema Limits & Validation](#schema-limits--validation)
  - [Curation Tasks](#curation-tasks)
  - [Local Testing](#local-testing)

---

## Background & Architecture

The model has gone through three evolutions:

1. **CSV Era (Original)**
Single `.csv` file compiled to `NF.jsonld` for Schematic validation.

2. **Modular CSV Era**
CSV files split into modules, still compiled to `NF.jsonld`.

3. **LinkML Era (Current)**
YAML source files using LinkML, compiled to:
  - **JSON schemas** - Synapse validation (primary)
  - **dist/NF.yaml** - Merged LinkML YAML
  - **dist/NF.ttl** - RDF/Turtle format

The rest of this guide assumes the current LinkML era.

---

## Synapse Curation Integration

A data model may be used by many downstream systems. Here we focus on Synapse, which is the primary system used for schema registration, validation, and curation workflows.

### JSON Schema Support

This section covers the Synapse behavior that matters for registration, validation, and curation.

- **Registration:** Schemas must be registered with Synapse before use.
- **Binding:** Registered schemas are bound to folders or RecordSets for validation. Child entities inherit parent bindings.

**Reference:** [Synapse JSON Schema Docs](https://help.synapse.org/docs/JSON-Schemas.3107291536.html)

#### $refs (Schema References)

Synapse supports `$refs` in a limited way:
- ✅ References to definitions **within** the same schema
- ✅ References to **other Synapse-registered** schemas
- ❌ References to non-registered schemas

Our conversion pipeline uses dereferencing for simplicity.

**Reference:** [Synapse REST API Docs](https://rest-docs.synapse.org/rest/POST/schema/type/create/async/start.html)

#### If-Then-Else (Conditional Schemas)

JSON Schema `if` / `then` / `else` is used for:
1. **Derived annotations** - Auto-populating fields from other values
2. **Dynamic validation** - Switching rules by field value, such as `dataType`

More complex conditional rules live in `rules/`.

**Example use case:** Changing `dataType` updates the allowed assay options, file formats, and required fields.

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


#### Read-only fields in Grid

In Synapse Grid, properties marked `"readOnly": true` are not editable.

Reference: [SWC-7491](https://sagebionetworks.jira.com/browse/SWC-7491?focusedCommentId=276013)

### Schema Generation & Management

#### CI/CD Workflows

**PR Validation** (`.github/workflows/main-ci.yml`)
1. Generates JSON schemas from LinkML sources
2. Validates against Synapse API (dry-run)
3. Reports results in PR comment
4. Blocks merge if validation fails

**Schema Registration**
Typically performed on versioned releases using `register-schemas.py`.

#### Development Scripts

##### gen-json-schema-class.py

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

##### register-schemas.py

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


### Schema Limits & Validation

The NF Metadata Dictionary must satisfy several Synapse limits:

- **Enum values:** 100 per annotation field
- **Row size:** 64KB per file view row
- **String lengths:** Depend on whether the target is a JSON schema or a file view

#### File View Configuration (Stricter)

File views have the stricter limit, so we use conservative column sizes:

```
STRING: 80 chars (covers 100% of enum values, max: 77 chars)
LIST: 80 chars × 40 items max
name column: 256 chars
Largest schema: ~52.7KB (PortalDataset, Superdataset)
```

**Applied in:** `utils/json_schema_entity_view.py`, `utils/create_curation_task.py`

#### JSON Schema Validation (More Permissive)

Registered JSON schemas are more permissive:
- Enum sizes: Some exceed 100 values (e.g., `CellLineModel`: 638, `Institution`: 335)
- String lengths: No strict character limits beyond what's semantically meaningful
- Used for: Data validation, dropdown generation, documentation

**Applied in:** `registered-json-schemas/*.json`

#### Validation Tool

Run:
```bash
python utils/check_schema_limits.py
```

It checks:
- **Enum sizes** against 100-value annotation limit
- **Enum string lengths** against file view column limits (80 chars)
- **Row sizes** against 64KB file view limit
- Documents current bytes used per schema

**Key distinction:** JSON schemas can be broader for validation and documentation. File views must stay within the stricter 64KB row budget.


### Curation Tasks

Synapse curation tasks support structured metadata collection with registered JSON schemas. Two task types are supported.

> [!IMPORTANT]
> Requires `synapseclient>=4.12.0` (both scripts rely on `synapseclient.extensions.curator`).
> `create_recordset_task.py` additionally requires `pandas`, which `synapseclient` does not
> pull in: `create_record_based_metadata_task()` imports it, so a bare `synapseclient` install
> fails with `ModuleNotFoundError: No module named 'pandas'`.
> ```bash
> # file-based tasks (create_curation_task.py)
> pip install 'synapseclient>=4.12.0'
>
> # record-based tasks (create_recordset_task.py)
> pip install 'synapseclient>=4.12.0' pandas
> ```

#### Wrapper vs. synapseclient

Both scripts build on top of `synapseclient`'s curation task support, but they are not
thin passthroughs to it. The table below is the actual diff, so it's clear what would be
lost if these scripts were ever replaced by direct client calls.

| What our wrapper adds | Why synapseclient doesn't cover it |
|---|---|
| Local, short template name → `schema_uri` resolution (reads `registered-json-schemas/{template}.json`) | The client takes a `schema_uri` only; wrapper allows convenient short-name reference by taking advantage of registered-json-schemas folder  |
| Enforces our team's task naming convention — `dataType` is auto-generated as `{folder_name} ({folder_id})` | The client's `curation_task_name` is used verbatim as `data_type`; it has no naming convention of its own, let alone ours |
| Pre-flight check for files that already have annotations matching the new template's fields | No equivalent — the client has no awareness of annotation state before task creation |
| `--replace` (delete the stale task and rebind the schema when switching templates on an already-configured folder) | No equivalent, this convenience was added in #875 |
| `--assignee` + a permission check (warns if the assignee lacks `READ`/`CREATE`/`UPDATE` on the folder; never grants access) | `assignee_principal_id` implies future writes by the assignee so permissions should be checked, and client doesn't do this |
| Sized `STRING`/list columns (max 80 chars / 20 items) instead of unbounded `MEDIUMTEXT` | The client's own column builder doesn't account for Synapse's 64KB file-view row limit; using it as-is would reintroduce a real production incident (PR #843, `ScRNASeqTemplate` row-size breach) |

What we *do* delegate to the client (as of `synapseclient>=4.12.0`):
- `project_id_from_entity_id()` for folder→project traversal (replaced a hand-rolled loop)
- `Folder.bind_schema()` for schema binding — it's a PUT, so rebinding just overwrites; no manual unbind step needed
- `EntityView`'s own default columns (`include_default_columns=True`) + `reorder_column()`, instead of manually constructing `id`/`name` columns (which collided with the defaults and risked corrupting `id`'s special meaning)
- `CurationTask.store()`'s built-in non-destructive upsert (merges by `project_id` + `data_type` automatically)
- `assignee_principal_id` on `CurationTask`, passed straight through

We deliberately do **not** call `synapseclient.extensions.curator.create_file_based_metadata_task()` /
`create_json_schema_entity_view()` wholesale — see the column-sizing row above.

#### File-Based Curation Tasks

**Use case:** Associate metadata with uploaded files in a folder (e.g., sequencing data, images).

**Script:** `utils/create_curation_task.py`

**What it creates:**
- EntityView (file view) with schema-derived columns
- CurationTask bound to the folder
- `dataType` (the task's display name in Synapse), enforced as `{folder_name} ({folder_id})`

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
| `--template` | Template name *or* schema URI (required) | - |
| `--instructions` | Instructions for contributors | "Please add metadata for your files" |
| `--bind-schema` / `--no-bind-schema` | Bind schema to folder | True |
| `--replace` | Delete any existing curation task for this folder and rebind the schema before creating a new one; use when switching templates | False |
| `--assignee` | Username, team name, or numeric principal ID to assign the task to; existing folder permissions are checked (not granted). Email addresses are *not* supported — Synapse does not allow principal lookup by email | None |
| `--output-format` | `json` or `github` | `json` |

**Output:** `task_id`, `fileview_id`, `data_type`, `schema_uri`, `project_id`, `assignee_principal_id`

#### Record-Based Curation Tasks

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
  --folder-id syn87654321 \
  --recordset-name "DDI_Doe_2026" \
  --template DataLandscape \
  --upsert-keys study name
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
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

**Notes:**
- **Project ID** is derived automatically from the folder.
- **Upsert keys** define record uniqueness so updates modify existing rows instead of creating duplicates. Common choices: `study`, `name`, `individualID`.


### Local Testing

#### Python unit tests

Run all pytest-based tests from the repo root:

```bash
python -m pytest tests/ -v
```

Individual test files:

| Test file | What it covers |
|---|---|
| `tests/test_schema_instances.py` | JSON instances validate correctly against registered schemas |
| `tests/test_template_datatypes.py` | Every non-abstract template class declares valid `dataType` annotations |
| `tests/test_model_system_sync.py` | Model system data is in sync |

#### JSON schema instance tests

`tests/test_schema_instances.py` discovers `test_registry*.yaml` fixtures in `tests/` and validates each listed JSON instance against its registered schema. Cases marked `expected: valid` must pass; `expected: invalid` must fail and are marked `xfail(strict=True)`.

**Adding and registering new test instances:**

1. Create a JSON file under `tests/data/<TemplateName>/` with the instance data, e.g. `tests/data/RNASeqTemplate/valid_my_case.json`.

2. Register it in an existing `tests/test_registry*.yaml` (or a new `test_registry_<topic>.yaml`) under the matching `schema:` document:

   ```yaml
   schema: RNASeqTemplate
   instances:
     - file: data/RNASeqTemplate/valid_my_case.json
       description: What this instance tests and why
       expected: valid          # or: invalid

     # For invalid cases, add a reason explaining which rule should catch it:
     - file: data/RNASeqTemplate/invalid_my_case.json
       description: What constraint this violates
       expected: invalid
       reason: Brief explanation of the expected validation error
   ```

3. Rebuild the relevant schema locally (see below), then run `pytest tests/test_schema_instances.py -v` to confirm the result matches `expected`.

#### Rebuilding schemas locally before running tests

These tests run against `registered-json-schemas/`, so rebuild after changes to `modules/`. Use the `.venv` Python environment (Python 3.10) to avoid system Python incompatibilities:

```bash
# Rebuild NF.yaml from sources first
make NF.yaml

# Rebuild a specific schema (fast, no Synapse auth needed)
PATH=".venv/bin:$PATH" .venv/bin/python utils/gen-json-schema-class.py \
  --class HumanCohortTemplate --skip-validation

# Rebuild all schemas (no Synapse auth)
PATH=".venv/bin:$PATH" .venv/bin/python utils/gen-json-schema-class.py \
  --skip-validation
```

---

## Additional Resources

- **LinkML Documentation:** https://linkml.io
- **Synapse JSON Schema Docs:** [https://help.synapse.org/docs/JSON-Schemas.3107291536.html](https://docs.synapse.org/synapse-docs/json-schemas)
- **Synapse Search Management Example:** [SYNAPSE_SEARCH.md](SYNAPSE_SEARCH.md)
