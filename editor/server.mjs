#!/usr/bin/env node
/**
 * Local-only server for the NF metadata model editor.
 *
 *   cd editor && npm install && npm start
 *   open http://localhost:5174
 *
 * Reads/writes the LinkML source under ../modules. All edits land in the
 * working tree only — review them with `git diff` before committing.
 */
import express from 'express';
import { createServer } from 'http';
import { WebSocketServer } from 'ws';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';
import { existsSync, watch, mkdirSync, copyFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { exec, execFile } from 'child_process';
import { existsSync as fexists } from 'fs';
import { resolve as rpath } from 'path';
import { loadModel, buildGraph, modelSummary, readSourceFile, classifyRange, slotRanges, ROOT } from './model.mjs';
import { setScalarField, addEnumValues, createEnum, createClass, addDcaEntry, addListItem, setSlotUsage, removeEnumValue } from './patch.mjs';
import { searchOntology, getDescendants, getTerm, getParents, domainHint } from './ontology.mjs';

const KINDS = { classes: 'classes', slots: 'slots', enums: 'enums' };
function fileFor(kind, name) {
  const rel = loadModel().fileIndex[`${kind}:${name}`];
  if (!rel) throw new Error(`${kind}:${name} not found in model`);
  return rel;
}

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 5174;
app.use(express.json({ limit: '8mb' }));

// Track our own mutating API calls so the file watcher can ignore GUI-originated
// writes (those are already reflected client-side) and only auto-reflect EXTERNAL
// edits (terminal / Claude Code / IDE).
let lastApiWrite = 0;
app.use((req, res, next) => { if (req.method !== 'GET' && req.path.startsWith('/api/')) lastApiWrite = Date.now(); next(); });

const wrap = (fn) => (req, res) => Promise.resolve(fn(req, res)).catch((e) => {
  console.error(e);
  res.status(500).json({ error: e.message });
});

// ---- Model ----
app.get('/api/summary', wrap((req, res) => res.json(modelSummary(loadModel()))));

app.get('/api/graph', wrap((req, res) => {
  const model = loadModel();
  res.json({ ...buildGraph(model), summary: modelSummary(model) });
}));

app.get('/api/entity/:kind/:name', wrap((req, res) => {
  const { kind, name } = req.params;
  const model = loadModel();
  const map = { classes: model.classes, slots: model.slots, enums: model.enums }[kind];
  if (!map) return res.status(400).json({ error: `bad kind ${kind}` });
  if (!map[name]) return res.status(404).json({ error: `${kind}:${name} not found` });
  res.json({ kind, name, def: map[name], file: model.fileIndex[`${kind}:${name}`] || null });
}));

// Set a single scalar field on a slot or class (range, required, description, title, is_a, abstract).
app.patch('/api/:kind(classes|slots)/:name', wrap((req, res) => {
  const { kind, name } = req.params;
  const { field, value } = req.body || {};
  if (!field) return res.status(400).json({ error: 'missing field' });
  const rel = fileFor(kind, name);
  res.json({ ok: true, file: rel, ...setScalarField(rel, [kind, name], field, value) });
}));

// Edit a slot's contextual override (range / any_of / required) within a template.
app.post('/api/classes/:name/slot-usage', wrap((req, res) => {
  const { name } = req.params;
  const { slot, ranges, required } = req.body || {};
  if (!slot) return res.status(400).json({ error: 'missing slot' });
  const rel = fileFor('classes', name);
  setSlotUsage(rel, name, slot, { ranges: Array.isArray(ranges) ? ranges : undefined, required });
  res.json({ ok: true, file: rel });
}));

// Append a slot reference to a class's `slots:` list.
app.post('/api/classes/:name/slot', wrap((req, res) => {
  const { name } = req.params;
  const { slot } = req.body || {};
  if (!slot) return res.status(400).json({ error: 'missing slot' });
  const rel = fileFor('classes', name);
  res.json({ ok: true, file: rel, ...addListItem(rel, ['classes', name, 'slots'], slot) });
}));

// Set/insert a field (meaning, source, description) on one enum permissible value.
app.patch('/api/enums/:name/value/:value', wrap((req, res) => {
  const { name, value } = req.params;
  const { field, val } = req.body || {};
  if (!field) return res.status(400).json({ error: 'missing field' });
  const rel = fileFor('enums', name);
  const result = setScalarField(rel, ['enums', name, 'permissible_values', value], field, val);
  res.json({ ok: true, file: rel, ...result });
}));

// Remove a permissible value from an enum.
app.delete('/api/enums/:name/value/:value', wrap((req, res) => {
  const rel = fileFor('enums', req.params.name);
  res.json({ ok: true, file: rel, ...removeEnumValue(rel, req.params.name, req.params.value) });
}));

// Append permissible values to an existing enum (bulk import / manual add).
app.post('/api/enums/:name/values', wrap((req, res) => {
  const { name } = req.params;
  const { values } = req.body || {};
  if (!Array.isArray(values) || !values.length) return res.status(400).json({ error: 'missing values[]' });
  const rel = fileFor('enums', name);
  res.json({ ok: true, file: rel, ...addEnumValues(rel, name, values) });
}));

// Valid dataType annotation values (union of Data + MetadataEnum permissible values).
app.get('/api/datatypes', wrap((req, res) => {
  const m = loadModel();
  const vals = new Set();
  for (const name of ['Data', 'MetadataEnum']) {
    const pv = m.enums[name]?.permissible_values || {};
    Object.keys(pv).forEach((k) => vals.add(k));
  }
  res.json({ values: [...vals].sort() });
}));

// Create a new class / template.
app.post('/api/classes', wrap((req, res) => {
  const { name, file, def = {}, dca } = req.body || {};
  if (!name || !file) return res.status(400).json({ error: 'need name and file' });
  if (file.includes('..')) return res.status(400).json({ error: 'bad file' });
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) return res.status(400).json({ error: 'class name must be alphanumeric (PascalCase), no spaces' });
  if (loadModel().classes[name]) return res.status(409).json({ error: `class ${name} already exists` });
  const result = createClass(file, name, def);
  let dcaResult = null;
  if (dca && dca.display_name) dcaResult = addDcaEntry(dca.display_name, name, dca.type || 'file');
  res.json({ ok: true, ...result, dca: dcaResult });
}));

