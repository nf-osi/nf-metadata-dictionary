// NF metadata model editor — vanilla JS front end.
/* global cytoscape */

// ---------- tiny helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props);
  for (const k of kids) n.append(k);
  return n;
};
async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${url}`);
  return data;
}
let toastTimer;
function toast(msg, type = '') {
  const t = $('#toast');
  t.textContent = msg; t.className = `toast ${type}`; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2600);
}
const KIND_OF = (id) => id.split('::')[0];
const NAME_OF = (id) => id.slice(id.indexOf('::') + 2);

// ---------- state ----------
const STATE = {
  nodes: new Map(),        // id -> node.data
  edgesByNode: new Map(),  // id -> [edge.data]
  allEdges: [],
  enumsByName: new Map(),  // name -> enum node.data (for import dropdowns)
  files: [],
  cy: null,
};
const KIND_FILTER = new Set(['class', 'slot', 'enum']); // sidebar legend toggles

// ---------- boot ----------
init().catch((e) => toast(e.message, 'err'));

// (Re)build the in-memory model indices from a /api/graph payload.
function ingestGraph(g) {
  STATE.nodes = new Map();
  STATE.edgesByNode = new Map();
  STATE.enumsByName = new Map();
  for (const n of g.nodes) {
    STATE.nodes.set(n.data.id, n.data);
    if (n.data.kind === 'enum') STATE.enumsByName.set(n.data.name, n.data);
  }
  STATE.allEdges = g.edges.map((e) => e.data);
  for (const e of STATE.allEdges) {
    for (const end of [e.source, e.target]) {
      if (!STATE.edgesByNode.has(end)) STATE.edgesByNode.set(end, []);
      STATE.edgesByNode.get(end).push(e);
    }
  }
  STATE.files = g.summary.files;
  renderStats(g.summary);
}

// Re-read the model after a structural edit so new entities appear without a reload.
async function refreshModel(focusId) {
  try {
    ingestGraph(await api('GET', '/api/graph'));
    renderSidebar();
    ['#slot-options', '#parent-options'].forEach((s) => $(s)?.remove()); // regenerate with fresh data
    if (focusId && STATE.nodes.has(focusId)) focusEntity(focusId);
    else if (!CURRENT_SCOPE || CURRENT_SCOPE === '*') showOverview();
    else if (STATE.nodes.has(CURRENT_SCOPE)) focusEntity(CURRENT_SCOPE);
    else showOverview();
  } catch (e) { toast(`Couldn't refresh model: ${e.message}`, 'err'); }
}

function applyBranding(cfg) {
  document.title = cfg.title || 'Model editor';
  const strong = document.querySelector('.brand-text strong'); if (strong && cfg.title) strong.textContent = cfg.title;
  const sub = document.querySelector('.brand-sub'); if (sub && cfg.subtitle) sub.textContent = cfg.subtitle;
  // Read-only models (e.g. schematic-csv): flag the body so edit affordances hide, and show a banner.
  document.body.classList.toggle('read-only', !!cfg.readOnly);
  if (cfg.readOnly && !document.querySelector('.ro-banner')) {
    const b = document.createElement('div');
    b.className = 'ro-banner';
    b.textContent = `Read-only — this is a ${cfg.format || ''} model. Explore the graph and find ontology gaps; editing isn't wired for this format yet.`;
    document.body.appendChild(b);
  }
}
async function init() {
  STATE.config = await api('GET', '/api/config').catch(() => ({ title: 'Model', subtitle: '', features: { dca: true, dataType: true } }));
  applyBranding(STATE.config);
  ingestGraph(await api('GET', '/api/graph'));
  await loadPrefixes();
  initTabs();
  initGraph();
  initSidebar();
  initImportPanel();
  initAddTerm();
  initBuildBar();
  initTerminal();
  applyDeepLink();
  // test/automation hook (harmless)
  window.__nf = { focus: focusEntity, overview: showOverview, ids: () => [...STATE.nodes.keys()], cy: () => STATE.cy, term: () => TERM.xt };
}

// ?focus=enum::Tumor (or a bare name) opens that subset; otherwise the whole-model overview.
function applyDeepLink() {
  const focus = new URLSearchParams(location.search).get('focus');
  let id = null;
  if (focus) {
    const token = focus.split(',')[0].trim();
    id = STATE.nodes.has(token) ? token : null;
    if (!id) for (const [nid, d] of STATE.nodes) if (d.name === token) { id = nid; break; }
  }
  if (id) focusEntity(id); else showOverview();
}

function renderStats(s) {
  const el = $('#stats');
  if (!el) return; // stats were removed from the header
  const pct = s.enumValues ? Math.round((s.mappedEnumValues / s.enumValues) * 100) : 0;
  el.innerHTML =
    `<span class="stat-pill"><b>${s.classes}</b> classes</span>` +
    `<span class="stat-pill"><b>${s.slots}</b> slots</span>` +
    `<span class="stat-pill"><b>${s.enums}</b> enums</span>` +
    `<span class="stat-pill accent"><b>${s.mappedEnumValues}/${s.enumValues}</b> mapped · ${pct}%</span>`;
}

// ---------- tabs ----------
function showView(view) {
  $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
  if (view === 'gaps') loadGaps();
  if (view === 'changes') loadDiff();
  if (view === 'issues') loadIssues();
  if (STATE.cy && view === 'graph') STATE.cy.resize();
  if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
}
function initTabs() {
  $$('.tab').forEach((btn) => btn.addEventListener('click', () => showView(btn.dataset.view)));
  const hashView = location.hash.slice(1);
  if (['graph', 'gaps', 'import'].includes(hashView)) showView(hashView);
}

// ============================================================
//  GRAPH EDITOR
// ============================================================
function initGraph() {
  STATE.cy = cytoscape({
    container: $('#cy'),
    minZoom: 0.2, maxZoom: 3,
    style: [
      { selector: 'node', style: {
        'label': 'data(label)', 'font-size': 10, 'font-weight': 600, 'color': '#fdfdfb',
        'font-family': 'IBM Plex Sans, sans-serif',
        'text-valign': 'center', 'text-halign': 'center', 'text-wrap': 'wrap', 'text-max-width': 132,
        'background-color': '#888', 'shape': 'round-rectangle',
        // Fixed dimensions (not label-based): known at add() time so Cytoscape
        // never caches visible()=false from a transient zero-size measurement.
        'width': 150, 'height': 42,
        'border-width': 1.5, 'border-color': 'rgba(24,33,28,.18)',
        'transition-property': 'border-width, border-color', 'transition-duration': '0.15s',
      } },
      { selector: 'node[kind="class"]', style: { 'background-color': '#2e4c8c' } },
      { selector: 'node[kind="slot"]', style: { 'background-color': '#2e7d6e' } },
      { selector: 'node[kind="enum"]', style: { 'background-color': '#b9791a' } },
      { selector: 'node[?abstract]', style: { 'border-style': 'dashed', 'border-color': 'rgba(253,253,251,.95)', 'border-width': 2 } },
      { selector: 'node:selected', style: { 'border-width': 3.5, 'border-color': '#9a3324' } },
      { selector: 'edge', style: {
        'width': 1.4, 'line-color': '#aab1a4', 'target-arrow-color': '#aab1a4',
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.9,
        'label': 'data(type)', 'font-size': 8, 'font-family': 'IBM Plex Mono, monospace', 'color': '#59635a',
        'text-rotation': 'autorotate', 'text-background-color': '#ebeee6', 'text-background-opacity': 0.95,
        'text-background-padding': 2, 'text-background-shape': 'round-rectangle',
      } },
      { selector: 'edge[type="is_a"]', style: { 'line-color': '#9aa193', 'line-style': 'dashed', 'target-arrow-color': '#9aa193' } },
      { selector: 'edge[type="range"]', style: { 'line-color': '#cf9e54', 'target-arrow-color': '#cf9e54' } },
      { selector: 'edge[type="usage"]', style: { 'line-color': '#b58a6f', 'line-style': 'dotted', 'target-arrow-color': '#b58a6f' } },
    ],
  });
  STATE.cy.on('tap', 'node', (e) => { selectNode(e.target.id()); });        // highlight + inspect (no relayout)
  STATE.cy.on('dbltap', 'node', (e) => { focusEntity(e.target.id()); });    // re-center the scope on this node

  $('#clear-graph').addEventListener('click', showOverview);
  $('#new-class-btn').addEventListener('click', openNewClass);
}

// The graph shows ONE scope at a time: the whole class hierarchy, or a single
// entity's subset. Layout is hierarchical (breadthfirst), never an accumulating
// force-network.
let CURRENT_SCOPE = null;

// Build the node-id set for an entity's subset.
function subsetFor(id) {
  const ids = new Set([id]);
  const d = STATE.nodes.get(id);
  for (const e of STATE.edgesByNode.get(id) || []) ids.add(e.source === id ? e.target : e.source);
  // a class also pulls in the value sets (enums) its slots range to
  if (d && d.kind === 'class') {
    for (const sid of [...ids]) {
      if (STATE.nodes.get(sid)?.kind !== 'slot') continue;
      for (const e of STATE.edgesByNode.get(sid) || []) if (e.type === 'range' && e.source === sid) ids.add(e.target);
    }
  }
  return ids;
}

