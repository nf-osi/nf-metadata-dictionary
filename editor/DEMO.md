# Demo script — NF Metadata Model Editor

A ~4‑minute screen recording that shows a teammate what the tool is and why it's
useful. There's also a ~75‑second teaser cut at the bottom. Voiceover lines are
suggestions — say them in your own words.

---

## Before you record

```bash
cd editor && npm install      # first time only (builds node-pty)
npm start                     # serves http://localhost:5174
```

- **Start clean** so demo edits stand out in the *Changes* tab:
  `git status` should be clean under `modules/`. (Revert any test edits first.)
- Open **http://localhost:5174/?tour=off** — the `?tour=off` skips the first‑run
  tutorial so it doesn't pop while you talk. (You can show the tutorial on purpose
  later; see the optional beat.)
- Browser at ~1440×900, zoom 100%, hide bookmarks bar. Light room, dark‑on‑light UI.
- Have a terminal mental note: you'll run **`claude`** in the in‑app drawer. If
  Claude Code isn't set up on this machine, use the fallback edit in Scene 6.
- Optional: clear the model's font cache by loading the page once before recording
  so webfonts (Fraunces/Plex) are already cached and render crisply.

## Reset between takes

```bash
git checkout -- modules header.yaml dca-template-config.json
```

(Every edit the tool makes lands in the working tree only — nothing is committed —
so a single `git checkout` resets you to a clean slate.)

---

## The 4‑minute walkthrough

| ⏱ | Do | Say |
|---|----|-----|
| 0:00 | Land on **Graph Editor** (whole‑model view). | "This is a local visual editor for our LinkML metadata model — the same `modules/*.yaml` we hand‑edit today, but you can see and change it directly." |
| 0:12 | Point at the tiers; hover the header stats (62 classes · 262 slots · 121 enums · 42% mapped). | "Up front: the whole model as a hierarchy. 62 templates, 262 attributes, 121 value sets — and only ~42% of enum values are mapped to ontology terms. Hold that thought." |
| 0:25 | Type **`Sequencing`** in the sidebar search; click **BulkSequencingAssayTemplate**. | "Search anything — class, slot, or enum — and click to focus its neighborhood." |
| 0:33 | Let the subset lay out; toggle the **enum** legend pill off then on. | "Now I see exactly what this template uses: its slots, the value sets they point to, its parent. The chips up here also filter by kind." |
| 0:45 | Click a slot node; in the inspector tweak **Required** / a description. | "Click anything to edit it — range, required, description — and it writes straight back to the right source file." |
| 0:55 | Open **Add term** (top‑right). Pick enum **Tumor**. | "Here's the part that matters day‑to‑day: adding a controlled term. Pick the value set…" |
| 1:05 | Type **`Astrocytoma`**; pause on the live results. | "…type the term, and it searches the *right* ontologies for that value set — MONDO and NCIT for diseases — live." |
| 1:15 | Click the **NCIT:C60781 Astrocytoma** match → preview fills. | "Pick a match and it fills in everything: the value, the CURIE, the definition, even synonyms. No copy‑pasting accession numbers." |
| 1:25 | Click **Add term**; show the toast + bottom "1 changed file". | "One click. It wrote clean YAML to `modules/Sample/Tumor.yaml`." |
| 1:35 | Go to **Ontology Gaps**. Click **Tumor**. | "But the real question isn't 'is this value mapped' — it's 'what are we *missing*'." |
| 1:45 | In *Find missing values*, search **`Astrocytoma`**, click the **Astrocytoma** branch. | "Compare our enum to an ontology branch…" |
| 1:55 | Show "**N missing / present / in branch**"; tick a few; **Add selected**. | "…and it tells me the terms that exist in NCIT but aren't in our model yet. Select the ones we want, add them all at once — fully mapped." |
| 2:10 | Go to **Graph Editor** → **＋ Class**. Name **`NanoStringAssayTemplate`**, parent **GeneticsAssayTemplate**, add a dataType. **Create**. | "Beyond values — you can add a whole new template: pick a parent to inherit from, the required dataType, and it can even register it in the Data Curator App config." |
| 2:25 | The new class appears focused in the graph. | "And it shows up immediately — no rebuild needed." |
| 2:35 | Bottom toolbar → **Check model**. Scroll the findings. | "There's a built‑in QC pass. Notice it already caught a real issue: ontology prefixes like `rrid` used 500+ times but never declared in `header.yaml` — that breaks RDF generation." |
| 2:55 | Open the **Terminal** button (top‑right). | "For anything the GUI doesn't cover — bulk edits, refactors — there's a real terminal, right here." |
| 3:02 | In the drawer, run: `claude` then a prompt like *"add a permissible value 'Test Tumor' to the Tumor enum in modules/Sample/Tumor.yaml"*. (Fallback below.) | "I can run Claude Code against the repo for a bulk change…" |
| 3:20 | When it finishes, **don't click anything** — point at the graph/stat updating + the toast "Reflected changes from disk". | "…and the app notices the files changed and reflects it automatically. GUI for the common stuff, full terminal for the rest, one shared view." |
| 3:35 | Go to **Changes** tab (default: *model files only*). Click a file. | "Before I commit, here's everything I changed this session versus `main` — model files only, with a real diff." |
| 3:50 | End on the diff. | "Everything's a normal working‑tree edit — I review with `git diff` and commit like always. That's the tool: see the model, edit it safely, and drop to a terminal when you need to." |

---

## Optional 75‑second teaser cut

For a quick Slack clip, record just these and trim:

1. **Whole‑model graph** (3s) → focus **BulkSequencingAssayTemplate** (4s).
2. **Add term → Tumor → "Astrocytoma" → click match → Add** (15s). *This is the hero shot.*
3. **Ontology Gaps → Tumor → branch compare → "N missing" → Add selected** (15s).
4. **Check model** showing the `rrid` prefix finding (8s).
5. **Terminal**: `claude` makes an edit → graph auto‑reflects (15s).
6. **Changes** tab diff (5s).

Open line: "We hand‑edit a big LinkML model in YAML. This makes the common edits a few clicks — and keeps a terminal for everything else."

---

## Fallback for the terminal beat (no Claude Code on this machine)

Run a visible, safe edit instead and show auto‑reflect:

```bash
# in the in-app terminal, from repo root:
yq -i '.enums.Tumor.permissible_values["Demo Tumor"].description = "added from the terminal"' modules/Sample/Tumor.yaml
```

…then point at the app updating itself. (Revert after: `git checkout -- modules`.)
If `yq` isn't handy, just run `git status` to show it's a real shell at the repo root, and use the **↻ Reflect changes** button after an edit.

---

## Money shots (make sure these land)
- **Add term** filling meaning/source/description from one click.
- **Ontology Gaps** saying *"13 missing"* against a branch.
- **Check model** surfacing the undeclared‑prefix bug.
- **Auto‑reflect**: edit in the terminal, app updates with no click.

## Tips
- Pre‑pick your examples and do one dry run — the OLS searches take ~1s, so pause
  your narration for the results to appear.
- Keep the window steady; let layouts settle before talking over them.
- If the tutorial pops, that's fine — it's a feature; either narrate it briefly
  ("first‑run walkthrough") or hit Esc and continue.
- Reset with `git checkout` between takes so the *Changes* tab is always clean.
