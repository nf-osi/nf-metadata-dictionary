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
- So is a **folder listing** lost after its retries, and so is a drill-down the circuit breaker cuts short. Both leave entities uninspected and therefore absent from `entity_findings.jsonl`, which is exactly the same gap as a failed read: reported coverage never claims more than was actually read.
- **A gap is recorded, never retired.** A run reports the coverage it lost *and* whatever an earlier run recorded in the state file it resumed from; nothing retires another run's gap, not even for a scope this run happens to re-read successfully. So a `--resume` or `--report-only` says in its coverage block that **its figure is not authoritative** and names how many project audits it carried forward. Only a full scan - or accepting the gap with `--max-unscanned` - clears a transient failure a later read recovered. That under-claims coverage, which is the honest direction: deciding which gaps a run had re-verified needed an identity for "the same operation" that kept mis-firing, and every mis-fire made a resumed run claim coverage it did not have.
- Each lost operation is a gap of its own. A folder's listing, that folder's own annotation read, the key-inventory merge `--include-project-entity` performs and a drill-down the breaker cut short are four different holes even when they name one entity, so recording one can never swallow another. Repeating the *same* lost operation is collapsed, so a recurring failure spends the `--max-unscanned` budget once.
- Every per-entity network loop - the drill-down here, the conformance loop in `validate_annotations.py`, and the planning, conformance, write, rollback and verify passes in `fix_annotation_keys.py` - is guarded by the same circuit breaker in `synapse_annotation_io.py`. A systemic failure stops the loop where it starts instead of spending the retry budget on thousands of entities, which with retries in place would turn seconds of failure into days of grinding. The breaker is sampled once per *request*, so work that issued no network call can neither trip it nor dilute it, and neither can a request the service answered definitively about one entity: a 403 on a file behind its own ACL, or a 404 on an entity deleted since the scan, is recorded as lost coverage without entering the guard's window. A 401 or a 400 is not in that set - those recur for every remaining request, so a token revoked mid-scan still stops the run.
Both kinds of request the drill-down issues are sampled - the entity annotation reads and the walk's folder listings - into one window, because the question a guard has to answer is "has Synapse stopped answering", not "how is this one endpoint doing". Sampling only the reads let a degradation confined to `POST /entity/children` hide behind the healthy reads filling the window with successes, while every listing paid the full retry backoff.
One breaker spans the whole drill-down rather than one per project: a per-project window merely made a systemic outage cost one breaker's worth of doomed reads per project, about nine hours across the 53 flagged projects on the recorded scan.
A trip is a latch.
The failure *rate* is a live trailing figure that recovers as successes push the failures out of the window, so a pass that asks "was I cut short" after the fact would otherwise be told no - and a truncated drill-down would be stamped complete.
- A pass cut short says so. The write, preflight, rollback and verify summaries each name how many entities they never attempted, because `rollback: restored=0` on its own reads as a finished pass when in fact thousands of entities are still in the state the fix left them in.
- **An abort never costs a findings file that was already complete.** A `--drill-down` writes its rows to `entity_findings.partial.jsonl` and only moves them onto `entity_findings.jsonl` when the pass ran to completion.
Since the breaker spans the run, an abort skips every remaining flagged project, and rewriting the real path in place would replace a complete file with a subset of itself - a curator re-running during a transient degradation would then repair part of the work believing it was all of it.
Completion is the positive signal each project reports, not the absence of skipped ones: the pre-project check only names projects the pass never started, so an abort *inside* the last - or only - flagged project used to leave that list empty and promote a truncated file with `complete: true` on it.
The documented single-project drill-down hits exactly that case.
Either way an `entity_findings.manifest.json` beside the file records whether the coverage is whole (`complete`) and whether the pass itself ran end to end (`pass_completed`), how many entities it holds, which projects it inspected, which it never reached, which it cut short part-way, and how many coverage gaps it recorded - in total and per project.
`complete` means the drill-down covered everything it set out to cover, so **any recorded coverage gap makes the file incomplete**, not only an abort: an entity whose read was lost after its retries is missing from `entity_findings.jsonl` exactly as if the pass had never reached it.
A pass that finished still replaces the previous findings file - it covered every flagged project and is the more current of the two - and its manifest is what says the coverage is short.
`fix_annotation_keys.py --findings` reads that manifest and **refuses an `--apply` run** over an incomplete file, unless `--allow-incomplete-findings` accepts the gap; a dry run proceeds, records the gap in `report.csv` and `progress.jsonl`, and exits 2.

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
Regeneration therefore **carries each generated entry's expiry forward verbatim**: the command above cannot renew the baseline, only `--baseline-expires` moves a deadline, and drift found since the last regeneration is dated a quarter out from the day it first appears.

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
6. **Every per-entity loop aborts on a systemic failure**, and they all abort through the same guard: the preflight's planning pass, its conformance pass, the write pass, the rollback and verify passes, and the audit's drill-down.
   The guard lives in `synapse_annotation_io.py` beside the retry policy, as one implementation rather than a copy per loop, because a guard added to one loop and forgotten on its sibling is how this went wrong repeatedly.
   A degraded service stops the run where it starts rather than at entity 5,000, and the trailing window is judged from a floor of 10 results so a 30-entity run driven by hand is guarded too.
   The window holds one sample per *request*, never one per iteration: an entity with nothing to change issues no call, so it can neither trip the guard nor dilute it.
   Nor does a request the service answered definitively about one entity - a 403 on a file behind a per-folder ACL, a 404 or 410 on an entity deleted since the audit - which is recorded as lost coverage and left out of the window.
   Those are facts about individual entities, and sampling them made the guard fire on the data: with a floor of 10 and a threshold of 10%, two 403s in one window aborted a whole pass, deterministically, leaving no way forward but pruning the input by hand.
   That exemption is exactly those statuses and not "anything the retry policy will not retry", which swept in the two failures a run cannot survive: a 401 is a fact about the credential rather than about an entity, and a 400 says the tool is building a request the service will keep rejecting.
   Both recur on every remaining call, so **a revoked token or a systematically malformed request still stops the run where it starts** - within ten requests, since every request then fails.
   Nothing is hidden by the exemption either - a definitive failure is still an error in the report and still spends the coverage budget - and a write run with no access at all is refused up front by the permission check rather than by the guard.
   That distinction matters because retries make an unguarded loop worse - each entity of a doomed run pays the full backoff before failing, which turns seconds into days.
