/**
 * Adapter: Sage "schematic" CSV data models -> the editor's internal model shape.
 *
 * Several Sage data-model repos (e.g. adknowledgeportal/data-models) describe their
 * model as a single compiled CSV (`AD.model.csv`) in the DCA/schematic dialect rather
 * than as LinkML YAML. This module reads that CSV and produces the SAME object shape
 * `loadModel()` returns for LinkML models — { classes, slots, enums, prefixes, fileIndex } —
 * so the graph, inspector, and ontology-gap tooling work unchanged.
 *
 * It is READ-ONLY: schematic models are visualized and analyzed (great for finding the
 * many unmapped values that need ontology terms), but write-back to CSV is not yet wired,
 * so the server rejects edit calls when `format` is `schematic-csv`.
 *
 * Schematic column semantics (as used across Sage models):
 *   Attribute      - the term's name
 *   Description    - human description
 *   Valid Values   - comma-separated permissible values (inline enum)
 *   DependsOn      - for a template/component: the columns (slots) it contains
 *   Required       - True/False
 *   Parent         - "ManifestColumn" (a reusable column/slot) OR the name of the
 *                    enum this row is a permissible value of (value-as-row pattern)
 *   Source         - provenance (annotation namespace or ontology token); a CURIE
 *                    here is surfaced as `meaning`, otherwise as `source`
 *   columnType     - string | string_list | number | integer | boolean
 *   IsTemplate     - True => this attribute is a manifest template (a class)
 */
import { readFileSync, existsSync } from 'fs';
import { resolve } from 'path';
import { CONFIG, ROOT } from './config.mjs';

/** Minimal RFC-4180-ish CSV parser: quoted fields, embedded commas/newlines, "" escapes. */
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  const s = text.replace(/\r\n?/g, '\n');
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inQuotes) {
      if (c === '"') {
        if (s[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field); field = '';
    } else if (c === '\n') {
      row.push(field); rows.push(row); row = []; field = '';
    } else field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}

const CURIE_RE = /^[A-Za-z][\w.]*:[A-Za-z0-9]/; // e.g. NCIT:C1234 (not a URL, not a bare word)
const isCurie = (s) => CURIE_RE.test(s) && !/^https?:\/\//i.test(s);

function splitList(v) {
  if (!v) return [];
  return v.split(',').map((x) => x.trim()).filter((x) => x && x.toLowerCase() !== 'component');
}

const PRIMITIVE = { string: 'string', string_list: 'string', number: 'float', integer: 'integer', float: 'float', boolean: 'boolean' };

/** Load a schematic CSV model into the editor's internal shape. */
export function loadSchematicModel() {
  const rel = CONFIG.csvModel;
  if (!rel) throw new Error('format is "schematic-csv" but no "csvModel" path is set in the config');
  const abs = resolve(ROOT, rel);
  if (!existsSync(abs)) throw new Error(`schematic model CSV not found: ${rel}`);

  const table = parseCsv(readFileSync(abs, 'utf-8')).filter((r) => r.some((c) => c && c.trim()));
  const header = (table[0] || []).map((h) => h.trim());
  const col = (name) => header.indexOf(name);
  const iAttr = col('Attribute');
  const rows = table.slice(1)
    .filter((r) => (r[iAttr] || '').trim())
    .map((r) => {
      const o = {};
      header.forEach((h, i) => { o[h] = (r[i] || '').trim(); });
      return o;
    });

  const byAttr = new Map();
  for (const r of rows) if (!byAttr.has(r.Attribute)) byAttr.set(r.Attribute, r);

  const isTemplate = (r) => /^(true|yes|1)$/i.test(r.IsTemplate || '') || (splitList(r.DependsOn).length > 0 && !r.Parent);

  // 1) Templates -> classes; collect the columns they depend on (slot candidates).
  const templates = rows.filter(isTemplate);
  const templateNames = new Set(templates.map((r) => r.Attribute));

  // 2) Enums: an attribute is an enum if it has inline Valid Values OR is the Parent of value-rows.
  const valueRowsByParent = new Map(); // parentAttr -> [valueRow, ...]
  for (const r of rows) {
    const p = r.Parent;
    if (!p || p === 'ManifestColumn' || templateNames.has(r.Attribute)) continue;
    if (!valueRowsByParent.has(p)) valueRowsByParent.set(p, []);
    valueRowsByParent.get(p).push(r);
  }

  const classes = {};
  const slots = {};
  const enums = {};
  const fileIndex = {};

  const enumNames = new Set();
  for (const r of rows) {
    const inline = splitList(r['Valid Values']);
    const children = valueRowsByParent.get(r.Attribute) || [];
    if (!inline.length && !children.length) continue;
    enumNames.add(r.Attribute);
    const pv = {};
    for (const v of inline) pv[v] = pv[v] || { description: '' };
    for (const cr of children) {
      const src = cr.Source || '';
      pv[cr.Attribute] = {
        description: cr.Description || '',
        ...(isCurie(src) ? { meaning: src } : src ? { source: src } : {}),
      };
    }
    enums[r.Attribute] = { description: r.Description || '', permissible_values: pv };
    fileIndex[`enums:${r.Attribute}`] = rel;
  }

  // 3) Slots: manifest columns + any attribute referenced by a template's DependsOn,
  //    excluding templates themselves and pure value-rows.
  const slotNames = new Set();
  for (const r of rows) if (r.Parent === 'ManifestColumn') slotNames.add(r.Attribute);
  for (const t of templates) for (const dep of splitList(t.DependsOn)) slotNames.add(dep);
  for (const name of slotNames) {
    if (templateNames.has(name)) continue;
    const r = byAttr.get(name) || { Attribute: name };
    const range = enumNames.has(name) ? name : (PRIMITIVE[r.columnType] || 'string');
    slots[name] = {
      title: name,
      description: r.Description || '',
      required: /^(true|yes|1)$/i.test(r.Required || ''),
      range,
      ...((r.columnType || '').endsWith('_list') ? { multivalued: true } : {}),
    };
    fileIndex[`slots:${name}`] = rel;
  }

  // 4) Classes from templates; slots = DependsOn (minus Component/value tokens we know).
  for (const t of templates) {
    const deps = splitList(t.DependsOn).filter((d) => slots[d] || enumNames.has(d));
    classes[t.Attribute] = {
      description: t.Description || '',
      slots: deps,
      annotations: { ...(t.module ? { module: { value: t.module } } : {}), sourceFormat: { value: 'schematic-csv' } },
    };
    fileIndex[`classes:${t.Attribute}`] = rel;
  }

  return { classes, slots, enums, prefixes: {}, fileIndex };
}