// Create a new enum (wholesale ontology import or manual). Caller chooses the file.
app.post('/api/enums', wrap((req, res) => {
  const { name, file, description = '', values = [] } = req.body || {};
  if (!name || !file) return res.status(400).json({ error: 'need name and file' });
  if (file.includes('..')) return res.status(400).json({ error: 'bad file' });
  if (loadModel().enums[name]) return res.status(409).json({ error: `enum ${name} already exists` });
  res.json({ ok: true, ...createEnum(file, name, { description, values }) });
}));

app.get('/api/file', wrap((req, res) => {
  const rel = req.query.path;
  if (!rel || rel.includes('..')) return res.status(400).json({ error: 'bad path' });
  res.json({ path: rel, content: readSourceFile(rel) });
}));

// Enum values that lack an ontology `meaning` mapping — the gaps to fill.
app.get('/api/gaps', wrap((req, res) => {
  const model = loadModel();
  const wanted = req.query.enum;
  const gaps = [];
  for (const [name, def] of Object.entries(model.enums)) {
    if (wanted && name !== wanted) continue;
    const pv = def.permissible_values || {};
    const missing = Object.entries(pv)
      .filter(([, v]) => !(v && v.meaning))
      .map(([value, v]) => ({ value, description: v?.description || '', hasSource: !!(v && v.source) }));
    if (missing.length) {
      gaps.push({ enum: name, file: model.fileIndex[`enums:${name}`] || null,
        total: Object.keys(pv).length, missing });
    }
  }
  gaps.sort((a, b) => b.missing.length - a.missing.length);
  res.json({ gaps });
}));

