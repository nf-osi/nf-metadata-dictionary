# NF Metadata Model Editor (local tool)

A **local-only** visual editor for the NF metadata model, plus tools for pulling
values/attributes in from ontologies and finding the gaps where you should.

It reads and writes the LinkML source under [`../modules`](../modules) directly.
Three things it's built to make easier:

1. **See the whole model and how it's linked** — an interactive graph of
   classes (templates) ↔ slots (attributes) ↔ enums (value sets), with the
   `is_a`, `uses`, `range`, and `slot_usage` relationships drawn as edges.
2. **Edit it** — click a node and edit it in a form. Changes are written back to
   the *correct* source `.yaml` file with **surgical, minimal diffs** (only the
   lines you changed — no whole-file reformatting).
3. **Import ontologies / fill gaps** — search EBI OLS, pull a term's descendants
   in wholesale as a new (or appended) enum, and find every enum value missing a
   `meaning:` mapping with one-click ontology suggestions.

> ⚠️ All edits land in your **working tree only**. Nothing is committed or pushed.
> Review everything with `git diff` before committing. Generated artifacts
> (`registered-json-schemas/`, `dist/`, `NF.jsonld`) are **never** touched — only `modules/` and `header.yaml`.

## The fast path: "Add term"

The most common task in this repo (by far) is **adding a controlled-vocabulary value
and mapping it to an ontology**. The **+ Add term** button (top-right, or press <kbd>A</kbd>,
or the assisted button inside any enum / on the Gaps tab) makes that one short flow:

1. Pick the value set (enum).
2. Type the term — it **live-searches the right ontologies** for that enum
   (tumors → MONDO/NCIT, species → NCBITaxon, file formats → EDAM, anatomy → UBERON/BTO…).
3. Click a match. The value, `meaning:` (CURIE), `source:` (IRI), `description:`, and
   candidate `aliases:` are **filled in for you** — no manual CURIE typing.
4. **Add term.** It writes a minimal, repo-style diff and stays open so you can add another.

No ontology match? One click uses your text as-is (free-text value). **Guardrails** keep
`meaning:` a valid CURIE and, if a CURIE's prefix isn't declared in `header.yaml` yet
(e.g. `rrid:`), it's added automatically with the right URI.

