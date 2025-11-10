## Development

Data model developer-oriented information. 
While the root README gives a general overview of the repo organization and LinkML framework, this goes into history and implementation details helpful to know.

### A brief history

Initially, the source file for the data model was a single `.csv` that compiled to a JSONLD file compliant with the Sage-specific [schematic]() framework/ 
Later the `.csv` was modularized to make development easier and friendlier. 
Later still, the `.csv`s became YAML files as the framework transitioned to LinkML to get additional developer-friendly benefits and become part of a much larger ecosystem, with some custom interop to generate the main schematic-compliant JSONLD to enable using schematic validation. It was considered the best of both worlds.

Currently, the *implementation* for validation is changing so that the schematic Python package will no longer handle much of validation at all (with much of the underlying implementation using Great Expectations). Instead, it will now be handled by the Synapse platform directly, and the Synapse platform understands relatively standard JSON schemas. 

The main artifacts to provide for the downstream validation implementation is now a set of JSON schemas that covers all org-defined entities of interest. The JSONLD is still very useful in its way, since that format is easier for comparing data models *semantically*, but that is a different use case.

### Working with JSON schemas with regard to Synapse

You are developing a data model as JSON schemas with the knowledge that they will be used by Synapse. 
So there are a couple of things to keep in mind in how Synapse deals with/uses the JSON schema.

#### See also: schematic tooling in development

Schematic tooling for schema registration, binding, and creating fileviews from the schema
https://sagebionetworks.jira.com/wiki/x/QIBD-/

#### 1: Schema registration and binding

Before a schema can actually be used for validation, the schema must be registered in Synapse and then "bound" to an entity of interest. Children entities (e.g. a folder or file under another folder) inherit the same bound schema of a parent unless they have a schema bound to them, similar to local sharing settings.

#### 2: About $refs