// ---- Model QC / linter (fast, model-aware; complements `linkml-lint`) ----
const OPTIONAL_DATATYPE = new Set(['AnimalIndividualTemplate', 'PortalDataset', 'PortalStudy', 'PortalPublication', 'PublicationTemplate', 'DataLandscape', 'ProtocolTemplate', 'AnalysisResultTemplate']);
const isUrl = (s) => /^https?:\/\//i.test(String(s || ''));

function runQc(model) {
  const F = [];
  const add = (severity, kind, message, opts = {}) => F.push({ severity, kind, message, ...opts });
  const validDataTypes = new Set();
  for (const n of ['Data', 'MetadataEnum']) Object.keys(model.enums[n]?.permissible_values || {}).forEach((k) => validDataTypes.add(k));

  // --- enums / permissible values ---
  const undeclaredPrefix = {}; // prefix -> count
  let urlMeaning = 0; const urlEx = [];
  let noDesc = 0;
  for (const [name, def] of Object.entries(model.enums)) {
    const pv = def.permissible_values || {};
    if (!Object.keys(pv).length) add('warn', 'empty-enum', `Enum "${name}" has no permissible values.`, { entity: name, file: model.fileIndex[`enums:${name}`] });
    for (const [val, v] of Object.entries(pv)) {
      const meaning = v && v.meaning;
      if (meaning) {
        if (isUrl(meaning)) { urlMeaning++; if (urlEx.length < 5) urlEx.push(`${name}.${val}`); }
        else if (meaning.includes(':')) { const p = meaning.split(':')[0]; if (!model.prefixes[p]) undeclaredPrefix[p] = (undeclaredPrefix[p] || 0) + 1; }
      }
      if (!(v && v.description)) noDesc++;
    }
  }
  for (const [p, n] of Object.entries(undeclaredPrefix)) add('error', 'undeclared-prefix', `CURIE prefix "${p}:" is used by ${n} value(s) but not declared in header.yaml prefixes.`, { entity: p, file: 'header.yaml' });
  if (urlMeaning) add('warn', 'url-meaning', `${urlMeaning} value(s) use a full URL in meaning: instead of a CURIE (e.g. ${urlEx.join(', ')}). Prefer a CURIE; put URLs in source:.`);
  if (noDesc) add('info', 'no-description', `${noDesc} permissible value(s) have no description.`);

  // --- slots: range targets resolve? ---
  const unknownRanges = {};
  for (const [name, def] of Object.entries(model.slots)) {
    for (const r of slotRanges(def)) if (classifyRange(r, model) === 'unknown') unknownRanges[r] = (unknownRanges[r] || []).concat(name);
  }
  for (const [r, slots] of Object.entries(unknownRanges)) add('warn', 'unknown-range', `Range "${r}" (used by ${slots.length} slot(s), e.g. ${slots.slice(0, 3).join(', ')}) is not a known enum, class, or type.`, { entity: r });

  // --- classes ---
  for (const [name, def] of Object.entries(model.classes)) {
    const file = model.fileIndex[`classes:${name}`] || '';
    for (const s of def.slots || []) if (!model.slots[s]) add('error', 'missing-slot', `Class "${name}" lists slot "${s}" which is not defined.`, { entity: name, file });
    for (const [s, ov] of Object.entries(def.slot_usage || {})) {
      for (const r of slotRanges(ov)) if (classifyRange(r, model) === 'unknown') add('warn', 'usage-range', `Class "${name}" slot_usage "${s}" range "${r}" is not a known enum/class/type.`, { entity: name, file });
    }
    if (def.is_a && !model.classes[def.is_a]) add('error', 'missing-parent', `Class "${name}" is_a "${def.is_a}" which is not defined.`, { entity: name, file });
    // template dataType requirement (mirrors tests/test_template_datatypes.py)
    if (file.startsWith('modules/Template/') && !def.abstract && !OPTIONAL_DATATYPE.has(name)) {
      const dts = def.annotations?.templateFor?.dataType;
      if (!dts || !dts.length) add('error', 'template-datatype', `Template "${name}" has no dataType annotation (tests require one).`, { entity: name, file });
      else for (const dt of dts) if (!validDataTypes.has(dt)) add('error', 'invalid-datatype', `Template "${name}" dataType "${dt}" is not a valid Data/Metadata value.`, { entity: name, file });
    }
  }

  const counts = { error: F.filter((f) => f.severity === 'error').length, warn: F.filter((f) => f.severity === 'warn').length, info: F.filter((f) => f.severity === 'info').length };
  return { findings: F, counts };
}
app.get('/api/qc', wrap((req, res) => res.json(runQc(loadModel()))));