### Terminal (Claude Code in a drawer)
The **Terminal** button (top-right) opens a real shell at the repo root in a
resizable bottom drawer. Run **`claude`** (Claude Code) or any CLI there for bulk
or out-of-scope edits the GUI doesn't cover. Edits are reflected in the app two ways:
- **Automatically** — the server watches `modules/`, `header.yaml`, and
  `dca-template-config.json` and pushes a live update (via SSE) whenever an
  *external* edit lands (terminal / Claude Code / your IDE). The graph, sidebar,
  stats, and Changes tab refresh themselves — no reload. (Your own in-app edits
  are filtered out so they don't double-refresh.)
- **Manually** — the **↻ Reflect changes** button re-reads the model on demand.

Powered by a PTY (`node-pty`) over a localhost WebSocket; the shell runs with your
environment, so `claude` and your tools resolve normally. If `node-pty` isn't built,
the drawer shows a "run `npm install`" notice instead of failing.

Other low-friction helpers:
- **New class / template** — the **＋ Class** button (graph sidebar) creates a class:
  pick a parent (`is_a`) to inherit from, slots to include, and — for a concrete
  template — its `dataType`/granularity/usage annotations (the build/tests require a
  `dataType`). Optionally registers it in `dca-template-config.json` in the same step.
- **Add a slot to many templates at once** — from a slot's inspector, tick the templates
  and apply in one step (avoids the "missed a sibling template" class of bugs).
- **Check model (QC)** — the bottom toolbar's **Check model** runs fast, model-aware
  checks and lists findings by severity (click one to open it in the graph):
  CURIE prefixes used but not declared in `header.yaml`, URLs sitting in `meaning:`
  instead of `source:`, undefined slot/range/parent references, concrete templates
  missing a valid `dataType`, empty enums, and values with no description. The
  **LinkML lint** build button runs the official `linkml-lint` when it's installed.
- **Build / validate toolbar** (bottom): one-click **Rebuild model** (`make NF.ttl`),
  **Generate schemas**, **Check limits** (`check_schema_limits.py`), **Run tests** (pytest) —
  plus a live "N changed files" indicator. (These shell out to your local toolchain; failures
  show the command output.)

## Run it

```bash
cd editor
npm install      # express, js-yaml, cytoscape (served locally — no CDN)
npm start        # http://localhost:5174
```

Then open http://localhost:5174. (Set `PORT=xxxx` to change the port.)

A **guided tutorial** runs automatically on your first visit and walks through all
three tabs. Replay it anytime from the **Tutorial** button in the top-right
(arrow keys / Esc work too).

Ontology lookups call the public [EBI OLS4](https://www.ebi.ac.uk/ols4/) API, so
the import/gap features need an internet connection. Everything else is offline.

## The three tabs

### Graph Editor
Shows **one scope at a time**, laid out as a hierarchy (not a force-network):
- **Whole model** (default) — the class `is_a` hierarchy. Click **⌂ Whole model** to return here.
- **A subset** — click an entity in the sidebar (or **Focus a module…**) to focus
  it: the entity with its slots, value sets, parents and children. **Double-click**
  any node to re-center the scope on it. Drag to pan, scroll to zoom.
  Colors: 🔵 class · 🟢 slot · 🟠 enum (dashed border = abstract class).
- Select a node to **edit it** in the right panel:
  - **Slot** — title, range, required, description; add the slot to many templates at once.
  - **Class** — description; view/add slots.
  - **Enum** — every permissible value with its mapping status; **+ Add term**;
    **Find mapping** searches OLS and writes the chosen CURIE to `meaning:`.

### Ontology Gaps (coverage)
The real gap is usually a **missing permissible value**, not just an unmapped one.
Pick a value set, **search for a branch** in an ontology (root candidates that are
leaves — nothing to pull under them — are hidden), and the tool diffs the branch
against your enum and lists the **terms you're missing**. Select them and add all
at once (with `meaning:`/`source:`/`description:` filled in). A secondary section
lists existing values lacking a `meaning:` mapping, with one-click **Find mapping**.
Search can be **filtered to specific ontologies** (e.g. `mondo,ncit`, prefilled per
value-set domain) and toggled to **exact** match.

### Import Ontology
1. Search a **root term** (optionally scope to an ontology like `ncit`, `uberon`).
2. Pick **direct children** or **all descendants**; check the ones you want.
3. Send them to a **new enum** (you choose name + target file) or **append** to an
   existing enum. Each imported value gets `meaning:` (CURIE) and `source:` (IRI).

After importing a **new** enum, run `make NF.ttl` and restart the server for it to
appear in the graph (existing-enum edits show up on the next page load).

## Shareable links
- `?focus=enum::Tumor` (or a bare name) — open the graph focused on that subset.
- `#gaps`, `#import` — open a specific tab. `?gap=Tumor#gaps` opens a value set's coverage.
- `?tour=off` — suppress the first-run tutorial (handy for demos/screenshots).

## How it works
| File | Role |
|------|------|
| `server.mjs` | Express app + JSON API |
| `model.mjs` | Merges `header.yaml` + `modules/**/*.yaml` (like the Makefile), indexes each class/slot/enum to its source file, builds the graph |
| `patch.mjs` | Line-based, indentation-aware YAML patching — minimal diffs, repo-matching quote style |
| `ontology.mjs` | EBI OLS4 client (search / descendants / term) |
| `public/` | Vanilla-JS front end (Cytoscape graph, edit forms, ontology tools) |

No build step; no framework. `git diff` is your safety net.
