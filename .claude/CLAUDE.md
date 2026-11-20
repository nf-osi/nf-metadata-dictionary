# NF Metadata Dictionary: guidance for Claude

This repo is the NF metadata dictionary: a LinkML data model (`modules/`, `header.yaml`).
`dist/NF.yaml`, `NF.jsonld`, and the JSON schemas in `registered-json-schemas/` are generated from it.
Python utilities and CI live in `utils/`, `scripts/`, `tests/`, and `.github/`.

## Reviewing pull requests

Focus on problems that matter, not style.

### Your role as reviewer

When someone requests `nfosi-service` as a reviewer, you are filling the reviewer role
for a change the author considers small enough to delegate. The team's policy on what
can be delegated and what needs a human is in
[CONTRIBUTING.md, "Choosing a reviewer"](../CONTRIBUTING.md#choosing-a-reviewer). Read it.

- If the PR falls in any of the "request a real reviewer" categories there, say so near
  the top of your summary comment: name the category and recommend requesting a
  dcc-team member before merging. Still do the review; the human reviewer can use it.
- If it is a delegable change and you found nothing significant, say clearly that it
  looks ready to merge. The author relies on that statement.
- Never imply that your review substitutes for a human decision on modeling or policy
  questions.

### Duplicate terms (check carefully)

Every new term (enum `permissible_values`, class, or slot) must be checked against
the existing model. Duplicates fragment annotations and are costly to migrate later.

- Search all of `modules/` for the new term, not just the file being edited. Look for:
  - case, spelling, punctuation, and plural/singular variants
  - abbreviations and expanded forms
  - existing `aliases`
  - entries in `term_synonyms.csv`
  - any existing term with the same `meaning` (ontology CURIE)
- If you find a likely duplicate or near-duplicate, flag it with an inline comment.
  Link the existing term (file and line) and ask the author to reuse it.
  If the new term really is distinct, ask them to explain how it differs.
- New terms that are similar to existing ones need a stated justification in the
  PR description or in the term's `description`. If none is given, request one.
  Don't approve the addition on the assumption that it's fine.
- Batch additions (many terms at once) need the same check for each term,
  including duplicates within the batch itself.

### Other review focus

- LinkML correctness: broken ranges; references to undefined classes, slots, or enums;
  misplaced `permissible_values`; conflicting definitions; required or multivalued
  changes that would break existing annotations.
- Breaking changes for data contributors: enum values or slots that are renamed or
  removed without a migration path or deprecation.
- Term quality: missing or unclear descriptions; missing `meaning` mappings where
  sibling terms have them; naming that's inconsistent with neighboring terms.
- Bugs in Python, Makefile, or workflow changes.
- CI rebuilds generated artifacts on main. Don't flag a `dist/` or `NF.jsonld` that
  hasn't been regenerated, unless the PR edits those files by hand in a way that
  disagrees with the source.

Use inline comments for specific issues. Post one top-level summary comment, and say
plainly if you found nothing significant. Don't repeat issues other reviewers have
already raised.