// ---- Ontology (OLS4) ----
app.get('/api/ontology/search', wrap(async (req, res) => {
  const { q, ontology = '', rows, exact, branches } = req.query;
  if (!q) return res.status(400).json({ error: 'missing q' });
  res.json({ results: await searchOntology({ q, ontology, rows: Number(rows) || 12, exact: exact === 'true', branchesOnly: branches === 'true' }) });
}));

app.get('/api/ontology/descendants', wrap(async (req, res) => {
  const { ontology, iri, direct, size } = req.query;
  if (!ontology || !iri) return res.status(400).json({ error: 'need ontology and iri' });
  res.json({ terms: await getDescendants({ ontology, iri, direct: direct === 'true', size: Number(size) || 200 }) });
}));

app.get('/api/ontology/term', wrap(async (req, res) => {
  const { ontology, iri } = req.query;
  if (!ontology || !iri) return res.status(400).json({ error: 'need ontology and iri' });
  res.json({ term: await getTerm({ ontology, iri }) });
}));

app.get('/api/ontology/parents', wrap(async (req, res) => {
  const { ontology, iri } = req.query;
  if (!ontology || !iri) return res.status(400).json({ error: 'need ontology and iri' });
  res.json({ parents: await getParents({ ontology, iri }) });
}));

// Domain hint for an enum (which ontologies to scope a search to).
app.get('/api/enum-hint', wrap((req, res) => res.json(domainHint(req.query.enum || ''))));

// ---- Prefixes (header.yaml) — for CURIE guardrails ----
app.get('/api/prefixes', wrap((req, res) => res.json({ prefixes: loadModel().prefixes || {} })));
app.post('/api/prefixes', wrap((req, res) => {
  const { prefix, uri } = req.body || {};
  if (!prefix || !uri) return res.status(400).json({ error: 'need prefix and uri' });
  if (loadModel().prefixes?.[prefix]) return res.json({ ok: true, existed: true });
  setScalarField('header.yaml', ['prefixes'], prefix, uri);
  res.json({ ok: true, file: 'header.yaml' });
}));

// ---- Add a slot to many templates at once ----
app.post('/api/classes/slot-bulk', wrap((req, res) => {
  const { slot, classes } = req.body || {};
  if (!slot || !Array.isArray(classes) || !classes.length) return res.status(400).json({ error: 'need slot and classes[]' });
  const results = classes.map((name) => {
    try { const rel = fileFor('classes', name); return { class: name, file: rel, ...addListItem(rel, ['classes', name, 'slots'], slot) }; }
    catch (e) { return { class: name, error: e.message }; }
  });
  res.json({ ok: true, results });
}));

// ---- Working-tree changes (modules + header) ----
app.get('/api/changes', wrap((req, res) => {
  exec('git status --porcelain -- modules header.yaml', { cwd: ROOT }, (err, stdout) => {
    if (err) return res.json({ files: [], error: err.message });
    const files = stdout.split('\n').filter(Boolean).map((l) => ({ status: l.slice(0, 2).trim(), path: l.slice(3) }));
    res.json({ files });
  });
}));