// --- label-fit node sizing -------------------------------------------------
// Long names are mostly single-word PascalCase (e.g. SpatialTranscriptomicsSequencingTemplate)
// with no spaces to wrap on. We break them at camelCase boundaries so they can
// wrap, then measure the wrapped text to size each node exactly — no truncation,
// no wasted width.
const _mctx = document.createElement('canvas').getContext('2d');
function labelAtoms(label) {
  const atoms = [];
  for (const word of String(label || '').split(/\s+/).filter(Boolean)) {
    const subs = word.match(/[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+/g) || [word];
    subs.forEach((s, i) => atoms.push({ text: s, glue: i > 0 })); // glue = no space before (mid-word)
  }
  return atoms;
}
function nodeVisual(label, fontSize, maxChars) {
  _mctx.font = `600 ${fontSize}px "IBM Plex Sans", -apple-system, sans-serif`;
  const lines = []; let cur = '';
  for (const a of labelAtoms(label)) {
    const cand = cur + (cur && !a.glue ? ' ' : '') + a.text;
    if (cur && cand.length > maxChars) { lines.push(cur); cur = a.text; } else cur = cand;
  }
  if (cur) lines.push(cur);
  const maxw = Math.max(10, ...lines.map((l) => _mctx.measureText(l).width));
  return { text: lines.join('\n'), maxw, lineCount: lines.length };
}

// Replace the whole graph with a fresh set of nodes/edges, laid out as a tree.
function renderElements(nodeIds, { roots, onlyEdgeType } = {}) {
  STATE.cy.elements().remove();
  STATE.cy.add([...nodeIds].map((id) => STATE.nodes.get(id)).filter(Boolean).map((data) => ({ group: 'nodes', data })));
  const edges = STATE.allEdges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target) && (!onlyEdgeType || e.type === onlyEdgeType));
  STATE.cy.add(edges.map((data) => ({ group: 'edges', data })));
  // Scale node size + spacing to how much is on screen: roomy & readable for a
  // small focus subset, compact for the big whole-model hierarchy.
  const count = STATE.cy.nodes().length;
  const compact = count > 18;
  const fontSize = compact ? 9 : 12;
  const maxChars = compact ? 16 : 18;
  const lineH = fontSize * 1.32;
  STATE.cy.nodes().forEach((n) => {
    const v = nodeVisual(n.data('label') || n.data('name'), fontSize, maxChars);
    n.style({
      label: v.text, 'font-size': fontSize, 'text-wrap': 'wrap', 'text-max-width': Math.ceil(v.maxw + 8),
      width: Math.ceil(v.maxw * 1.06 + 24), height: Math.ceil(v.lineCount * lineH + 14),
    });
  });
  const r = roots && roots.filter((x) => nodeIds.has(x));
  // Pack tight: avoidOverlap already prevents collisions, so spacingFactor 1.0 gives
  // the smallest non-overlapping layout → fit can zoom in closer → more readable.
  STATE.cy.layout({ name: 'breadthfirst', directed: false, roots: r && r.length ? r : undefined,
    padding: 26, spacingFactor: 1.0, animate: false, fit: false, avoidOverlap: true }).run();
  STATE.cy.fit(undefined, 45);
  const z = STATE.cy.zoom();
  // never balloon a tiny view; for focus subsets keep a readable floor (pan if wider than the canvas)
  if (z > 1.5) { STATE.cy.zoom(1.5); STATE.cy.center(); }
  else if (!compact && z < 0.75) { STATE.cy.zoom(0.75); STATE.cy.center(); }
  updateGraphStatus();
}

function focusEntity(id) {
  if (!STATE.nodes.get(id)) return;
  CURRENT_SCOPE = id;
  renderElements(subsetFor(id), { roots: [id] });
  setScopeLabel(STATE.nodes.get(id));
  selectNode(id);
}

function showOverview() {
  CURRENT_SCOPE = '*';
  const classIds = new Set([...STATE.nodes.values()].filter((d) => d.kind === 'class').map((d) => d.id));
  const hasParent = new Set(STATE.allEdges.filter((e) => e.type === 'is_a').map((e) => e.source));
  const roots = [...classIds].filter((id) => !hasParent.has(id));
  renderElements(classIds, { roots, onlyEdgeType: 'is_a' });
  setScopeLabel(null);
  inspectorEmpty();
}

function setScopeLabel(d) {
  const s = $('#graph-scope'); if (!s) return;
  s.innerHTML = !d ? '<b>Whole model</b> · class hierarchy'
    : `<b>${d.name}</b> · ${d.kind} subset`;
}

function updateGraphStatus() {
  const s = $('#graph-status');
  if (s) s.textContent = `${STATE.cy.nodes().length} nodes · ${STATE.cy.edges().length} edges`;
}

// ---------- sidebar list / search ----------
function renderSidebar() {
  const list = $('#entity-list');
  if (!list) return;
  const f = ($('#entity-search')?.value || '').trim().toLowerCase();
  const items = [...STATE.nodes.values()].sort((a, b) =>
    a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind.localeCompare(b.kind));
  list.replaceChildren();
  let shown = 0;
  for (const d of items) {
    if (!KIND_FILTER.has(d.kind)) continue;
    if (f && !d.name.toLowerCase().includes(f) && !(d.label || '').toLowerCase().includes(f)) continue;
    if (++shown > 300) { list.append(el('div', { className: 'muted', style: 'padding:8px', textContent: '…refine your search' })); break; }
    const badge = d.kind === 'enum' ? `${d.mappedCount}/${d.valueCount}` :
      d.kind === 'class' ? `${d.slotCount} slots` : (d.ranges?.[0] || '');
    const item = el('div', { className: 'entity-item', title: d.name },
      el('span', { className: `dot ${d.kind}` }),
      el('span', { className: 'ename', textContent: d.label || d.name }),
      el('span', { className: 'ebadge', textContent: badge }));
    item.addEventListener('click', () => focusEntity(d.id));
    list.append(item);
  }
}
function initSidebar() {
  renderSidebar();
  $('#entity-search').addEventListener('input', renderSidebar);
  $$('#legend .lg').forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.kind;
    if (KIND_FILTER.has(k)) KIND_FILTER.delete(k); else KIND_FILTER.add(k);
    b.classList.toggle('off', !KIND_FILTER.has(k));
    b.setAttribute('aria-pressed', KIND_FILTER.has(k));
    renderSidebar();
  }));
}

// ============================================================
//  INSPECTOR (edit forms)
// ============================================================
function inspectorEmpty() { $('#inspector').replaceChildren(el('div', { className: 'inspector-empty', textContent: 'Select a node to inspect and edit it.' })); }

function selectNode(id) {
  const node = STATE.cy.getElementById(id);
  if (node.length) { STATE.cy.elements().unselect(); node.select(); }
  const d = STATE.nodes.get(id);
  if (!d) return;
  ({ class: renderClassInspector, slot: renderSlotInspector, enum: renderEnumInspector }[d.kind])(d);
}

function inspectorHead(d) {
  return el('div', {},
    el('span', { className: `insp-kind ${d.kind}`, textContent: d.kind }),
    el('div', { className: 'insp-title', textContent: d.label || d.name }),
    d.file ? el('div', { className: 'insp-file', textContent: d.file }) : '');
}

// Render the inspector with a frozen top region and a scrolling body.
function setInspector(top, body) {
  const t = el('div', { className: 'insp-top' });
  for (const n of top) if (n) t.append(n);
  const b = el('div', { className: 'insp-scroll' });
  for (const n of body) if (n) b.append(n);
  $('#inspector').replaceChildren(t, b);
}

function fieldText(label, value, onSave, { textarea = false } = {}) {
  const input = textarea ? el('textarea', { value: value || '' }) : el('input', { type: 'text', value: value ?? '' });
  const btn = el('button', { className: 'btn btn-sm', textContent: 'Save' });
  btn.addEventListener('click', () => onSave(input.value.trim(), btn));
  return el('div', { className: 'field' }, el('label', { textContent: label }), input,
    el('div', { style: 'margin-top:4px' }, btn));
}

async function patchEntity(kind, name, field, value, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    const r = await api('PATCH', `/api/${kind}/${encodeURIComponent(name)}`, { field, value });
    toast(`Saved → ${r.file}`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = 'Save'; } }
}

function renderClassInspector(d) {
  const body = el('div', {});
  body.append(fieldText('Description', d.description, (v, b) => patchEntity('classes', d.name, 'description', v, b), { textarea: true }));
  // slots list (each row: focus + ⚙ customize range/required for this template) + add
  const slotEdges = (STATE.edgesByNode.get(d.id) || []).filter((e) => e.type === 'uses' && e.source === d.id);
  const slotsWrap = el('div', { className: 'su-list' });
  slotEdges.forEach((e) => {
    const sname = NAME_OF(e.target);
    const name = el('span', { className: 'su-name', textContent: sname, title: 'focus this slot' });
    name.addEventListener('click', () => focusEntity(e.target));
    const gear = el('button', { className: 'su-gear', textContent: '⚙', title: 'customize range / required for this template' });
    gear.addEventListener('click', () => openSlotUsage(d.name, sname));
    slotsWrap.append(el('div', { className: 'su-row' }, name, gear));
  });
  const addInput = el('input', { type: 'text', placeholder: 'slot name to add…' });
  addInput.setAttribute('list', 'slot-options');
  const addBtn = el('button', { className: 'btn btn-sm', textContent: 'Add slot' });
  addBtn.addEventListener('click', async () => {
    const slot = addInput.value.trim(); if (!slot) return;
    try { const r = await api('POST', `/api/classes/${encodeURIComponent(d.name)}/slot`, { slot });
      toast(r.changed ? `Added ${slot} → ${r.file}` : `${slot} already present`, 'ok'); addInput.value = ''; refreshChanges(); await refreshModel(d.id); }
    catch (e) { toast(e.message, 'err'); }
  });
  body.append(el('div', { className: 'field' }, el('label', { textContent: `Slots (${slotEdges.length}) — ⚙ to constrain per template` }), slotsWrap,
    el('div', { className: 'field inline', style: 'margin-top:6px' }, addInput, addBtn)));
  ensureSlotDatalist();
  setInspector([inspectorHead(d)], [body]);
}

function ensureSlotDatalist() {
  if ($('#slot-options')) return;
  const dl = el('datalist', { id: 'slot-options' });
  for (const [, d] of STATE.nodes) if (d.kind === 'slot') dl.append(el('option', { value: d.name }));
  document.body.append(dl);
}
function ensureRangeDatalist() {
  if ($('#range-options')) return;
  const dl = el('datalist', { id: 'range-options' });
  for (const [, d] of STATE.nodes) if (d.kind === 'enum' || d.kind === 'class') dl.append(el('option', { value: d.name }));
  document.body.append(dl);
}

// Edit a slot's contextual override (range / any_of / required) for one template.
async function openSlotUsage(className, slot) {
  ensureRangeDatalist();
  let ov = {};
  try { const r = await api('GET', `/api/entity/classes/${encodeURIComponent(className)}`); ov = r.def?.slot_usage?.[slot] || {}; } catch {}
  const curRanges = ov.any_of ? ov.any_of.map((a) => a.range).filter(Boolean) : (ov.range ? [ov.range] : []);
  const m = openModal({ title: `Customize “${slot}”`, subtitle: `in ${className} — overrides this template only (slot_usage)`, width: '520px' });

  const ranges = chipField('add a range — enum or class…', 'range-options', curRanges);
  const rangeNote = el('p', { className: 'muted', style: 'font-size:11.5px;margin:4px 0 0', textContent: 'One range, or several for an any_of union. Leave as-is to keep the current range.' });
  const reqSel = el('select', { className: 'select' });
  [['inherit', 'Required: inherit from slot'], ['required', 'Required: yes (in this template)'], ['optional', 'Required: no (in this template)']]
    .forEach(([v, t]) => reqSel.append(el('option', { value: v, textContent: t })));
  reqSel.value = ov.required === true ? 'required' : ov.required === false ? 'optional' : 'inherit';

  m.body.append(labeledField('Range', el('div', {}, ranges.el, rangeNote)), labeledField('Required', reqSel));

  const save = el('button', { className: 'btn btn-primary', textContent: 'Save override' });
  save.addEventListener('click', async () => {
    save.disabled = true; save.textContent = 'Saving…';
    const required = reqSel.value === 'required' ? true : reqSel.value === 'optional' ? false : null;
    try {
      const r = await api('POST', `/api/classes/${encodeURIComponent(className)}/slot-usage`, { slot, ranges: [...ranges.set], required });
      toast(`Updated ${slot} in ${className} → ${r.file}`, 'ok');
      refreshChanges(); m.close();
      await refreshModel(`class::${className}`);
    } catch (e) { toast(e.message, 'err'); save.disabled = false; save.textContent = 'Save override'; }
  });
  m.foot.append(save, el('span', { className: 'muted', style: 'font-size:12px', textContent: 'writes classes › slot_usage' }),
    el('span', { style: 'flex:1' }), el('button', { className: 'btn btn-sm', textContent: 'Cancel', onclick: m.close }));
}

