# Model readiness

The editor is config-driven and supports two source dialects:

- **`linkml`** (default) — one or more `*.yaml` modules + an optional `header.yaml`
  of prefixes. Full read **and** write (surgical, minimal-diff edits).
- **`schematic-csv`** — a single compiled DCA/schematic CSV (e.g. `AD.model.csv`).
  **Read-only**: the whole model loads as a graph and every ontology-gap /
  mapping tool works, but write-back to CSV isn't wired yet, so edit calls are
  blocked server-side.

Each model below was loaded through the editor's own model loader
(`loadModel()` → `buildGraph()` / `modelSummary()`). Drop the matching config in
this folder next to the model repo as `model-editor.config.json`.

| Model | Repo | Dialect | Loads | Edit | Config |
|-------|------|---------|:-----:|:----:|--------|
| NF (this repo) | `nf-osi/nf-metadata-dictionary` | linkml | ✅ 62c / 262s / 121e | ✅ | *(none — defaults)* |
| AMP-ALS | `amp-als/data-model` | linkml | ✅ 70c / 61s / 183e | ✅ | [`amp-als.config.json`](amp-als.config.json) |
| HTAN2 | `ncihtan/htan2-data-model` | linkml | ✅ 45c / 237s / 175e | ✅ | [`htan2.config.json`](htan2.config.json) |
| AD Knowledge Portal | `adknowledgeportal/data-models` | schematic-csv | ✅ 32c / 279s / 105e | 🔒 read-only | [`adknowledgeportal.config.json`](adknowledgeportal.config.json) |

*c = classes/templates, s = slots/attributes, e = enums/value sets.*

## Notes per model

**AMP-ALS** — layout mirrors NF (`header.yaml` + `modules/**/*.yaml`, uses mixins),
so only branding + NF-specific features need turning off (no `Template` dir /
`dataType` convention / DCA registry). Loads clean.

**HTAN2** — the current model lives under `modules/**/domains/*.yaml` (the
Makefile's `MODULES_DIR = modules`; `archive/` holds the old single-file layout,
which this config ignores). There's no root prefixes file, so `headerFile` is
`null`. Caveats: enums are very large (~195k permissible values across the model,
mostly NCIT term dumps) so ontology-gap diffs are heavy, and one source file
(`modules/Clinical/domains/antineoplastic_agent_enum.yaml`) has a YAML
indentation error upstream — the loader logs and skips it rather than failing.

**AD Knowledge Portal** — not LinkML: the model is the schematic/DCA CSV
`AD.model.csv` (templates via `IsTemplate`/`DependsOn`, columns via
`Parent=ManifestColumn`, enums via `Valid Values` + value-as-row `Parent`
links). The `schematic-csv` adapter (`schematic.mjs`) maps it into the same
internal shape. Almost nothing is mapped to an ontology CURIE yet (`meaning` is
empty on ~all 1,665 values), so the ontology-gap view is where this model gets
the most value. Making it editable = a CSV write-back path (next step).

## Build commands

The `build` block in each config is a best-guess starting point for that repo's
toolchain and only affects the one-click build/validate toolbar — loading,
editing, and the ontology tools don't depend on it. Adjust to match the repo.