// ---- Terminal availability (for the drawer banner) ----
app.get('/api/terminal', (req, res) => res.json({ available: !!pty }));

// ---- Live file-watch: SSE that pushes when EXTERNAL edits touch the source ----
const watchers = new Set();
app.get('/api/watch', (req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
  res.write(': connected\n\n');
  watchers.add(res);
  const ping = setInterval(() => { try { res.write(': ping\n\n'); } catch {} }, 25000);
  req.on('close', () => { clearInterval(ping); watchers.delete(res); });
});

// ---- Create a PR from the current MODEL changes (isolated worktree off base) ----
const MODEL_PATHS = ['modules', 'header.yaml', 'dca-template-config.json'];
// NB: do not trim stdout — `git status --porcelain` lines have a significant leading space.
const run = (cmd, args, opts = {}) => new Promise((resolveP, reject) =>
  execFile(cmd, args, { cwd: ROOT, maxBuffer: 32 * 1024 * 1024, ...opts },
    (e, so, se) => (e ? reject(new Error((se || '').trim() || e.message)) : resolveP(so || ''))));

app.post('/api/pr', wrap(async (req, res) => {
  const title = (req.body?.title || '').trim();
  const body = String(req.body?.body || '');
  const base = (req.body?.base || 'main').replace(/[^\w./-]/g, '');
  const branch = (req.body?.branch || '').trim().replace(/\s+/g, '-').replace(/[^\w./-]/g, '');
  if (!title) return res.status(400).json({ error: 'title is required' });
  if (!branch) return res.status(400).json({ error: 'branch is required' });

  const status = await run('git', ['status', '--porcelain', '--', ...MODEL_PATHS]);
  const lines = status.split('\n').filter(Boolean);
  if (!lines.length) return res.status(400).json({ error: 'No model changes to submit.' });

  const wt = rpath(tmpdir(), `nf-pr-${Date.now()}`);
  try {
    await run('git', ['fetch', 'origin', base]).catch(() => {});      // best-effort, ok if offline
    await run('git', ['worktree', 'add', '-b', branch, wt, `origin/${base}`]);
    for (const l of lines) {                                          // mirror each model change into the worktree
      const xy = l.slice(0, 2); const p = l.slice(3);
      const dst = rpath(wt, p);
      if (xy.includes('D')) { try { rmSync(dst); } catch {} }
      else { mkdirSync(dirname(dst), { recursive: true }); copyFileSync(rpath(ROOT, p), dst); }
    }
    await run('git', ['-C', wt, 'add', '-A', '--', ...MODEL_PATHS]);
    await run('git', ['-C', wt, 'commit', '-m', title + (body ? `\n\n${body}` : '')]);
    await run('git', ['-C', wt, 'push', '-u', 'origin', branch]);
    const out = await run('gh', ['pr', 'create', '--base', base, '--head', branch, '--title', title, '--body', body || title], { cwd: wt });
    const url = out.split('\n').map((s) => s.trim()).filter(Boolean).filter((s) => s.startsWith('http')).pop() || out.trim();
    res.json({ ok: true, url, branch, files: lines.length });
  } catch (e) {
    res.status(500).json({ error: e.message });
  } finally {
    try { await run('git', ['worktree', 'remove', '--force', wt]); } catch {}
    try { rmSync(wt, { recursive: true, force: true }); } catch {}
  }
}));