function renderSlotInspector(d) {
  const body = el('div', {});
  body.append(fieldText('Title (display name)', d.title, (v, b) => patchEntity('slots', d.name, 'title', v, b)));
  if ((d.ranges || []).length > 1) {
    // union range (any_of) — editing as a single scalar would corrupt it
    body.append(el('div', { className: 'field' }, el('label', { textContent: 'Range (union — edit in YAML)' }),
      el('input', { type: 'text', value: d.ranges.join(' | '), readOnly: true, style: 'background:#f1f3f7' })));
  } else {
    body.append(fieldText('Range', (d.ranges || [])[0] || '', (v, b) => patchEntity('slots', d.name, 'range', v, b)));
  }
  // required toggle
  const cb = el('input', { type: 'checkbox', checked: !!d.required });
  cb.addEventListener('change', () => patchEntity('slots', d.name, 'required', cb.checked));
  body.append(el('div', { className: 'field inline' }, cb, el('label', { textContent: 'Required', style: 'text-transform:none' })));
  body.append(fieldText('Description', d.description, (v, b) => patchEntity('slots', d.name, 'description', v, b), { textarea: true }));
  const usedBy = classesUsingSlot(d.name).size;
  const applyBtn = el('button', { className: 'btn', style: 'width:100%;margin-top:4px', textContent: `＋ Add this slot to templates…  (in ${usedBy} now)` });
  applyBtn.addEventListener('click', () => openApplySlot(d.name));
  body.append(applyBtn);
  if ((d.ranges || []).some((r) => STATE.enumsByName.has(r))) {
    body.append(el('p', { className: 'muted', style: 'font-size:12px;margin-top:8px', textContent: 'Tip: this range is an enum — double-click its node to expand its values.' }));
  }
  setInspector([inspectorHead(d)], [body]);
}

function renderEnumInspector(d) {
  const pct = d.valueCount ? Math.round((d.mappedCount / d.valueCount) * 100) : 0;
  const summary = el('p', { className: 'muted', style: 'font-size:12px; margin:0 0 10px', textContent: `${d.mappedCount}/${d.valueCount} values mapped to ontology terms (${pct}%).` });
  const addBtn = el('button', { className: 'btn btn-primary', style: 'width:100%', textContent: '＋ Add term (assisted)' });
  addBtn.addEventListener('click', () => openAddTerm(d.name));
  const rows = el('div', { className: 'val-rows' });
  for (const v of d.values) rows.append(enumValueRow(d, v));
  setInspector([inspectorHead(d), summary, addBtn], [rows]);
}

function enumValueRow(enumNode, v) {
  const row = el('div', { className: 'val-row' });
  row.append(el('div', { className: 'val-name', textContent: v.value }));
  const meaning = el('div', { className: 'val-meaning' });
  meaning.innerHTML = v.meaning
    ? `<span class="mapped">✓ ${v.meaning}</span>`
    : `<span class="unmapped">no mapping</span>`;
  row.append(meaning);
  if (v.description) row.append(el('div', { className: 'vdesc', textContent: v.description }));
  const findBtn = el('button', { className: 'btn btn-sm', textContent: v.meaning ? 'Re-map' : 'Find mapping' });
  const sugg = el('div', { className: 'suggestions' });
  findBtn.addEventListener('click', () => suggestFor(enumNode, v, sugg, meaning));
  const removeBtn = el('button', { className: 'btn btn-sm', textContent: 'Remove', title: 'delete this value from the enum' });
  removeBtn.addEventListener('click', async () => {
    if (!confirm(`Remove “${v.value}” from ${enumNode.name}?\nThis deletes the permissible value from the source YAML (existing data using it would no longer validate).`)) return;
    try {
      await api('DELETE', `/api/enums/${encodeURIComponent(enumNode.name)}/value/${encodeURIComponent(v.value)}`);
      const i = enumNode.values.findIndex((x) => x.value === v.value);
      if (i >= 0) { if (enumNode.values[i].meaning) enumNode.mappedCount = Math.max(0, enumNode.mappedCount - 1); enumNode.values.splice(i, 1); enumNode.valueCount = Math.max(0, enumNode.valueCount - 1); }
      const n = STATE.cy?.getElementById(enumNode.id); if (n?.length) { n.data('valueCount', enumNode.valueCount); n.data('mappedCount', enumNode.mappedCount); }
      toast(`Removed “${v.value}”`, 'ok'); refreshChanges(); renderSidebar(); row.remove();
    } catch (e) { toast(e.message, 'err'); }
  });
  row.append(el('div', { className: 'mini' }, findBtn, removeBtn), sugg);
  return row;
}

// shared: search OLS for a value and offer click-to-apply suggestions
async function suggestFor(enumNode, v, container, meaningEl) {
  container.replaceChildren(el('div', { className: 'muted', style: 'font-size:12px', textContent: 'searching…' }));
  try {
    const { results } = await api('GET', `/api/ontology/search?q=${encodeURIComponent(v.value)}&rows=8`);
    container.replaceChildren();
    if (!results.length) { container.append(el('div', { className: 'muted', textContent: 'no matches' })); return; }
    for (const r of results) {
      if (!r.curie) continue;
      const s = el('div', { className: 'suggestion' },
        el('span', { className: 'curie', textContent: r.curie }),
        el('span', { textContent: r.label }),
        el('span', { className: 'muted', textContent: r.ontology || '' }));
      s.title = r.description || '';
      s.addEventListener('click', async () => {
        try {
          await ensurePrefix(r.curie, r.iri);
          await api('PATCH', `/api/enums/${encodeURIComponent(enumNode.name)}/value/${encodeURIComponent(v.value)}`, { field: 'meaning', val: r.curie });
          if (r.iri) await api('PATCH', `/api/enums/${encodeURIComponent(enumNode.name)}/value/${encodeURIComponent(v.value)}`, { field: 'source', val: r.iri }).catch(() => {});
          v.meaning = r.curie; applyValueLocally(enumNode, v.value, r.curie);
          meaningEl.innerHTML = `<span class="mapped">✓ ${r.curie}</span>`;
          container.replaceChildren();
          toast(`Mapped ${v.value} → ${r.curie}`, 'ok');
          refreshChanges();
        } catch (e) { toast(e.message, 'err'); }
      });
      container.append(s);
    }
  } catch (e) { container.replaceChildren(el('div', { className: 'muted', textContent: e.message })); }
}

// update local model counts so stats/inspectors stay in sync
function applyValueLocally(enumNode, value, meaning) {
  let vobj = enumNode.values.find((x) => x.value === value);
  if (!vobj) { vobj = { value, meaning: null, source: null, description: '' }; enumNode.values.push(vobj); enumNode.valueCount++; }
  const wasMapped = !!vobj.meaning;
  vobj.meaning = meaning;
  if (meaning && !wasMapped) enumNode.mappedCount++;
  if (STATE.cy) { const n = STATE.cy.getElementById(enumNode.id); if (n.length) n.data('mappedCount', enumNode.mappedCount); }
}

// ============================================================
//  ONTOLOGY GAPS
// ============================================================
let gapsLoaded = false;
async function loadGaps() {
  if (gapsLoaded) return; gapsLoaded = true;
  const { gaps } = await api('GET', '/api/gaps');
  const listEl = $('#gaps-list');
  function render(filter = '', onlyGaps = true) {
    listEl.replaceChildren();
    const f = filter.toLowerCase();
    for (const g of gaps) {
      if (onlyGaps && !g.missing.length) continue;
      if (f && !g.enum.toLowerCase().includes(f)) continue;
      const item = el('div', { className: 'gap-item' },
        el('span', { className: 'gname', textContent: g.enum }),
        el('span', { className: 'gcount', textContent: `${g.missing.length}/${g.total}` }));
      item.addEventListener('click', () => {
        $$('.gap-item').forEach((x) => x.classList.remove('active')); item.classList.add('active');
        renderGapDetail(g);
      });
      listEl.append(item);
    }
  }
  render();
  $('#gaps-filter').addEventListener('input', (e) => render(e.target.value.trim(), $('#gaps-hide-mapped').checked));
  $('#gaps-hide-mapped').addEventListener('change', (e) => render($('#gaps-filter').value.trim(), e.target.checked));
  // ?gap=EnumName auto-opens that enum's gap detail (shareable link)
  const want = new URLSearchParams(location.search).get('gap');
  if (want) { const g = gaps.find((x) => x.enum === want); if (g) renderGapDetail(g); }
}