7. **An aborted pass never reads as a finished one.** A cut-short write pass logs the entities it attempted against the size of the plan and writes a `not_attempted` row per entity it never reached, so `report.csv` cannot be mistaken for a complete run over a smaller plan; the preflight likewise reports every entity left without a verdict rather than only the ones it reached and failed on.

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
`--allow-unvalidatable` accepts that gap deliberately, and `--allow-incomplete-findings` is its counterpart for a findings file that covers only part of the audit.
Run standalone, the conformance loop is guarded like every other per-entity loop: a systemic failure stops it, the markdown report says how many entities were never checked, and it exits 1 rather than presenting a truncated pass as a verdict on the whole plan.
A truncated pass also stops claiming "None. The planned fix does not break conformance anywhere." - the sentence an operator quotes when deciding to run `--apply`, and one the unchecked entities cannot support - and its `--report` CSV carries a `not_checked` row per entity it never reached, so neither artifact can be mistaken for a full pass.
`still_invalid` does not block, but it is reported separately rather than counted among the entities the preflight vouched for: the plan is proven only for `clean` and `repaired`.

Two reads decide which schema an entity is judged against, and both are read off the response status rather than off the message: a missing binding is a 404 on `/entity/{id}/schema/binding`, not the string `404` appearing anywhere in the error - which also matched a 5xx on an entity whose own synID contains those digits, and then validated it against whatever its `Component` annotation named instead.
`--include-cached` gets the same retry budget and the same guard as those two, and a lost read of Synapse's stored verdict is reported in the `synapse_cached_error` column rather than leaving the same blank cell as "Synapse holds no verdict for this entity": the two mean opposite things when triaging.

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