// ---- GitHub issues (via gh, repo inferred from the git remote) ----
app.get('/api/issues', wrap((req, res) => {
  const state = ['open', 'closed', 'all'].includes(req.query.state) ? req.query.state : 'open';
  const args = ['issue', 'list', '--state', state, '--limit', '200', '--json', 'number,title,labels,state,url,updatedAt'];
  if (req.query.label) args.push('--label', String(req.query.label));
  execFile('gh', args, { cwd: ROOT, maxBuffer: 16 * 1024 * 1024 }, (err, stdout) => {
    if (err) return res.json({ issues: [], error: err.message });
    try { res.json({ issues: JSON.parse(stdout || '[]') }); } catch (e) { res.json({ issues: [], error: e.message }); }
  });
}));
app.get('/api/issues/:n', wrap((req, res) => {
  const n = String(req.params.n).replace(/\D/g, '');
  if (!n) return res.status(400).json({ error: 'bad issue number' });
  execFile('gh', ['issue', 'view', n, '--json', 'number,title,body,labels,state,url,author,createdAt'], { cwd: ROOT, maxBuffer: 16 * 1024 * 1024 }, (err, stdout) => {
    if (err) return res.status(500).json({ error: err.message });
    try { res.json(JSON.parse(stdout)); } catch (e) { res.status(500).json({ error: e.message }); }
  });
}));

// ---- Full branch diff vs a base (default main): committed + uncommitted + new files ----
const git = (args, cb) => exec(`git ${args}`, { cwd: ROOT, maxBuffer: 64 * 1024 * 1024 }, cb);
const safeBase = (b) => (b || 'main').replace(/[^\w./-]/g, '');
app.get('/api/diff', wrap((req, res) => {
  const base = safeBase(req.query.base);
  git(`diff --numstat ${base}`, (e1, numstat) => {
    git(`diff --name-status ${base}`, (e2, namestat) => {
      git('status --porcelain --untracked-files=all', (e3, status) => {
        const stat = {};
        (namestat || '').split('\n').filter(Boolean).forEach((l) => { const [s, ...p] = l.split('\t'); stat[p.join('\t')] = s[0]; });
        const files = (numstat || '').split('\n').filter(Boolean).map((l) => {
          const [a, d, ...p] = l.split('\t'); const path = p.join('\t');
          return { path, added: a === '-' ? null : +a, removed: d === '-' ? null : +d, status: stat[path] || 'M' };
        });
        const seen = new Set(files.map((f) => f.path));
        (status || '').split('\n').filter((l) => l.startsWith('?? ')).forEach((l) => {
          const p = l.slice(3); if (!seen.has(p)) files.push({ path: p, status: 'new', added: null, removed: null });
        });
        files.sort((a, b) => a.path.localeCompare(b.path));
        res.json({ base, files, error: e1 && !numstat ? e1.message : undefined });
      });
    });
  });
}));
app.get('/api/diff/file', wrap((req, res) => {
  const base = safeBase(req.query.base);
  const path = req.query.path;
  if (!path || path.includes('..')) return res.status(400).json({ error: 'bad path' });
  const cmd = req.query.untracked === 'true'
    ? `diff --no-index -- /dev/null ${JSON.stringify(path)}`
    : `diff ${base} -- ${JSON.stringify(path)}`;
  git(cmd, (err, out) => res.json({ path, patch: out || '' })); // no-index exits 1 with a patch; ignore err
}));

// ---- One-click build / validate ----
function pythonBin() {
  const venv = rpath(ROOT, '.venv', 'bin', 'python');
  return fexists(venv) ? venv : 'python3';
}
const TASKS = {
  ttl: { label: 'Build TTL', cmd: () => 'make NF.ttl' },
  schemas: { label: 'Generate JSON schemas', cmd: () => `${pythonBin()} utils/gen-json-schema-class.py --skip-validation` },
  limits: { label: 'Check schema limits', cmd: () => `${pythonBin()} utils/check_schema_limits.py --strict` },
  tests: { label: 'Run tests', cmd: () => `${pythonBin()} -m pytest tests/ -q` },
  lint: { label: 'LinkML lint', cmd: () => 'linkml-lint dist/NF.yaml' },
};
app.post('/api/run/:task', wrap((req, res) => {
  const t = TASKS[req.params.task];
  if (!t) return res.status(400).json({ error: `unknown task ${req.params.task}` });
  const cmd = t.cmd();
  exec(cmd, { cwd: ROOT, timeout: 9 * 60 * 1000, maxBuffer: 32 * 1024 * 1024 }, (err, stdout, stderr) => {
    const tail = (s) => (s || '').slice(-4000);
    res.json({ task: req.params.task, label: t.label, cmd, ok: !err,
      code: err?.code ?? 0, timedOut: !!err?.killed, out: tail(stdout), err: tail(stderr) });
  });
}));