const normLabel = (s) => String(s == null ? '' : s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

async function renderGapDetail(g) {
  const enumNode = STATE.enumsByName.get(g.enum) || { name: g.enum, values: [], mappedCount: 0, valueCount: g.total, id: `enum::${g.enum}` };
  const box = el('div', {});
  box.append(
    el('h2', { textContent: g.enum }),
    el('p', { className: 'muted', textContent: `${enumNode.values.length || g.total} values · ${enumNode.mappedCount || 0} mapped to ontology terms. Compare to an ontology branch to find values you're missing.` }));

  // ---- present-membership index (rebuilt after adds) ----
  let presentCuries, presentLabels;
  const rebuildPresent = () => {
    presentCuries = new Set((enumNode.values || []).filter((v) => v.meaning).map((v) => String(v.meaning).toLowerCase()));
    presentLabels = new Set((enumNode.values || []).map((v) => normLabel(v.value)));
  };
  rebuildPresent();
  const isPresent = (t) => (t.curie && presentCuries.has(t.curie.toLowerCase()))
    || presentLabels.has(normLabel(t.label))
    || (t.synonyms || []).some((s) => presentLabels.has(normLabel(s)));

  // ---- Section 1: find missing values ----
  const cov = el('div', { className: 'cov' });
  cov.append(el('h3', { textContent: 'Find missing values' }));
  const rootQ = el('input', { type: 'text', className: 'search', placeholder: 'Find a branch, e.g. "Astrocytoma", "Neurofibroma"…' });
  const ontF = el('input', { type: 'text', className: 'search ont-filter', placeholder: 'all ontologies' });
  const exactC = el('input', { type: 'checkbox' });
  const searchBtn = el('button', { className: 'btn', textContent: 'Search branches' });
  cov.append(el('div', { className: 'cov-search' }, rootQ, ontF,
    el('label', { className: 'chk' }, exactC, document.createTextNode(' exact')), searchBtn));
  const hintEl = el('div', { className: 'add-hint' }); hintEl.style.display = 'none';
  cov.append(hintEl);
  const rootBox = el('div', { className: 'cov-roots' });
  const missBox = el('div', { className: 'cov-missing' });
  cov.append(rootBox, missBox);
  box.append(cov);

  // prefill ontology filter from the enum's domain hint
  api('GET', `/api/enum-hint?enum=${encodeURIComponent(g.enum)}`).then((h) => {
    if (h.ontology) ontF.value = h.ontology;
    if (h.note) { hintEl.style.display = 'flex'; hintEl.textContent = h.note; }
  }).catch(() => {});

  async function searchRoots() {
    const q = rootQ.value.trim(); if (q.length < 2) return;
    rootBox.replaceChildren(el('div', { className: 'muted', style: 'padding:8px', textContent: 'searching branches…' }));
    missBox.replaceChildren();
    try {
      const params = new URLSearchParams({ q, ontology: ontF.value.trim(), rows: '14', branches: 'true' });
      if (exactC.checked) params.set('exact', 'true');
      const { results } = await api('GET', `/api/ontology/search?${params}`);
      rootBox.replaceChildren();
      if (!results.length) { rootBox.append(el('div', { className: 'cand-none', textContent: 'No branch terms match (leaf terms are hidden — nothing to pull beneath them).' })); return; }
      for (const r of results) {
        const item = el('div', { className: 'root-item' },
          el('div', {}, el('span', { className: 'curie', textContent: r.curie || '' }), ' ', el('strong', { textContent: r.label }),
            el('span', { className: 'cand-ont', style: 'margin-left:8px', textContent: r.ontology || '' })),
          r.description ? el('div', { className: 'muted', style: 'font-size:11.5px;margin-top:3px', textContent: r.description }) : '');
        item.addEventListener('click', () => { $$('.root-item', rootBox).forEach((x) => x.classList.remove('active')); item.classList.add('active'); loadBranch(r); });
        rootBox.append(item);
      }
    } catch (e) { rootBox.replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
  }
  searchBtn.addEventListener('click', searchRoots);
  rootQ.addEventListener('keydown', (e) => { if (e.key === 'Enter') searchRoots(); });

  let depth = 'direct';
  async function loadBranch(root) {
    missBox.replaceChildren(el('div', { className: 'muted', style: 'padding:8px', textContent: 'loading branch & comparing…' }));
    const ont = (root.ontology || ontF.value.trim() || '').toLowerCase();
    try {
      const { terms } = await api('GET', `/api/ontology/descendants?ontology=${encodeURIComponent(ont)}&iri=${encodeURIComponent(root.iri)}&direct=${depth === 'direct'}&size=400`);
      rebuildPresent();
      const missing = terms.filter((t) => t.curie && !isPresent(t)).sort((a, b) => a.label.localeCompare(b.label));
      const presentN = terms.length - missing.length;
      renderMissing(root, ont, terms, missing, presentN);
    } catch (e) { missBox.replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
  }

  function renderMissing(root, ont, terms, missing, presentN) {
    missBox.replaceChildren();
    const depthRow = el('div', { className: 'cov-depth' },
      el('span', { className: 'muted', textContent: `under ${root.curie} · ` }));
    ['direct', 'all'].forEach((d) => {
      const id = `cd-${d}`;
      const rb = el('input', { type: 'radio', name: 'cov-depth', id, checked: depth === d });
      rb.addEventListener('change', () => { depth = d; loadBranch(root); });
      depthRow.append(el('label', { className: 'chk', htmlFor: id }, rb, document.createTextNode(d === 'direct' ? ' direct children' : ' all descendants')));
    });
    missBox.append(depthRow);

    const summary = el('div', { className: 'cov-summary' },
      el('strong', { textContent: `${missing.length} missing` }),
      el('span', { className: 'muted', textContent: ` · ${presentN} already present · ${terms.length} in branch` }));
    missBox.append(summary);

    if (!missing.length) { missBox.append(el('div', { className: 'cand-none', textContent: terms.length ? '✓ This enum already covers the whole branch.' : 'No terms found under this root.' })); return; }

    const boxes = [];
    const list = el('div', { className: 'miss-list' });
    for (const t of missing) {
      const cb = el('input', { type: 'checkbox', checked: true });
      boxes.push([cb, t]);
      list.append(el('label', { className: 'miss-item' }, cb,
        el('span', { className: 'curie', textContent: t.curie }),
        el('span', { className: 'mi-label', textContent: t.label }),
        t.description ? el('span', { className: 'mi-def', textContent: t.description }) : ''));
    }
    const selAll = el('button', { className: 'btn btn-sm', textContent: 'All' });
    const selNone = el('button', { className: 'btn btn-sm', textContent: 'None' });
    selAll.addEventListener('click', () => { boxes.forEach(([cb]) => (cb.checked = true)); updateAdd(); });
    selNone.addEventListener('click', () => { boxes.forEach(([cb]) => (cb.checked = false)); updateAdd(); });
    const addSel = el('button', { className: 'btn btn-primary' });
    boxes.forEach(([cb]) => cb.addEventListener('change', updateAdd));
    function updateAdd() { const n = boxes.filter(([cb]) => cb.checked).length; addSel.textContent = `Add ${n} to ${g.enum}`; addSel.disabled = !n; }
    updateAdd();
    addSel.addEventListener('click', async () => {
      const picked = boxes.filter(([cb]) => cb.checked).map(([, t]) => t);
      if (!picked.length) return;
      addSel.disabled = true; addSel.textContent = 'Adding…';
      try {
        for (const t of picked) if (t.curie) await ensurePrefix(t.curie, t.iri);
        const values = picked.map((t) => ({ value: t.label, meaning: t.curie, source: t.iri, description: t.description || undefined }));
        const r = await api('POST', `/api/enums/${encodeURIComponent(g.enum)}/values`, { values });
        (r.added || []).forEach((v) => { const t = picked.find((x) => x.label === v); applyValueLocally(enumNode, v, t?.curie || null); });
        toast(`Added ${r.added?.length || 0} value${r.added?.length === 1 ? '' : 's'} → ${r.file}`, 'ok');
        refreshChanges(); renderSidebar();
        rebuildPresent();
        loadBranch(root); // re-diff so added terms drop out of the missing list
      } catch (e) { toast(e.message, 'err'); addSel.disabled = false; }
    });
    missBox.append(el('div', { className: 'cov-actions' }, selAll, selNone, el('span', { style: 'flex:1' }), addSel), list);
  }

  // ---- Section 2: fix mappings on existing unmapped values ----
  if (g.missing?.length) {
    box.append(el('h3', { textContent: 'Unmapped existing values', style: 'margin-top:22px' }),
      el('p', { className: 'muted', style: 'margin:-4px 0 10px;font-size:12px', textContent: `${g.missing.length} value${g.missing.length === 1 ? '' : 's'} have no meaning: mapping. Add one with Find mapping.` }));
    const rows = el('div', { className: 'val-rows' });
    for (const m of g.missing) {
      const vobj = enumNode.values.find((x) => x.value === m.value) || { value: m.value, meaning: null, description: m.description };
      rows.append(enumValueRow(enumNode, vobj));
    }
    box.append(rows);
  }

  $('#gaps-detail').replaceChildren(box);
}

// ============================================================
//  GITHUB ISSUES
// ============================================================
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
let issuesInit = false;
async function loadIssues() {
  if (!issuesInit) {
    issuesInit = true;
    $('#issues-refresh').addEventListener('click', loadIssues);
    $('#issues-label').addEventListener('input', debounce(loadIssues, 400));
    $('#issues-state').addEventListener('change', loadIssues);
  }
  const list = $('#issues-list');
  list.replaceChildren(el('div', { className: 'muted', style: 'padding:12px', textContent: 'loading…' }));
  const label = $('#issues-label').value.trim();
  const state = $('#issues-state').value;
  try {
    const params = new URLSearchParams({ state });
    if (label) params.set('label', label);
    const { issues, error } = await api('GET', `/api/issues?${params}`);
    if (error) throw new Error(error);
    $('#issues-summary').textContent = `${issues.length} ${state} issue${issues.length === 1 ? '' : 's'}`;
    list.replaceChildren();
    if (!issues.length) { $('#issues-detail').replaceChildren(el('div', { className: 'inspector-empty', textContent: 'No matching issues.' })); return; }
    for (const it of issues) {
      const item = el('div', { className: 'gap-item' },
        el('span', { className: 'gname' }, el('span', { className: 'inum', textContent: `#${it.number}` }), ' ', el('span', { textContent: it.title })),
        el('span', { className: 'ilabels' }, ...it.labels.slice(0, 3).map((l) => el('span', { className: 'ilabel', textContent: l.name }))));
      item.title = it.title;
      item.addEventListener('click', () => { $$('.gap-item', list).forEach((x) => x.classList.remove('active')); item.classList.add('active'); showIssue(it); });
      list.append(item);
    }
  } catch (e) { list.replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
}
async function showIssue(it) {
  const d = $('#issues-detail');
  d.replaceChildren(el('div', { className: 'muted', textContent: 'loading…' }));
  try {
    const iss = await api('GET', `/api/issues/${it.number}`);
    const box = el('div', {});
    box.append(el('div', { className: 'issue-head' },
      el('span', { className: 'inum', textContent: `#${iss.number}` }),
      el('span', { className: `issue-state ${(iss.state || '').toLowerCase()}`, textContent: iss.state })));
    box.append(el('h2', { textContent: iss.title, style: 'margin-top:6px' }));
    if (iss.labels?.length) box.append(el('div', { className: 'ilabels', style: 'margin:8px 0 12px' }, ...iss.labels.map((l) => el('span', { className: 'ilabel', textContent: l.name }))));
    const gh = el('button', { className: 'btn btn-sm', textContent: 'Open on GitHub ↗' });
    gh.onclick = () => window.open(iss.url, '_blank', 'noopener');
    const cp = el('button', { className: 'btn btn-sm', textContent: 'Copy prompt for Claude' });
    cp.onclick = () => navigator.clipboard?.writeText(`In the nf-metadata-dictionary repo, resolve GitHub issue #${iss.number}: "${iss.title}".\n\n${iss.body || ''}`).then(() => toast('Prompt copied — paste into the terminal', 'ok'), () => toast('clipboard blocked', 'err'));
    const tm = el('button', { className: 'btn btn-sm btn-primary', textContent: '❯ Open terminal' });
    tm.onclick = () => openTerminal();
    box.append(el('div', { className: 'issue-actions' }, gh, cp, tm));
    box.append(renderIssueBody(iss.body || '_(no description)_'));
    d.replaceChildren(box);
  } catch (e) { d.replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
}
function renderIssueBody(md) {
  const esc = String(md).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const html = esc
    .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  const div = el('div', { className: 'issue-body' });
  div.innerHTML = html;
  return div;
}

// ============================================================
//  CHANGES (branch diff vs main)
// ============================================================
let diffInit = false;
let DIFF = { base: 'main', files: [] };
const isModelFile = (p) => p.startsWith('modules/') || p === 'header.yaml' || p === 'dca-template-config.json';
async function loadDiff() {
  if (!diffInit) { diffInit = true; $('#diff-refresh').addEventListener('click', loadDiff); $('#diff-model-only').addEventListener('change', renderDiffList); $('#pr-btn').addEventListener('click', openPrModal); }
  const listEl = $('#diff-list');
  listEl.replaceChildren(el('div', { className: 'muted', style: 'padding:12px', textContent: 'loading…' }));
  try {
    DIFF = await api('GET', '/api/diff');
    $('#diff-base').textContent = DIFF.base;
    renderDiffList();
  } catch (e) { listEl.replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
}
function renderDiffList() {
  const listEl = $('#diff-list');
  const modelOnly = $('#diff-model-only')?.checked;
  const files = modelOnly ? DIFF.files.filter((f) => isModelFile(f.path)) : DIFF.files;
  const hidden = DIFF.files.length - files.length;
  $('#diff-summary').textContent = files.length
    ? `${files.length} file${files.length === 1 ? '' : 's'} vs ${DIFF.base}${modelOnly && hidden ? ` · ${hidden} non-model hidden` : ''}`
    : '';
  listEl.replaceChildren();
  if (!files.length) {
    $('#diff-detail').replaceChildren(el('div', { className: 'inspector-empty',
      textContent: modelOnly && DIFF.files.length ? `No model changes vs ${DIFF.base} (${DIFF.files.length} other file(s) changed).` : `No differences from ${DIFF.base}.` }));
    return;
  }
  for (const f of files) {
    const st = f.status === 'new' ? 'A' : f.status;
    const item = el('div', { className: 'gap-item' },
      el('span', { className: 'gname' }, el('span', { className: `diff-stat ds-${st}`, textContent: st }), ' ',
        el('span', { textContent: f.path.replace(/^modules\//, '') })),
      f.added != null ? el('span', { className: 'gcount diff-num', textContent: `+${f.added} −${f.removed}` })
        : el('span', { className: 'gcount', textContent: f.status === 'new' ? 'new' : '' }));
    item.title = f.path;
    item.addEventListener('click', () => { $$('.gap-item', listEl).forEach((x) => x.classList.remove('active')); item.classList.add('active'); showDiff(f); });
    listEl.append(item);
  }
}
function openPrModal() {
  const files = (DIFF.files || []).filter((f) => isModelFile(f.path));
  if (!files.length) { toast('No model changes to submit', 'err'); return; }
  const m = openModal({ title: 'Create pull request', subtitle: `${files.length} model file(s) → a new branch off ${DIFF.base || 'main'}`, width: '560px' });
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '');
  const titleI = el('input', { type: 'text', value: 'Update metadata model' });
  const branchI = el('input', { type: 'text', value: `model-update-${stamp}` });
  const baseI = el('input', { type: 'text', value: DIFF.base || 'main' });
  const bodyI = el('textarea', { style: 'min-height:70px' });
  bodyI.value = 'Model changes from the visual editor:\n' + files.map((f) => `- ${f.path}`).join('\n');
  const list = el('div', { className: 'pr-files' }, ...files.map((f) => {
    const st = f.status === 'new' ? 'A' : f.status;
    return el('div', { className: 'pr-file' }, el('span', { className: `diff-stat ds-${st}`, textContent: st }), ' ', el('span', { textContent: f.path }));
  }));
  const result = el('div', { className: 'import-result' });
  m.body.append(labeledField('Title', titleI), labeledField('Branch', branchI), labeledField('Base branch', baseI),
    labeledField('Description', bodyI), labeledField(`Includes (${files.length})`, list), result);

  const create = el('button', { className: 'btn btn-primary', textContent: 'Create PR' });
  create.addEventListener('click', async () => {
    if (!titleI.value.trim()) { toast('title required', 'err'); return; }
    create.disabled = true; create.textContent = 'Creating PR…';
    result.className = 'import-result'; result.textContent = 'Pushing branch & opening PR…';
    try {
      const r = await api('POST', '/api/pr', { title: titleI.value.trim(), branch: branchI.value.trim(), base: baseI.value.trim() || 'main', body: bodyI.value });
      result.className = 'import-result ok';
      result.replaceChildren(el('span', { textContent: `✓ PR created for ${r.files} file(s) on ${r.branch} — ` }),
        el('a', { href: r.url, target: '_blank', rel: 'noopener', textContent: 'open it ↗' }));
      toast('Pull request created', 'ok'); refreshChanges();
    } catch (e) { result.className = 'import-result err'; result.textContent = e.message; create.disabled = false; create.textContent = 'Create PR'; }
  });
  m.foot.append(create, el('span', { className: 'muted', style: 'font-size:12px', textContent: 'commits only model files; your working tree is untouched' }),
    el('span', { style: 'flex:1' }), el('button', { className: 'btn btn-sm', textContent: 'Cancel', onclick: m.close }));
}

async function showDiff(f) {
  $('#diff-detail').replaceChildren(el('div', { className: 'muted', textContent: 'loading diff…' }));
  try {
    const q = `path=${encodeURIComponent(f.path)}${f.status === 'new' ? '&untracked=true' : ''}`;
    const { patch } = await api('GET', `/api/diff/file?${q}`);
    $('#diff-detail').replaceChildren(el('div', { className: 'diff-file' }, el('div', { className: 'diff-file-head', textContent: f.path }), renderPatch(patch)));
  } catch (e) { $('#diff-detail').replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
}
function renderPatch(patch) {
  const box = el('div', { className: 'diff' });
  if (!patch.trim()) { box.append(el('div', { className: 'muted', style: 'padding:8px', textContent: '(no textual diff — binary or empty)' })); return box; }
  for (const line of patch.split('\n')) {
    let cls = 'dl';
    if (line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('+++') || line.startsWith('---') || line.startsWith('new file') || line.startsWith('deleted')) cls = 'dl meta';
    else if (line.startsWith('@@')) cls = 'dl hunk';
    else if (line.startsWith('+')) cls = 'dl add';
    else if (line.startsWith('-')) cls = 'dl del';
    box.append(el('div', { className: cls, textContent: line || ' ' }));
  }
  return box;
}

// ============================================================
//  IMPORT ONTOLOGY
// ============================================================
function initImportPanel() {
  // destination dropdowns
  const fileSel = $('#new-enum-file');
  // suggest a sensible default new file plus all existing module files
  fileSel.append(el('option', { value: 'modules/Other/ImportedEnums.yaml', textContent: 'modules/Other/ImportedEnums.yaml (new file)' }));
  STATE.files.forEach((f) => fileSel.append(el('option', { value: f, textContent: f.replace('modules/', '') })));
  const existSel = $('#existing-enum');
  [...STATE.enumsByName.keys()].sort().forEach((n) => existSel.append(el('option', { value: n, textContent: n })));

  $('#import-search-btn').addEventListener('click', searchRoots);
  $('#import-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchRoots(); });
  $$('input[name="depth"]').forEach((r) => r.addEventListener('change', () => { if (IMPORT.root) loadDescendants(); }));
  $('#sel-all').addEventListener('click', () => toggleAllTerms(true));
  $('#sel-none').addEventListener('click', () => toggleAllTerms(false));
  $('#do-import').addEventListener('click', doImport);
}

const IMPORT = { root: null, terms: [] };

async function searchRoots() {
  const q = $('#import-q').value.trim(); if (!q) return;
  const ont = $('#import-ont').value.trim();
  const box = $('#import-roots');
  box.replaceChildren(el('div', { className: 'muted', textContent: 'searching…' }));
  try {
    const { results } = await api('GET', `/api/ontology/search?q=${encodeURIComponent(q)}&ontology=${encodeURIComponent(ont)}&rows=15&branches=true`);
    box.replaceChildren();
    if (!results.length) return box.append(el('div', { className: 'muted', textContent: 'No branch terms match (leaf terms are hidden — they have nothing to import under them).' }));
    for (const r of results) {
      const item = el('div', { className: 'root-item' },
        el('div', {}, el('span', { className: 'curie', textContent: r.curie || '' }), ' ', el('span', { textContent: r.label })),
        el('div', { className: 'muted', style: 'font-size:11px', textContent: r.ontology || '' }));
      item.addEventListener('click', () => {
        $$('.root-item').forEach((x) => x.classList.remove('active')); item.classList.add('active');
        IMPORT.root = r; $('#import-root-label').textContent = `under ${r.curie}`;
        if (!$('#new-enum-name').value) $('#new-enum-name').value = suggestEnumName(r.label);
        loadDescendants();
      });
      box.append(item);
    }
  } catch (e) { box.replaceChildren(el('div', { className: 'muted', textContent: e.message })); }
}

function suggestEnumName(label) {
  return label.replace(/[^A-Za-z0-9 ]/g, '').split(/\s+/).map((w) => w[0]?.toUpperCase() + w.slice(1)).join('') + 'Enum';
}

async function loadDescendants() {
  const r = IMPORT.root; if (!r) return;
  const direct = $('input[name="depth"]:checked').value === 'direct';
  const ont = r.ontology || $('#import-ont').value.trim();
  const box = $('#import-terms');
  box.replaceChildren(el('div', { className: 'muted', textContent: 'loading descendants…' }));
  $('#import-toolbar').hidden = true;
  try {
    const { terms } = await api('GET', `/api/ontology/descendants?ontology=${encodeURIComponent(ont)}&iri=${encodeURIComponent(r.iri)}&direct=${direct}&size=300`);
    IMPORT.terms = terms;
    box.replaceChildren();
    if (!terms.length) { box.append(el('div', { className: 'muted', textContent: 'no descendants found' })); updateImportCount(); return; }
    for (const t of terms.sort((a, b) => a.label.localeCompare(b.label))) {
      const cb = el('input', { type: 'checkbox', checked: true });
      cb.addEventListener('change', updateImportCount);
      t._cb = cb;
      box.append(el('label', { className: 'term-item' }, cb,
        el('span', { className: 'curie', textContent: t.curie || '' }),
        el('span', { textContent: t.label })));
    }
    $('#import-toolbar').hidden = false;
    updateImportCount();
  } catch (e) { box.replaceChildren(el('div', { className: 'muted', textContent: e.message })); }
}

function toggleAllTerms(on) { IMPORT.terms.forEach((t) => { if (t._cb) t._cb.checked = on; }); updateImportCount(); }
function selectedTerms() { return IMPORT.terms.filter((t) => t._cb?.checked && t.curie); }
function updateImportCount() {
  const n = selectedTerms().length;
  $('#import-count').textContent = `${n} selected`;
  $('#do-import').disabled = n === 0;
}

async function doImport() {
  const terms = selectedTerms();
  if (!terms.length) return;
  const inclDesc = $('#incl-desc').checked;
  const values = terms.map((t) => ({ value: t.label, meaning: t.curie, source: t.iri, description: inclDesc ? t.description : undefined }));
  const dest = $('input[name="dest"]:checked').value;
  const resBox = $('#import-result');
  resBox.className = 'import-result'; resBox.textContent = 'importing…';
  try {
    let r;
    if (dest === 'new') {
      const name = $('#new-enum-name').value.trim(); const file = $('#new-enum-file').value;
      if (!name) throw new Error('enter a new enum name');
      r = await api('POST', '/api/enums', { name, file, description: `Imported from ${IMPORT.root.curie} (${IMPORT.root.label}).`, values });
      resBox.textContent = `✓ Created enum ${name} with ${values.length} values → ${r.file}.`;
    } else {
      const name = $('#existing-enum').value;
      r = await api('POST', `/api/enums/${encodeURIComponent(name)}/values`, { values });
      resBox.textContent = `✓ Added ${r.added.length} new values to ${name} → ${r.file} (${values.length - r.added.length} already present).`;
    }
    resBox.classList.add('ok');
    toast('Import written', 'ok');
    refreshChanges();
    await refreshModel();
    // refresh existing-enum dropdown so a newly created enum is appendable next time
    const existSel = $('#existing-enum');
    if (existSel && dest === 'new' && ![...existSel.options].some((o) => o.value === $('#new-enum-name').value.trim())) {
      existSel.append(el('option', { value: $('#new-enum-name').value.trim(), textContent: $('#new-enum-name').value.trim() }));
    }
  } catch (e) { resBox.className = 'import-result err'; resBox.textContent = e.message; }
}

// toggle destination field visibility
document.addEventListener('change', (e) => {
  if (e.target.name === 'dest') {
    $('#dest-new').style.opacity = e.target.value === 'new' ? 1 : 0.4;
    $('#dest-existing').style.opacity = e.target.value === 'existing' ? 1 : 0.4;
  }
});

// ============================================================
//  PREFIXES + CURIE GUARDRAILS
// ============================================================
async function loadPrefixes() { try { STATE.prefixes = (await api('GET', '/api/prefixes')).prefixes || {}; } catch { STATE.prefixes = {}; } }
const isCurie = (s) => /^[A-Za-z][\w.]*:[^/\s]\S*$/.test(s) && !/^https?:/.test(s);
const prefixOf = (curie) => (curie || '').split(':')[0];
const isUrl = (s) => /^https?:\/\//.test(s || '');

// Ensure a CURIE's prefix is declared in header.yaml; derive its URI from the term IRI.
async function ensurePrefix(curie, iri) {
  const pfx = prefixOf(curie);
  if (!pfx || (STATE.prefixes && STATE.prefixes[pfx])) return true;
  if (!iri) return false;
  const local = curie.slice(pfx.length + 1);
  const uri = iri.endsWith(local) ? iri.slice(0, iri.length - local.length) : null;
  if (!uri) return false;
  await api('POST', '/api/prefixes', { prefix: pfx, uri });
  STATE.prefixes[pfx] = uri;
  toast(`Declared prefix "${pfx}:" in header.yaml`, 'ok');
  return true;
}

// ============================================================
//  MODAL INFRA
// ============================================================
function openModal({ title, subtitle = '', width }) {
  if (window.__nfEndTour) window.__nfEndTour(); // a modal takes precedence over the tour
  const root = $('#modal-root');
  const bg = el('div', { className: 'modal-bg' });
  const card = el('div', { className: 'modal-card' });
  if (width) card.style.width = width;
  const body = el('div', { className: 'modal-body' });
  const foot = el('div', { className: 'modal-foot' });
  const x = el('button', { className: 'modal-x', innerHTML: '&times;', title: 'Close (Esc)' });
  card.append(
    el('div', { className: 'modal-head' },
      el('div', {}, el('h3', { textContent: title }), subtitle ? el('p', { textContent: subtitle }) : ''), x),
    body, foot);
  bg.append(card); root.append(bg);
  const close = () => { bg.remove(); document.removeEventListener('keydown', onEsc); };
  const onEsc = (e) => { if (e.key === 'Escape') close(); };
  x.onclick = close;
  bg.onclick = (e) => { if (e.target === bg) close(); };
  document.addEventListener('keydown', onEsc);
  return { bg, card, body, foot, close, setSubtitle: (t) => { const p = card.querySelector('.modal-head p'); if (p) p.textContent = t; } };
}

// ============================================================
//  ASSISTED "ADD TERM"  — the primary, low-friction flow
// ============================================================
function initAddTerm() {
  $('#add-term-btn').addEventListener('click', () => openAddTerm());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'a' && !/input|textarea|select/i.test(document.activeElement?.tagName) && !$('.modal-bg')) openAddTerm();
  });
}

function openAddTerm(presetEnum) {
  const m = openModal({ title: 'Add a term', subtitle: 'Pick a value set, type the term — pick a match to fill everything in.', width: '600px' });
  const enums = [...STATE.enumsByName.keys()].sort();

  const enumSel = el('select', { className: 'select' });
  enumSel.append(el('option', { value: '', textContent: 'Choose a value set (enum)…' }));
  enums.forEach((n) => enumSel.append(el('option', { value: n, textContent: n })));
  if (presetEnum) enumSel.value = presetEnum;

  const hint = el('div', { className: 'add-hint' }); hint.style.display = 'none';
  const searchWrap = el('div', { className: 'add-search-wrap' });
  const termInput = el('input', { type: 'text', className: 'search', placeholder: 'Type a term, e.g. "Glioblastoma"…', disabled: !presetEnum });
  searchWrap.append(termInput, el('div', { className: 'spin' }));
  // ontology filter + exact toggle
  const ontInput = el('input', { type: 'text', className: 'search ont-filter', placeholder: 'all ontologies', title: 'Comma-separated ontology prefixes, e.g. mondo,ncit. Blank = all.' });
  const exactChk = el('input', { type: 'checkbox' });
  const filterRow = el('div', { className: 'filter-row' },
    el('label', { textContent: 'Ontologies' }), ontInput,
    el('label', { className: 'chk' }, exactChk, document.createTextNode(' exact match')));
  const candList = el('div', { className: 'cand-list' });
  const preview = el('div', {}); // filled on selection

  m.body.append(
    el('div', { className: 'add-target' }, el('label', { textContent: 'Add to' }), enumSel),
    hint, searchWrap, filterRow, candList, preview);

  let scope = { ontology: '', note: '' };
  let chosen = null;

  async function refreshHint() {
    const name = enumSel.value;
    if (!name) { hint.style.display = 'none'; return; }
    try { scope = await api('GET', `/api/enum-hint?enum=${encodeURIComponent(name)}`); } catch { scope = { ontology: '', note: '' }; }
    hint.style.display = 'flex';
    hint.textContent = scope.note;
    ontInput.value = scope.ontology || '';
  }
  enumSel.addEventListener('change', () => { termInput.disabled = !enumSel.value; refreshHint(); termInput.focus(); runSearch(); });
  if (presetEnum) refreshHint();

  let t;
  const debounced = () => { clearTimeout(t); t = setTimeout(runSearch, 280); };
  termInput.addEventListener('input', debounced);
  ontInput.addEventListener('input', debounced);
  exactChk.addEventListener('change', runSearch);
  async function runSearch() {
    const q = termInput.value.trim();
    chosen = null; preview.replaceChildren();
    if (!enumSel.value || q.length < 2) { candList.replaceChildren(); renderFoot(); return; }
    searchWrap.classList.add('loading');
    try {
      const params = new URLSearchParams({ q, ontology: ontInput.value.trim(), rows: '12' });
      if (exactChk.checked) params.set('exact', 'true');
      const { results } = await api('GET', `/api/ontology/search?${params}`);
      renderCandidates(results, q);
    } catch (e) { candList.replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
    finally { searchWrap.classList.remove('loading'); }
  }

  function renderCandidates(results, q) {
    candList.replaceChildren();
    results = results.filter((r) => r.curie);
    if (!results.length) {
      candList.append(el('div', { className: 'cand-none' },
        el('div', { textContent: `No ontology match for “${q}”.` }),
        el('div', { style: 'margin-top:8px' }, freeTextBtn(q))));
      renderFoot(); return;
    }
    for (const r of results) {
      const c = el('div', { className: 'cand' },
        el('div', { className: 'cand-top' },
          el('span', { className: 'cand-label', textContent: r.label }),
          el('span', { className: 'cand-curie', textContent: r.curie }),
          el('span', { className: 'cand-ont', textContent: r.ontology || '' })));
      if (r.description) c.append(el('div', { className: 'cand-def', textContent: r.description }));
      if (r.synonyms?.length) c.append(el('div', { className: 'cand-syn' }, el('b', { textContent: 'synonyms: ' }), r.synonyms.slice(0, 5).join(', ')));
      c.addEventListener('click', () => { chosen = r; $$('.cand', candList).forEach((x) => x.classList.remove('sel')); c.classList.add('sel'); renderPreview(r); });
      candList.append(c);
    }
    candList.append(el('div', { style: 'padding-top:6px' }, freeTextBtn(q)));
    renderFoot();
  }

  function freeTextBtn(q) {
    const b = el('button', { className: 'btn btn-sm', textContent: `Use “${q}” as-is (no ontology mapping)` });
    b.addEventListener('click', () => { chosen = { label: q, curie: null, iri: null, description: '', synonyms: [], freeText: true }; renderPreview(chosen); });
    return b;
  }

  const state = { value: '', description: '', aliases: new Set() };
  function renderPreview(r) {
    state.value = r.label; state.description = r.description || ''; state.aliases = new Set();
    const valInput = el('input', { type: 'text', value: r.label });
    valInput.addEventListener('input', () => { state.value = valInput.value; renderFoot(); });
    const descInput = el('input', { type: 'text', value: r.description || '', placeholder: 'definition (optional)' });
    descInput.addEventListener('input', () => { state.description = descInput.value; });

    const rows = el('div', { className: 'add-preview' });
    rows.append(prow('Value', valInput));
    if (r.curie) rows.append(prow('Meaning', el('code', { textContent: r.curie })));
    else rows.append(prow('Meaning', el('span', { className: 'muted', textContent: '— none (free text) —' })));
    if (r.iri) rows.append(prow('Source', el('code', { textContent: r.iri })));
    rows.append(prow('Definition', descInput));
    if (r.synonyms?.length) {
      const chips = el('div', { className: 'alias-toggle' });
      r.synonyms.slice(0, 8).forEach((s) => {
        const chip = el('span', { className: 'alias-chip', textContent: s });
        chip.addEventListener('click', () => { chip.classList.toggle('on'); chip.classList.contains('on') ? state.aliases.add(s) : state.aliases.delete(s); });
        chips.append(chip);
      });
      rows.append(prow('Aliases', el('div', {}, el('div', { className: 'muted', style: 'font-size:11px;margin-bottom:4px', textContent: 'click to include as aliases:' }), chips)));
    }
    // prefix guardrail notice
    if (r.curie && STATE.prefixes && !STATE.prefixes[prefixOf(r.curie)]) {
      rows.append(el('div', { className: 'warn-line' },
        el('span', { textContent: `Prefix “${prefixOf(r.curie)}:” isn't declared yet — it'll be added to header.yaml automatically.` })));
    }
    preview.replaceChildren(rows);
    renderFoot();
  }
  function prow(k, v) { return el('div', { className: 'pv-row' }, el('div', { className: 'k', textContent: k }), el('div', { className: 'v' }, v)); }

  function renderFoot() {
    m.foot.replaceChildren();
    const addBtn = el('button', { className: 'btn btn-primary', textContent: 'Add term', disabled: !(chosen && state.value && enumSel.value) });
    addBtn.addEventListener('click', () => doAdd(addBtn));
    m.foot.append(addBtn, el('span', { className: 'muted', style: 'font-size:12px', textContent: chosen ? `→ ${enumSel.value}` : 'pick a match above' }),
      el('span', { style: 'flex:1' }), el('button', { className: 'btn btn-sm', textContent: 'Done', onclick: m.close }));
  }
  renderFoot();

  async function doAdd(btn) {
    btn.disabled = true; btn.textContent = 'Adding…';
    try {
      if (chosen.curie) await ensurePrefix(chosen.curie, chosen.iri);
      const value = { value: state.value, description: state.description || undefined,
        meaning: chosen.curie || undefined, source: chosen.iri || undefined,
        aliases: state.aliases.size ? [...state.aliases] : undefined };
      const r = await api('POST', `/api/enums/${encodeURIComponent(enumSel.value)}/values`, { values: [value] });
      if (!r.added?.length) { toast(`"${state.value}" already exists`, 'err'); btn.disabled = false; btn.textContent = 'Add term'; return; }
      const node = STATE.enumsByName.get(enumSel.value);
      if (node) applyValueLocally(node, state.value, chosen.curie || null);
      toast(`Added “${state.value}” → ${r.file}`, 'ok');
      refreshChanges(); renderSidebar();
      // reset for add-another, keep enum selected
      termInput.value = ''; chosen = null; candList.replaceChildren(); preview.replaceChildren(); termInput.focus(); renderFoot();
    } catch (e) { toast(e.message, 'err'); btn.disabled = false; btn.textContent = 'Add term'; }
  }

  setTimeout(() => (presetEnum ? termInput : enumSel).focus(), 50);
}

// ============================================================
//  APPLY SLOT TO MANY TEMPLATES
// ============================================================
function classesUsingSlot(slotName) {
  const sid = `slot::${slotName}`;
  return new Set((STATE.edgesByNode.get(sid) || []).filter((e) => e.type === 'uses').map((e) => NAME_OF(e.source)));
}
function openApplySlot(slotName) {
  const m = openModal({ title: `Add “${slotName}” to templates`, subtitle: 'Pick every template that should include this attribute — applied in one step.', width: '520px' });
  const have = classesUsingSlot(slotName);
  const classes = [...STATE.nodes.values()].filter((d) => d.kind === 'class').sort((a, b) => a.name.localeCompare(b.name));
  const list = el('div', { className: 'tmpl-check-list' });
  const boxes = [];
  for (const c of classes) {
    const cb = el('input', { type: 'checkbox', disabled: have.has(c.name) });
    boxes.push([cb, c.name]);
    list.append(el('label', { className: 'tmpl-check' }, cb,
      el('span', { textContent: c.name + (c.abstract ? '  (abstract)' : '') }),
      have.has(c.name) ? el('span', { className: 'has', textContent: '✓ has it' }) : ''));
  }
  const filter = el('input', { type: 'search', className: 'search', placeholder: 'Filter templates…' });
  filter.addEventListener('input', () => { const f = filter.value.toLowerCase();
    $$('.tmpl-check', list).forEach((lab) => { lab.style.display = lab.textContent.toLowerCase().includes(f) ? '' : 'none'; }); });
  m.body.append(filter, list);

  const apply = el('button', { className: 'btn btn-primary', textContent: 'Add to selected' });
  apply.addEventListener('click', async () => {
    const picked = boxes.filter(([cb]) => cb.checked && !cb.disabled).map(([, n]) => n);
    if (!picked.length) return;
    apply.disabled = true; apply.textContent = 'Applying…';
    try {
      const r = await api('POST', '/api/classes/slot-bulk', { slot: slotName, classes: picked });
      const ok = r.results.filter((x) => x.changed).length;
      toast(`Added “${slotName}” to ${ok} template${ok === 1 ? '' : 's'}`, 'ok');
      refreshChanges(); m.close();
      await refreshModel();
    } catch (e) { toast(e.message, 'err'); apply.disabled = false; apply.textContent = 'Add to selected'; }
  });
  m.foot.append(apply, el('span', { style: 'flex:1' }), el('button', { className: 'btn btn-sm', textContent: 'Cancel', onclick: m.close }));
}

// ============================================================
//  BUILD / VALIDATE TOOLBAR
// ============================================================
function initBuildBar() {
  $$('#build-bar [data-run]').forEach((btn) => btn.addEventListener('click', () => runTask(btn.dataset.run, btn)));
  $('#qc-btn').addEventListener('click', showQc);
  refreshChanges();
}
async function refreshChanges() {
  try {
    const { files } = await api('GET', '/api/changes');
    const elc = $('#build-changes');
    if (!files.length) { elc.textContent = 'No unsaved changes'; elc.className = 'build-changes'; }
    else { elc.textContent = `${files.length} changed file${files.length === 1 ? '' : 's'} — review with \`git diff\``; elc.className = 'build-changes dirty'; }
  } catch {}
}
async function runTask(task, btn) {
  const st = $('#build-status');
  st.className = 'build-status run'; st.textContent = `Running ${task}…`;
  $$('#build-bar [data-run]').forEach((b) => (b.disabled = true));
  try {
    const r = await api('POST', `/api/run/${task}`);
    st.className = `build-status ${r.ok ? 'ok' : 'err'}`;
    st.textContent = r.ok ? `✓ ${r.label} OK` : `✗ ${r.label} failed (exit ${r.code})`;
    if (!r.ok) showRunOutput(r);
  } catch (e) { st.className = 'build-status err'; st.textContent = e.message; }
  finally { $$('#build-bar [data-run]').forEach((b) => (b.disabled = false)); refreshChanges(); }
}
function showRunOutput(r) {
  const m = openModal({ title: r.label + ' — output', subtitle: r.cmd, width: '680px' });
  const pre = el('pre', { style: 'white-space:pre-wrap;font:12px/1.5 var(--font-mono);color:var(--ink-soft);margin:0' });
  pre.textContent = (r.err || '') + (r.out ? `\n${r.out}` : '') || '(no output)';
  m.body.append(pre);
  m.foot.append(el('span', { style: 'flex:1' }), el('button', { className: 'btn btn-sm', textContent: 'Close', onclick: m.close }));
}

// ============================================================
//  EMBEDDED TERMINAL (PTY over WebSocket → xterm.js)
// ============================================================
const TERM = { xt: null, ws: null, fit: null, poll: null, unavailable: false };
function initTerminal() {
  $('#terminal-btn').addEventListener('click', toggleTerminal);
  $('#term-close').addEventListener('click', closeTerminal);
  $('#term-reflect').addEventListener('click', reflectFromTerminal);
  initTermResize();
  window.addEventListener('resize', () => { if (!$('#terminal-drawer').hidden) fitTerm(); });
  initWatch(); // auto-reflect external edits
}
function toggleTerminal() { $('#terminal-drawer').hidden ? openTerminal() : closeTerminal(); }
function closeTerminal() {
  $('#terminal-drawer').hidden = true;
  clearInterval(TERM.poll); TERM.poll = null;
  if (STATE.cy) STATE.cy.resize();
}
async function openTerminal() {
  $('#terminal-drawer').hidden = false;
  if (STATE.cy) STATE.cy.resize();
  if (TERM.unavailable) return;
  if (!TERM.xt) {
    let ok = true;
    try { ok = (await api('GET', '/api/terminal')).available; } catch { ok = false; }
    if (!ok) { TERM.unavailable = true; $('#term-unavailable').hidden = false; $('#terminal').style.display = 'none'; return; }
    bootTerminal();
  } else { fitTerm(); TERM.xt.focus(); }
  TERM.poll = setInterval(refreshChanges, 4000); // keep the "N changed files" indicator live
}

// Server pushes an SSE "changed" when EXTERNAL edits touch the source (terminal /
// Claude Code / IDE) — our own GUI writes are filtered out server-side.
function initWatch() {
  let t;
  try {
    const es = new EventSource('/api/watch');
    es.onmessage = () => { clearTimeout(t); t = setTimeout(autoReflect, 600); };
  } catch { /* EventSource unsupported */ }
}
async function autoReflect() {
  try {
    await refreshModel();
    refreshChanges();
    const view = document.querySelector('.tab.active')?.dataset.view;
    if (view === 'changes') loadDiff();
    else if (view === 'gaps') { gapsLoaded = false; loadGaps(); }
    toast('Reflected changes from disk', 'ok');
  } catch { /* keep going */ }
}
function bootTerminal() {
  const Term = window.Terminal;
  const Fit = window.FitAddon?.FitAddon || window.FitAddon;
  if (!Term) { toast('terminal library failed to load', 'err'); return; }
  TERM.xt = new Term({
    fontSize: 12.5, fontFamily: '"IBM Plex Mono", ui-monospace, monospace', cursorBlink: true, scrollback: 5000,
    theme: { background: '#16201c', foreground: '#e7ece6', cursor: '#e7ece6', selectionBackground: '#3a4a42',
      black: '#2b3630', red: '#e0897e', green: '#9ec79a', yellow: '#e6c98a', blue: '#8fb8e8', magenta: '#cf9fd0', cyan: '#8fcfc6', white: '#e7ece6' },
  });
  if (Fit) { TERM.fit = new Fit(); TERM.xt.loadAddon(TERM.fit); }
  TERM.xt.open($('#terminal'));
  fitTerm();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/terminal`);
  TERM.ws = ws;
  ws.onopen = () => sendTermResize();
  ws.onmessage = (e) => TERM.xt.write(typeof e.data === 'string' ? e.data : '');
  ws.onclose = () => TERM.xt.write('\r\n\x1b[2m[terminal disconnected — reopen to reconnect]\x1b[0m\r\n');
  TERM.xt.onData((d) => { if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'input', data: d })); });
  TERM.xt.onResize(({ cols, rows }) => sendTermResize(cols, rows));
}
function fitTerm() { try { TERM.fit?.fit(); sendTermResize(); } catch {} }
function sendTermResize(cols, rows) {
  if (TERM.ws?.readyState === 1 && TERM.xt) TERM.ws.send(JSON.stringify({ type: 'resize', cols: cols || TERM.xt.cols, rows: rows || TERM.xt.rows }));
}
async function reflectFromTerminal() {
  const btn = $('#term-reflect'); btn.disabled = true; const t = btn.textContent; btn.textContent = 'Reflecting…';
  try {
    await refreshModel();
    refreshChanges();
    const view = document.querySelector('.tab.active')?.dataset.view;
    if (view === 'changes') loadDiff();
    if (view === 'gaps') { gapsLoaded = false; loadGaps(); }
    toast('Model re-read from the working tree', 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { btn.disabled = false; btn.textContent = t; }
}
function initTermResize() {
  const handle = $('#term-resize'); const drawer = $('#terminal-drawer');
  let startY, startH;
  const onMove = (e) => { const h = Math.max(140, Math.min(window.innerHeight * 0.82, startH + (startY - e.clientY))); drawer.style.height = `${h}px`; };
  const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); fitTerm(); if (STATE.cy) STATE.cy.resize(); };
  handle.addEventListener('mousedown', (e) => { startY = e.clientY; startH = drawer.offsetHeight; document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp); e.preventDefault(); });
}

// ============================================================
//  MODEL QC
// ============================================================
function resolveEntityId(name) {
  for (const k of ['enum', 'class', 'slot']) if (STATE.nodes.has(`${k}::${name}`)) return `${k}::${name}`;
  return null;
}
async function showQc() {
  const m = openModal({ title: 'Model QC', subtitle: 'Running checks…', width: '660px' });
  m.body.append(el('div', { className: 'muted', textContent: 'running…' }));
  try {
    const { findings, counts } = await api('GET', '/api/qc');
    m.setSubtitle(`${counts.error} error${counts.error === 1 ? '' : 's'} · ${counts.warn} warning${counts.warn === 1 ? '' : 's'} · ${counts.info} info`);
    const list = el('div', { className: 'qc-list' });
    if (!findings.length) list.append(el('div', { className: 'cand-none', textContent: '✓ No issues found.' }));
    for (const f of findings) {
      const row = el('div', { className: `qc-item qc-${f.severity}` },
        el('span', { className: 'qc-sev', textContent: f.severity }),
        el('div', {}, el('div', { className: 'qc-msg', textContent: f.message }), f.file ? el('div', { className: 'qc-file', textContent: f.file }) : ''));
      const id = f.entity && resolveEntityId(f.entity);
      if (id) { row.style.cursor = 'pointer'; row.title = 'Open in graph'; row.onclick = () => { m.close(); document.querySelector('.tab[data-view="graph"]').click(); focusEntity(id); }; }
      list.append(row);
    }
    m.body.replaceChildren(list);
  } catch (e) { m.body.replaceChildren(el('div', { className: 'cand-none', textContent: e.message })); }
  m.foot.append(el('button', { className: 'btn btn-sm', textContent: 'Re-run', onclick: () => { m.close(); showQc(); } }), el('span', { style: 'flex:1' }), el('button', { className: 'btn btn-sm', textContent: 'Close', onclick: m.close }));
}

// ============================================================
//  NEW CLASS / TEMPLATE
// ============================================================
const labeledField = (label, control) => el('div', { className: 'field' }, el('label', { textContent: label }), control);
const humanize = (name) => name.replace(/Template$/, '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/_/g, ' ').trim();

function chipField(placeholder, datalistId, initial = []) {
  const set = new Set(initial);
  const chips = el('div', { className: 'chips' });
  const input = el('input', { type: 'text', placeholder });
  if (datalistId) input.setAttribute('list', datalistId);
  const render = () => chips.replaceChildren(...[...set].map((v) => {
    const c = el('span', { className: 'chip', title: 'remove' }, `${v} ✕`); c.onclick = () => { set.delete(v); render(); }; return c;
  }));
  render();
  const addv = () => { const v = input.value.trim(); if (v) { set.add(v); input.value = ''; render(); } };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addv(); } });
  const addBtn = el('button', { className: 'btn btn-sm', textContent: 'Add' }); addBtn.onclick = addv;
  return { set, el: el('div', {}, el('div', { className: 'field inline' }, input, addBtn), chips) };
}

let DATATYPES = null;
async function openNewClass() {
  ensureSlotDatalist();
  const classes = [...STATE.nodes.values()].filter((d) => d.kind === 'class').sort((a, b) => a.name.localeCompare(b.name));
  if (!$('#parent-options')) { const dl = el('datalist', { id: 'parent-options' }); classes.forEach((c) => dl.append(el('option', { value: c.name }))); document.body.append(dl); }
  if (!DATATYPES) { try { DATATYPES = (await api('GET', '/api/datatypes')).values; } catch { DATATYPES = []; } }
  if (!$('#datatype-options')) { const dl = el('datalist', { id: 'datatype-options' }); DATATYPES.forEach((v) => dl.append(el('option', { value: v }))); document.body.append(dl); }

  const m = openModal({ title: 'New class / template', subtitle: 'Templates inherit from a parent (is_a); concrete templates need a dataType.', width: '600px' });
  const nameI = el('input', { type: 'text', placeholder: 'PascalCaseName, e.g. NanoStringAssayTemplate' });
  const parentI = el('input', { type: 'text', placeholder: 'parent class to inherit from' }); parentI.setAttribute('list', 'parent-options');
  const fileSel = el('select', { className: 'select' });
  fileSel.append(el('option', { value: '', textContent: 'choose a source file…' }));
  STATE.files.forEach((f) => fileSel.append(el('option', { value: f, textContent: f.replace('modules/', '') })));
  const absC = el('input', { type: 'checkbox' });
  const descI = el('textarea', { placeholder: 'one-line description' });
  const slots = chipField('add an existing slot…', 'slot-options');

  const dts = chipField('add a dataType…', 'datatype-options');
  const granSel = el('select', { className: 'select' }); ['', 'specimen-level', 'individual-level', 'aggregate-level', 'population-level'].forEach((v) => granSel.append(el('option', { value: v, textContent: v || 'data granularity…' })));
  const usageSel = el('select', { className: 'select' }); ['', 'most_common', 'common'].forEach((v) => usageSel.append(el('option', { value: v, textContent: v ? `usage: ${v}` : 'template usage…' })));
  const annBlock = el('div', { className: 'tmpl-ann' },
    el('h3', { textContent: 'Template annotations' }),
    labeledField('dataType — required for concrete templates', dts.el),
    el('div', { className: 'field inline' }, granSel, usageSel));

  const dcaC = el('input', { type: 'checkbox', checked: true });
  const dcaName = el('input', { type: 'text', placeholder: 'display name' });
  const dcaType = el('select', { className: 'select', style: 'max-width:110px' }); ['file', 'record'].forEach((v) => dcaType.append(el('option', { value: v, textContent: v })));
  const dcaBlock = el('div', { className: 'tmpl-ann' },
    el('label', { className: 'chk' }, dcaC, document.createTextNode(' Register in the Data Curator App as')),
    el('div', { className: 'field inline', style: 'margin-top:6px' }, dcaName, dcaType));

  const warn = el('div', { className: 'warn-line' }); warn.style.display = 'none';
  m.body.append(labeledField('Name', nameI), labeledField('Parent (is_a)', parentI), labeledField('Source file', fileSel),
    el('div', { className: 'field inline' }, absC, el('label', { textContent: 'Abstract (base template, not curated directly)', style: 'text-transform:none' })),
    labeledField('Description', descI), labeledField('Slots to include', slots.el), annBlock, dcaBlock, warn);

  const feats = STATE.config?.features || { dca: true, dataType: true };
  const tdir = STATE.config?.templateDir;
  const isTemplate = () => (tdir ? fileSel.value.startsWith(`${tdir}/`) : false);
  const concrete = () => isTemplate() && !absC.checked;
  const update = () => {
    annBlock.style.display = (concrete() && feats.dataType) ? '' : 'none';
    dcaBlock.style.display = (concrete() && feats.dca) ? '' : 'none';
    if (!dcaName.value && nameI.value) dcaName.value = humanize(nameI.value);
  };
  parentI.addEventListener('input', () => { const p = classes.find((c) => c.name === parentI.value.trim()); if (p && p.file) fileSel.value = p.file; update(); });
  fileSel.addEventListener('change', update);
  absC.addEventListener('change', update);
  nameI.addEventListener('input', () => { if (!dcaName.value) dcaName.value = humanize(nameI.value.trim()); });
  update();

  const createBtn = el('button', { className: 'btn btn-primary', textContent: 'Create class' });
  createBtn.addEventListener('click', async () => {
    const name = nameI.value.trim();
    warn.style.display = 'none';
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) { warn.style.display = 'flex'; warn.textContent = 'Name must be PascalCase with no spaces.'; return; }
    if (!fileSel.value) { warn.style.display = 'flex'; warn.textContent = 'Choose a source file.'; return; }
    const annotations = {};
    if (concrete() && feats.dataType) {
      if (!dts.set.size) { warn.style.display = 'flex'; warn.textContent = 'Concrete templates need at least one dataType (tests enforce this).'; return; }
      annotations.required = false; annotations.requiresComponent = '';
      if (usageSel.value) annotations.templateUsage = usageSel.value;
      if (granSel.value) annotations.dataGranularity = granSel.value;
      annotations.templateFor = { dataType: [...dts.set] };
    }
    const def = { is_a: parentI.value.trim() || undefined, abstract: absC.checked || undefined,
      description: descI.value.trim() || undefined, slots: [...slots.set], annotations: Object.keys(annotations).length ? annotations : undefined };
    const dca = (concrete() && feats.dca && dcaC.checked && dcaName.value.trim()) ? { display_name: dcaName.value.trim(), type: dcaType.value } : undefined;
    createBtn.disabled = true; createBtn.textContent = 'Creating…';
    try {
      const r = await api('POST', '/api/classes', { name, file: fileSel.value, def, dca });
      toast(`Created ${name} → ${r.file}${r.dca?.added ? ' (+ DCA)' : ''}`, 'ok');
      refreshChanges(); m.close();
      await refreshModel(`class::${name}`);
    } catch (e) { warn.style.display = 'flex'; warn.textContent = e.message; createBtn.disabled = false; createBtn.textContent = 'Create class'; }
  });
  m.foot.append(createBtn, el('span', { className: 'muted', style: 'font-size:12px', textContent: 'writes to the source YAML' }),
    el('span', { style: 'flex:1' }), el('button', { className: 'btn btn-sm', textContent: 'Cancel', onclick: m.close }));
  setTimeout(() => nameI.focus(), 50);
}
