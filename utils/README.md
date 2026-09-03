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

# record a completed scan's findings as the accepted baseline, no network calls
python utils/audit_annotation_keys.py --state audit/state.jsonl \
    --emit-allowlist utils/annotation_key_allowlist.yaml
```

Three things to know when reading a report:

- The inventory reports **presence, not scale**. One bad file out of 6,000 looks identical to wholesale corruption. `syn25881328` flags 19 duplicate keys at the project level but only 23 of its 772 files are actually affected. Always `--drill-down` before judging scale.
- A 403 is a **finding, not a skip**. Coverage (`scanned / not readable / failed`) is reported first, because "0 findings" is meaningless without it.
- An entity read lost during `--drill-down`, after its retries, is also a finding. It is counted in the coverage block, listed in `summary.md`, carried in `annotation_key_audit_projects.csv` and spends the `--max-unscanned` budget. `entity_findings.jsonl` is the only input `fix_annotation_keys.py --findings` reads, so an entity silently missing from it is a real finding that could never be repaired.

The markdown tables in `summary.md` that grow with the data - the per-key frequency tables and the per-(project, key) value-type table - are capped at 40 rows, because the weekly workflow pipes the file into a GitHub issue body, which is limited to 65,536 characters.
The list of affected projects is deliberately uncapped: it is the one actionable list in the issue, and a curator should not have to download a CI artifact to learn which project to look at.
The CSVs in the run artifact always hold every row.

Exit codes follow `check_schema_limits.py`: `0` clean, `1` repairable findings (with `--fail-on-findings`), `2` warnings.
Unrecognised keys do not warn by default - projects legitimately carry custom annotations - but probable misspellings of a schema slot do, since those are real bugs.
The weekly workflow fails the job on both `1` and `2`, with different messages: a warning annotation on a green job is what gets ignored, and lost coverage has to be as visible as drift.
Accepting a key in `annotation_key_allowlist.yaml` or raising `--max-unscanned` is how a triaged run goes green again.

`--include-project-entity` folds the project entity's own annotation keys into the inventory - a view scope cannot see them - and makes `--drill-down` inspect the project entity too, so a project-level finding is reachable by `fix_annotation_keys.py --findings` rather than visible but unfixable.

#### The allowlist baseline

`annotation_key_allowlist.yaml` ships with the **recorded pre-remediation baseline**: every finding present on the 368 portal projects at the time this tooling landed, before any Synapse writes. Without it the weekly job would be red from the first scheduled run and stay red until the drift is remediated out of band, and a permanently red gate gets ignored - so the baseline is what lets *new* drift be the thing that turns the job red.

The baseline entries are **generated, not hand-written**, and each one is marked `generated: true`. Regenerate them from any completed scan's state file, which needs no Synapse credentials:

```bash
python utils/audit_annotation_keys.py --state audit/state.jsonl \
    --emit-allowlist utils/annotation_key_allowlist.yaml
```

Regeneration **merges**: it replaces the generated block and preserves every entry without `generated: true`, collecting them in a labelled block at the end of the file. So a hand-triaged acceptance survives a regeneration, and the two kinds of entry stay distinguishable. Add yours without that field; where a hand-added entry covers the same key, scope and classification as a generated one, the hand-added entry stands. A file that cannot be parsed is refused rather than overwritten, since the entries at risk are the ones nothing else records.

Each entry is scoped to its project synID rather than `global`, so the same key on a project the baseline does not name is still a finding. Every entry carries the classification bucket, the issue it is triaged under (#939 for PascalCase duplicates, orphans and probable misspellings; #976 for case-variant drift from former slot names) and an expiry a quarter out.

**The file is meant to shrink, not to be renewed.** Every entry is drift that still exists in Synapse; each remediation pass should delete the entries it fixed. When the expiry passes the findings resurface and the job goes red, which is the reminder that the remediation never happened.

**Related files:**
- `annotation_key_allowlist.yaml` - the generated pre-remediation baseline plus any hand-triaged acceptances; affects the exit code only, never the report
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

1. **Dry run is the default**, and `--apply` alone is not enough - `--actions` has no default and must name each destructive action, so nothing is dropped or renamed that was not asked for by name.
2. **The backup is written and fsynced before the mutation**, so a kill mid-write still leaves a recoverable record. It stores the `/annotations2` payload including declared value types, so a rollback reproduces the original exactly rather than re-inferring types.
3. **Decisions are recomputed from a fresh read at write time**, never from the scan. If a value changed in between, the verdict flips to a reported conflict instead of a silent delete.
4. **Values are never re-serialised**, types and original wire strings included - not for a key the run did not name, and not for one it only moved.
   Decoding is lossy in the textual direction - a DOUBLE stored as `"1.50"` decodes to `1.5` and would re-serialise as `"1.5"`, `"1e6"` as `"1000000.0"` - and `--verify` compares decoded values, so it could never catch that.
   Re-emitting the strings Synapse served is what makes "nothing else changed" true byte for byte rather than only semantically, and what makes a rename a move rather than a rewrite.
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

A plan that cannot be checked is not a plan that passed: when used as `--validate-schema`, three cases refuse an `--apply` run just as a `regression` does - an entity that could not be read, one bound to a template this checkout does not have, and one with neither a schema binding nor a `Component` annotation, since there is then nothing to validate it against.
An unreadable entity means unreadable after `--max-retries` attempts, so a rate limit or a 503 costs a pause rather than the whole run; a 403 is never retried.
A dry run does not refuse - nothing is being mutated, and `report.csv` is what a curator triages the unvalidatable entity from - it names them, writes the report, and exits 2 to say the plan is not one `--apply` would accept.
`--allow-unvalidatable` accepts that gap deliberately.
`still_invalid` does not block, but it is reported separately rather than counted among the entities the preflight vouched for: the plan is proven only for `clean` and `repaired`.

The gate sees every entity the run would touch, not just the ones a plan could be built for, and it reconciles its own buckets before reporting: each entity has to land in exactly one of proven, unvalidatable, blocked, or nothing-to-change, and a mismatch refuses the run rather than shrinking the denominator.
That is what stops an entity whose read failed during plan construction from bypassing the gate and being mutated by the write pass with no verdict behind it.

Three things this gets right that a naive implementation does not:

- **It validates `GET /entity/{id}/json`, not a dict rebuilt from annotations.** Synapse's JSON presentation is schema-driven, not uniform: on `syn64420376` it renders `age` as the scalar `1.5` but `individualID` as the array `['1119']`, both single-value annotations. Rebuilding by flattening single-item lists produces spurious `is not of type 'array'` failures. Only the entity JSON endpoint matches what Synapse actually validates.
- **It predicts a renamed value in the shape Synapse will render it**, wrapping it when the target property is declared `array` and unwrapping a single value when it is not. `individualID` is declared `array` in 41 of the 42 registered schemas that declare it at all, so moving the value verbatim reported regressions that cannot happen - and one blocker aborts the whole rename pass. Note that `apply_key_changes` and `annotation_key_policy.apply_decisions` operate on different shapes on purpose: the latter on the annotations dict, where every value is a list, the former on the entity JSON, where the bound schema decides.
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