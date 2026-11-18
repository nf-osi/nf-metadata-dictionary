# Docs Site

The docs site is a single-page app built from the RDF artifact (`dist/NF.ttl`). No framework — just vanilla HTML/CSS/JS with a Node.js build step.

## Local Preview

```bash
# 1. Build the TTL if you haven't already
make NF.ttl

# 2. Install deps and build data.json
cd docs
npm install
node build.mjs

# 3. Serve locally (any static server works)
npx serve .
```

Open `http://localhost:3000` and verify Templates, Vocabulary, SPARQL Explorer, and About tabs.

## How It Works

`build.mjs` parses `dist/NF.ttl` with N3.js and writes two files into `docs/`:

| Output | Contents |
|--------|----------|
| `data.json` | Templates (with type/granularity annotations), slots (with usage-slot overrides), enums |
| `NF.ttl` | Copy of the TTL for the in-browser SPARQL explorer (oxigraph WASM) |

Both are gitignored — CI regenerates them on every deploy.

## When to Rebuild

Rebuild docs after any change to:
- `modules/**` (slots, enums, templates) — rebuild TTL first with `make NF.ttl`
- `docs/build.mjs` (extraction logic)

Frontend-only changes (`index.html`, `styles.css`, `app.js`, `sparql.js`) don't need a rebuild — just refresh the browser.

## CI

The GitHub Actions workflow (`.github/workflows/publish-docs.yml`) runs on pushes/PRs to `main` that touch `modules/**`, `docs/**`, or the workflow file. It sets up Node 20 and runs `npm ci && node build.mjs`, then deploys to GitHub Pages (prod) or a PR preview.
