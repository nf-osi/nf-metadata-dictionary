# Annotation key audit fixtures

Captures from real Synapse entities, used by `tests/test_annotation_key_policy.py`,
`tests/test_validate_annotations.py` and `tests/test_fix_annotation_keys.py`.

## Why real captures rather than hand-written dicts

The annotation-key tooling depends on two behaviours that a hand-rolled fixture gets wrong:

- **Synapse's entity JSON is schema-driven, not uniform.** On `syn64420376` the same
  kind of single-value annotation renders as the scalar `1.5` under `age` but as the
  array `["1119"]` under `individualID`, because the bound schema declares one as a
  number and the other as an array. That asymmetry is what the schema preflight has to
  model: predicting the wrong shape after a rename reports regressions that cannot
  happen. `syn64420376_entity_json.json` pins it.
- **A scope query reports one column per name *and type*.** The scope-column dumps
  contain `Age` twice, as `DOUBLE` and as `STRING`, which is how the audit detects that
  the same concept is stored under conflicting value types across entities. Flattening
  the capture would erase the finding.

The fidelity is the point, so these files are kept verbatim rather than trimmed or
anonymised.

## Provenance and access level

| File | Source | Notes |
|---|---|---|
| `syn64420376_annotations.json` | `GET /entity/syn64420376/annotations2` | `accessType: Public Access` mouse study metadata, from study `syn25881328` |
| `syn64420376_entity_json.json` | `GET /entity/syn64420376/json` | same entity, Synapse's schema-driven presentation |
| `syn25881328_scope_columns.json` | `POST /column/view/scope/async` | annotation key inventory, names and column types only |
| `syn35221462_scope_columns.json` | `POST /column/view/scope/async` | annotation key inventory, names and column types only |

The `syn64420376` captures come from a public-access study, so they carry no restricted
metadata. The scope-column dumps are key names and column types with no values at all.

Generated audit output is a different matter: a run sweeps every project the credential
can read, so `audit/` and `annotation-fix-logs/` are git-ignored and must not be
committed. Adding a fixture here means confirming the source entity's access level
first.