[$refs](https://json-schema.org/understanding-json-schema/structuring#dollarref) are a standard part of the JSON schema specification that Synapse supports in a limited/specific way ([docs](https://rest-docs.synapse.org/rest/POST/schema/type/create/async/start.html)). The current conversion pipelines use a deref step for simplicity. 

> All $ref within a JSON schema must either be references to "definitions" within the schema or references other registered JSON schemas. References to non-registered schemas is not currently supported.  


#### 3: About If-then-else

The specification describes [If-Then-Else](https://json-schema.org/understanding-json-schema/reference/conditionals#ifthenelse), which in Synapse [parlance/docs](https://help.synapse.org/docs/JSON-Schemas.3107291536.html#JSONSchemas-DerivedAnnotations) is called "derived annotations". 
This means that on Synapse, the schema can help materialize an annotation value based on another value. 
In this repo, this type of definition is most often referred to as "rules" and stored separately under `rules` for now, though that may change.

**However**, thinking of this as only "derived annotations" may not fully convey what can be done with If-then-else definitions. If-then-else can also be used to apply an appropriate schema based on a value. This is better used with an "abstract" schema applied at the top-level and expected to be inherited. When the value for dataType is changed, the relevant attributes, allowable values, and validation requirements may be able to be updated instantly. This is useful because when dataType is (raw) "gene expression", the ranges for "assay", "platform", "fileFormat", etc. that are selectable and validated against are different than when dataType is "image". As well, "image" expects different attributes, where something like "libraryPrep" is irrelevant and not seen in that template.

(Note: Currently, the templates are mostly developed by assay, but they should more correctly developed for data type, so the example below is still messy and non-ideal.)

Example: 
```
{
	"$schema": "http://json-schema.org/draft-07/schema#",
	"$id": "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-data",
	"properties": {
		"dataType": {
			"enum": [
				"gene expression",
				"aligned reads",
                "image",
                "clinical data",
                "workflow report",
				...
			]
		},
	},
	"allOf": [{
		"if": {
			"properties": {
				"dataType": {
					"const": "gene expression"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-genomicsassaytemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "aligned reads"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-processedalignedreadstemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "image"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-imagingassaytemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "clinical"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-clinicaldatatemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "workflow report"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-metadata"
		}
	},
    ...
    ]
}
```

### CI/CD Workflows for Schema Management

The repository includes automated workflows that handle JSON schema validation and registration:

#### Schema Validation (PR Workflow)

During pull requests, the `main-ci` workflow automatically:

1. **Generates JSON schemas** from LinkML source files using `utils/gen-json-schema-class.py`
2. **Validates schemas** against Synapse API (dry-run validation)  
3. **Reports results** as a PR comment with detailed validation status for each schema
4. **Blocks merge** if any schemas fail validation (workflow exits with error code 1)

The validation process ensures all schemas are syntactically correct and compatible with Synapse before they're merged to main.

#### Schema Registration (Post-merge)

After successful merge to main branch, (new, updated) schemas are automatically registered via with Synapse using:

```bash
python utils/register-schemas.py
```

This script:
- Registers all validated schemas with the Synapse platform (sets `dryRun: false`)
- Generates a registration log with detailed results
- Can exclude specific schemas if needed (e.g., `--exclude Superdataset.json`)

#### Script Usage

Both utilities support command-line configuration (refer to `.github/workflows/main-ci.yaml` for expected tools and versions in environment before running). Local testing examples:

```bash
# Schema validation - all classes (used in PR workflow)
SYNAPSE_AUTH_TOKEN="$NF_SERVICE_TOKEN" python utils/gen-json-schema-class.py --schema-yaml dist/NF.yaml --output-dir registered-json-schemas

# Schema validation - single class (useful for development/testing)
SYNAPSE_AUTH_TOKEN="$NF_SERVICE_TOKEN" python utils/gen-json-schema-class.py --class DataLandscape --skip-validation

# Schema validation - single class with validation
SYNAPSE_AUTH_TOKEN="$NF_SERVICE_TOKEN" python utils/gen-json-schema-class.py --class DataLandscape

# Schema registration (used post-merge)
SYNAPSE_AUTH_TOKEN="$NF_SERVICE_TOKEN" python utils/register-schemas.py --schema-dir registered-json-schemas
```

**gen-json-schema-class.py options:**
- `--schema-yaml`: Path to LinkML YAML schema file (default: `dist/NF.yaml`)
- `--output-dir`: Output directory for JSON schemas (default: `registered-json-schemas`)
- `--class`: Generate schema for a specific class only (e.g., `DataLandscape`)
- `--skip-validation`: Skip validation step and only generate JSON schemas
- `--version`: Semantic version to include in schema URIs (e.g., `0.1.0`)
- `--log-file`: Path to validation log file (default: `schema-validation-log.md`)

**register-schemas.py options:**
- `--schema-dir`: Directory containing JSON schemas to register (default: `registered-json-schemas`)
- `--log-file`: Path to registration log file (default: `schema-registration-log.md`)
- `--exclude`: Schema files to exclude from registration (e.g., `--exclude Superdataset.json Template.json`)
- `--include`: Only register specific schema files (e.g., `--include DataLandscape.json`). Overrides `--exclude`

**Additional registration examples:**
```bash
# Register only specific schemas
SYNAPSE_AUTH_TOKEN="$NF_SERVICE_TOKEN" python utils/register-schemas.py --include DataLandscape.json PortalDataset.json

# Register all schemas except specific ones
SYNAPSE_AUTH_TOKEN="$NF_SERVICE_TOKEN" python utils/register-schemas.py --exclude Superdataset.json Template.json
```

Generated log files (`schema-validation-log.md`, `schema-registration-log.md`) are automatically excluded from version control but provide detailed audit trails of the validation and registration processes.

### Curation Task Management

The repository includes utilities for creating metadata curation tasks in Synapse. These tasks enable structured data collection using registered JSON schemas.

#### File-Based Metadata Curation

File-based curation tasks are used when metadata should be associated with uploaded files in a folder. The script automatically creates an EntityView (file view) and CurationTask.

**Script:** `utils/create_curation_task.py`

**Usage examples:**

```bash
# Create file-based curation task with schema binding (default)
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_curation_task.py \
  --folder-id syn12345678 \
  --template ImagingAssayTemplate

# Create task with custom instructions
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_curation_task.py \
  --folder-id syn12345678 \
  --template RNASeqTemplate \
  --instructions "Please upload RNA-seq data with complete metadata"

# Skip schema binding to folder
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_curation_task.py \
  --folder-id syn12345678 \
  --template BiospecimenTemplate \
  --no-bind-schema

# Use external schema URI
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_curation_task.py \
  --folder-id syn12345678 \
  --template https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/sage.schemas.v2571-nf.ChIPSeqTemplate.schema-9.14.0
```

**Options:**
- `--folder-id`: Upload folder Synapse ID (required)
- `--template`: Template name or full schema URI (required)
- `--instructions`: Instructions for data contributors (default: "Please add metadata for your files")
- `--bind-schema`: Bind JSON schema to folder (default: True)
- `--no-bind-schema`: Skip binding JSON schema to folder
- `--output-format`: Output format - `json` for testing, `github` for GitHub Actions (default: json)

**What it does:**
1. Derives project ID from folder hierarchy
2. Loads schema URI from `registered-json-schemas/` or uses provided URI
3. Optionally binds JSON schema to the folder for validation
4. Creates EntityView (file view) with columns derived from schema
5. Creates CurationTask with auto-generated dataType: `{template_base}-{folder_id}`
6. Returns task_id, fileview_id, data_type, schema_uri, and project_id

#### Record-Based Metadata Curation

Record-based curation tasks are used for structured metadata records not directly tied to individual files (e.g., dataset planning, study metadata). The script creates a RecordSet, CurationTask, and DataGrid interface.

**Script:** `utils/create_recordset_task.py`

**Usage examples:**

```bash
# Create recordset task with schema binding (default)
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_recordset_task.py \
  --project-id syn12345678 \
  --folder-id syn87654321 \
  --recordset-name "YIA_Smith_2025" \
  --template DataLandscape

# Create task with upsert keys for record uniqueness
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_recordset_task.py \
  --project-id syn12345678 \
  --folder-id syn87654321 \
  --recordset-name "DDI_Doe_2026" \
  --template DataLandscape \
  --description "Data sharing plan tracking" \
  --task-name "DataLandscape_Curation" \
  --upsert-keys study name \
  --instructions "Please complete all required metadata fields"

# Create task without explicit upsert keys (use synapseclient defaults)
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_recordset_task.py \
  --project-id syn12345678 \
  --folder-id syn87654321 \
  --recordset-name "Vu_2020" \
  --template DataLandscape

# Skip schema binding
SYNAPSE_AUTH_TOKEN="$TOKEN" python utils/create_recordset_task.py \
  --project-id syn12345678 \
  --folder-id syn87654321 \
  --recordset-name "Allaway_2025" \
  --template DataLandscape \
  --no-bind-schema
```

**Options:**
- `--project-id`: Synapse project ID (required)
- `--folder-id`: Synapse folder ID associated with RecordSet (required)
- `--recordset-name`: Name/identifier for the RecordSet (required)
- `--template`: Template name or full schema URI (required)
- `--description`: Description of the RecordSet purpose (auto-generated if not provided)
- `--task-name`: Name for the curation task (auto-generated if not provided)
- `--upsert-keys`: Field names that uniquely identify records (optional; space-separated list)
- `--instructions`: Instructions for data contributors (default: "Please add metadata records")
- `--bind-schema`: Bind JSON schema to RecordSet (default: True)
- `--no-bind-schema`: Skip binding JSON schema to RecordSet
- `--output-format`: Output format - `json` for testing, `github` for GitHub Actions (default: json)

**What it does:**
1. Loads schema URI from `registered-json-schemas/` or uses provided URI
2. Creates RecordSet with schema binding (validates records against JSON schema)
3. Creates CurationTask for the record-based workflow
4. Creates DataGrid interface for editing records in the UI
5. Returns recordset_id, task_id, data_grid_session_id, schema_uri, project_id, folder_id, and record_set_name

**Requirements:**

Both scripts require the develop branch of synapsePythonClient:

```bash
pip install git+https://github.com/Sage-Bionetworks/synapsePythonClient.git@develop
```