// ---- Static assets ----
app.use(express.static(resolve(__dirname, 'public')));
const vendor = (name, sub) => {
  const dir = resolve(__dirname, 'node_modules', ...sub);
  if (existsSync(dir)) app.use(`/vendor/${name}`, express.static(dir));
};
vendor('cytoscape', ['cytoscape', 'dist']);
vendor('xterm', ['@xterm', 'xterm']);            // /vendor/xterm/lib/xterm.js + /css/xterm.css
vendor('xterm-fit', ['@xterm', 'addon-fit', 'lib']);

// ---- Embedded terminal: a real PTY streamed over WebSocket (for Claude Code etc.) ----
let pty = null;
try { const m = await import('node-pty'); pty = m.spawn ? m : (m.default || null); }
catch (e) { console.warn(`[terminal] node-pty unavailable (${e.message}); terminal disabled.`); }

const server = createServer(app);
const wss = new WebSocketServer({ server, path: '/terminal' });
wss.on('connection', (ws) => {
  if (!pty) {
    ws.send('node-pty is not installed. Run `npm install` in editor/ to enable the terminal.\r\n');
    ws.close(); return;
  }
  const shell = process.env.SHELL || (process.platform === 'win32' ? 'powershell.exe' : '/bin/bash');
  let term;
  try {
    term = pty.spawn(shell, [], {
      name: 'xterm-256color', cols: 80, rows: 24, cwd: ROOT,
      env: { ...process.env, TERM: 'xterm-256color', GIT_PAGER: 'cat', PAGER: 'cat' },
    });
  } catch (e) {
    try { ws.send(`\r\nFailed to start shell (${shell}): ${e.message}\r\n`); ws.close(); } catch {}
    return;
  }
  term.onData((d) => { try { ws.send(d); } catch {} });
  term.onExit(({ exitCode }) => { try { ws.send(`\r\n[process exited (${exitCode})]\r\n`); ws.close(); } catch {} });
  ws.on('message', (raw) => {
    let msg; try { msg = JSON.parse(raw.toString()); } catch { return; }
    if (msg.type === 'input') term.write(msg.data);
    else if (msg.type === 'resize') { try { term.resize(Math.max(2, msg.cols | 0), Math.max(2, msg.rows | 0)); } catch {} }
  });
  ws.on('close', () => { try { term.kill(); } catch {} });
});

// Watch source files; push an SSE "changed" to clients on EXTERNAL edits only.
let watchTimer = null;
function notifyChanged() {
  clearTimeout(watchTimer);
  watchTimer = setTimeout(() => {
    if (Date.now() - lastApiWrite < 1500) return; // a GUI edit just happened → client already updated
    for (const res of watchers) { try { res.write('data: changed\n\n'); } catch {} }
  }, 400);
}
try {
  watch(resolve(ROOT, 'modules'), { recursive: true }, notifyChanged);
  for (const f of ['header.yaml', 'dca-template-config.json']) {
    const p = resolve(ROOT, f); if (existsSync(p)) watch(p, notifyChanged);
  }
} catch (e) { console.warn(`[watch] file watching disabled: ${e.message}`); }

server.listen(PORT, () => {
  console.log(`\n  NF metadata model editor — http://localhost:${PORT}`);
  console.log(`  Editing source under: ${ROOT}`);
  console.log(`  Terminal: ${pty ? 'enabled' : 'disabled (node-pty missing)'} · edits write to the working tree only.\n`);
});
