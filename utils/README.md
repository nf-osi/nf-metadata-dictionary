# Utilities Documentation

This directory contains utilities for maintaining the NF metadata dictionary, including syncing model systems from Synapse and reviewing annotations for schema improvements.

## Overview

The modelSystemName field in the NF metadata dictionary is automatically synchronized with the authoritative data source: Synapse table `syn26450069`. This ensures that the dictionary always reflects the current set of available cell lines and animal models used in NF research.

## Scripts

### sync_model_systems.py

Main sync script that fetches model system data from Synapse and updates enum files.

**Related files:**
- `../tests/test_model_system_sync.py` - Test suite for the sync functionality
- `../.github/workflows/weekly-model-system-sync.yml` - GitHub Actions workflow for automated weekly syncing

### review_annotations.py

Analyzes file annotations from Synapse to identify free-text values that should be standardized as enum values.

**Features:**
- Queries Synapse materialized view for file annotations
- Excludes individualID field (reviewed separately in nf-research-tools-schema)
- Checks against schema enums including synonyms/aliases
- Automatically adds frequent values to YAML enum files
- Generates suggestions for portal search filters

**Related files:**
- `../.github/workflows/weekly-model-system-sync.yml` - Integrated in weekly workflow
- See [nf-research-tools-schema](https://github.com/nf-osi/nf-research-tools-schema) for tool annotation review

**individualID Exclusion:** As of 2026-02-06, only the `individualID` annotation field is excluded from this review. It is reviewed separately in the nf-research-tools-schema repository, where individualID values from file annotations (syn52702673) are analyzed and suggested as new cell lines or synonyms in the NF Research Tools Central database (syn51730943).

**All other annotation fields** (including tool-related fields like animalModelID, cellLineID, antibodyID, geneticReagentID, tumorType, tissue, organ, species, etc.) are reviewed here, provided they have enums that allow custom values.

### annotation_key_policy.py

The rules for deciding what to do about a mis-cased annotation key ([#939](https://github.com/nf-osi/nf-metadata-dictionary/issues/939)).
Pure logic with no `synapseclient` import, so every rule that governs a destructive write is unit tested offline.

Two unrelated defects leave the same concept on an entity under two keys:

- **PascalCase schematic labels.** Every attribute has a PascalCase `rdfs:label` and a camelCase `sms:displayName` - in the legacy `NF.jsonld`, `bts:Age` carries `rdfs:label: "Age"` and `sms:displayName: "age"`. A legacy schematic/DCA submission path keyed annotations off the label, so entities carry both `Age` and `age`. The stray form is exactly `canonical[:1].upper() + canonical[1:]`.
- **Case-variant drift.** Former slot names left behind by schema renames, e.g. `timePointUnit` before it became `timepointUnit`. These are not derivable from the PascalCase rule and are only found by a case-insensitive collision against the canonical set.

Canonical names come from `dist/NF.yaml` (both the top-level `slots:` and the inline `attributes:` of the five template classes that declare them).
`NF.jsonld` is legacy and no longer built; it is useful only as evidence of what the bad writer produced.

Three categories are deliberately never rewritten:

- Schematic infrastructure keys (`Id`, `Uuid`, `eTag`, `EntityId`, `entityId`). `Id` is a manifest row UUID, not a variant of the `id` slot - treating it as one produced 55 false-positive projects on the first pass.
- Canonical slots that already start uppercase (`Component`, `Filename`, `GIST`, and six more).
- Any key whose canonical target is a Synapse reserved entity field (`description`, `name`, `id`, `type`, `contentType`, and 10 more). Dropping such a stray is safe; renaming into one is not.

**Related files:**
- `../tests/test_annotation_key_policy.py` - the decision table, one test per rule

### audit_annotation_keys.py

Read-only scan for mis-cased annotation keys across NF-OSI projects. Never writes to Synapse.

Uses the async REST job `POST /column/view/scope/async`, which returns the complete annotation-key inventory for a scope **without creating an entity**.
One call per project triages all ~368 portal studies in about a minute, which is what makes a weekly audit affordable.

```bash
# triage every portal study
python utils/audit_annotation_keys.py --projects-table syn52694652 \
    --extra-project syn35221462 --out-dir audit

# resolve a flagged project down to the individual affected entities
python utils/audit_annotation_keys.py --project syn25881328 --drill-down --out-dir audit

# regenerate reports from a previous run, no network calls
python utils/audit_annotation_keys.py --out-dir audit --report-only
```

Two things to know when reading a report:

- The inventory reports **presence, not scale**. One bad file out of 6,000 looks identical to wholesale corruption. `syn25881328` flags 19 duplicate keys at the project level but only 23 of its 772 files are actually affected. Always `--drill-down` before judging scale.
- A 403 is a **finding, not a skip**. Coverage (`scanned / not readable / failed`) is reported first, because "0 findings" is meaningless without it.

Exit codes follow `check_schema_limits.py`: `0` clean, `1` repairable findings (with `--fail-on-findings`), `2` warnings.
Unrecognised keys do not warn by default - projects legitimately carry custom annotations - but probable misspellings of a schema slot do, since those are real bugs.

**Related files:**
- `annotation_key_allowlist.yaml` - findings a human has accepted; affects the exit code only, never the report
- `../.github/workflows/weekly-annotation-key-audit.yml` - the recurring audit

### fix_annotation_keys.py

Repairs what the audit finds. Consumes `entity_findings.jsonl` from `--drill-down`.

```bash
# dry run - the default; writes nothing
python utils/fix_annotation_keys.py --findings audit/entity_findings.jsonl \
    --actions drop_stray --log-dir annotation-fix-logs/dryrun

# apply the low-risk cleanup, then verify
python utils/fix_annotation_keys.py --findings audit/entity_findings.jsonl \
    --actions drop_stray --apply --verify --log-dir annotation-fix-logs/drop-1

# recover metadata hidden behind PascalCase keys, as a separate pass
python utils/fix_annotation_keys.py --findings audit/entity_findings.jsonl \
    --actions rename_stray --apply --verify --log-dir annotation-fix-logs/rename-1

# undo a run
python utils/fix_annotation_keys.py --rollback annotation-fix-logs/drop-1 --apply
```

Safety properties, in the order they matter:

1. **Dry run is the default**, and `--apply` alone is not enough - `--actions` must name each destructive action, so a rename can never happen silently alongside a drop.
2. **The backup is written and fsynced before the mutation**, so a kill mid-write still leaves a recoverable record. It stores the `/annotations2` payload including declared value types, so a rollback reproduces the original exactly rather than re-inferring types.
3. **Decisions are recomputed from a fresh read at write time**, never from the scan. If a value changed in between, the verdict flips to a reported conflict instead of a silent delete.
4. **Keys the run did not name are copied verbatim**, types included. That is what lets `--verify` assert that nothing else changed.
5. **Conflicts are never written.** Values that genuinely differ, values that match only across types, and targets that are Synapse reserved fields are all reported for a human.

Rollback has one non-obvious property worth knowing before relying on it: the backed-up etag is the *pre-write* etag and is stale the moment the fix wrote, so the restore reads the current etag first.
That means the restore has no optimistic-concurrency protection and replaces the whole dict, so an entity edited by someone else since the fix is skipped unless `--force-rollback`.

Annotations are versioned. Dropping a key from the current version does not remove it from earlier versions; "fixed" means "fixed on the current version".

**Related files:**
- `synapse_annotation_io.py` - the `/entity/{id}/annotations2` read/write layer, used instead of the `syn.get_annotations` / `syn.set_annotations` / `Annotations` trio that is deprecated for removal in synapseclient 5.0
- `validate_annotations.py` - the `--validate-schema` preflight
- `../tests/test_fix_annotation_keys.py` - write path, rollback and verification against a stub client

### validate_annotations.py

Checks whether entity annotations conform to the **current** NF JSON schemas, and whether a planned key fix would change that. Read-only.

```bash
# is the metadata on these entities clean right now?
python utils/validate_annotations.py --findings audit/entity_findings.jsonl --include-cached

# would the planned fix break conformance anywhere?
python utils/validate_annotations.py --findings audit/entity_findings.jsonl \
    --check-plan --report validation.csv
```

Also available as a gate on the fix tool, which is the recommended way to use it - it runs before the confirmation prompt, so a plan that would break validation is never offered for approval:

```bash
python utils/fix_annotation_keys.py --findings audit/entity_findings.jsonl \
    --actions drop_stray,rename_stray --validate-schema --apply --verify --log-dir ...
```

Every entity is classified into one of four transitions. Only `regression` blocks:

| Transition | Meaning |
|---|---|
| `clean` | valid before and after |
| `repaired` | invalid now, valid after the fix - what renaming an orphan is for |
| `still_invalid` | invalid either way; a pre-existing problem unrelated to key casing |
| `regression` | valid now, invalid after - **blocker** |

Two things this gets right that a naive implementation does not:

- **It validates `GET /entity/{id}/json`, not a dict rebuilt from annotations.** Synapse's JSON presentation is schema-driven, not uniform: on `syn64420376` it renders `age` as the scalar `1.5` but `individualID` as the array `['1119']`, both single-value annotations. Rebuilding by flattening single-item lists produces spurious `is not of type 'array'` failures. Only the entity JSON endpoint matches what Synapse actually validates.
- **It resolves the schema from the entity's binding**, falling back to the `Component` annotation, and reports version drift between the bound version and this checkout. Synapse's own cached `isValid` can be stale: `syn64420357` reports invalid against `microscopyassaytemplate-11.0.20` for missing `fileFormat`/`resourceType`, but its binding is 11.1.22, where a `concreteType` guard restricts those requirements to FileEntity - so the folder is valid under the schema actually bound to it. Prefer a fresh check over a stale cached one.

**Related files:**
- `../tests/test_validate_annotations.py` - the transition matrix and the real-instance conformance checks

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