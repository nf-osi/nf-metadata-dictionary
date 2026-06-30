/**
 * Model loader / writer for the NF metadata model.
 *
 * Reads the LinkML source the same way the Makefile merges it
 * (header.yaml + modules/props.yaml + modules/ ** / *.yaml), but keeps track of
 * which source file each class / slot / enum came from so edits can be written
 * back to the right place.
 */
import { readFileSync, writeFileSync, readdirSync, statSync, existsSync, mkdirSync } from 'fs';
import { resolve, relative, dirname, join } from 'path';
import { fileURLToPath } from 'url';
import yaml from 'js-yaml';

const __dirname = dirname(fileURLToPath(import.meta.url));
export const ROOT = resolve(__dirname, '..');
const MODULES_DIR = resolve(ROOT, 'modules');

// LinkML built-in / primitive ranges we should treat as scalar types, not nodes.
const PRIMITIVE_TYPES = new Set([
  'string', 'integer', 'float', 'double', 'decimal', 'boolean', 'date',
  'datetime', 'time', 'uri', 'uriorcurie', 'curie', 'ncname', 'objectidentifier',
  'nodeidentifier', 'jsonpointer', 'jsonpath', 'sparqlpath'
]);

// Dump options chosen to stay close to the repo's existing YAML style and keep
// git diffs as small as possible.
const DUMP_OPTS = { lineWidth: -1, noRefs: true, indent: 2, sortKeys: false, quotingType: '"' };

function walkYaml(dir, acc = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) walkYaml(full, acc);
    else if (entry.endsWith('.yaml') || entry.endsWith('.yml')) acc.push(full);
  }
  return acc;
}

/** List every source YAML file that feeds the merge, header + props first. */
export function listSourceFiles() {
  const files = [resolve(ROOT, 'header.yaml'), resolve(MODULES_DIR, 'props.yaml')];
  for (const f of walkYaml(MODULES_DIR)) {
    if (!files.includes(f)) files.push(f);
  }
  return files.filter(existsSync);
}

/**
 * Load and merge the model. Returns:
 *  { classes, slots, enums, prefixes, fileIndex }
 * where fileIndex maps `${kind}:${name}` -> repo-relative path.
 */
export function loadModel() {
  const classes = {};
  const slots = {};
  const enums = {};
  let prefixes = {};
  const fileIndex = {};

  for (const file of listSourceFiles()) {
    let doc;
    try {
      doc = yaml.load(readFileSync(file, 'utf-8'));
    } catch (e) {
      console.warn(`[model] skipping unparseable ${file}: ${e.message}`);
      continue;
    }
    if (!doc || typeof doc !== 'object') continue;
    const rel = relative(ROOT, file);
    if (doc.prefixes) prefixes = { ...prefixes, ...doc.prefixes };
    for (const [kind, target] of [['classes', classes], ['slots', slots], ['enums', enums]]) {
      if (!doc[kind]) continue;
      for (const [name, def] of Object.entries(doc[kind])) {
        target[name] = def || {};
        fileIndex[`${kind}:${name}`] = rel;
      }
    }
  }
  return { classes, slots, enums, prefixes, fileIndex };
}

/** Classify a range string as one of: enum | class | type | unknown. */
function classifyRange(range, model) {
  if (!range) return 'unknown';
  if (model.enums[range]) return 'enum';
  if (model.classes[range]) return 'class';
  if (PRIMITIVE_TYPES.has(String(range).toLowerCase())) return 'type';
  return 'unknown';
}

/** Pull the list of range targets for a slot (handles any_of unions). */
function slotRanges(def) {
  if (!def) return [];
  const out = [];
  if (def.range) out.push(def.range);
  if (Array.isArray(def.any_of)) {
    for (const a of def.any_of) if (a && a.range) out.push(a.range);
  }
  return out;
}

/**
 * Build a graph (nodes + edges) plus lightweight summaries for the UI.
 * Edges: is_a (class->class), uses (class->slot), range (slot->enum/class),
 * usage (class->enum, via slot_usage range overrides).
 */
export function buildGraph(model) {
  const nodes = [];
  const edges = [];
  const seenEdge = new Set();
  const addEdge = (source, target, type) => {
    const id = `${type}:${source}->${target}`;
    if (seenEdge.has(id)) return;
    seenEdge.add(id);
    edges.push({ data: { id, source, target, type } });
  };
  const nid = (kind, name) => `${kind}::${name}`;

  for (const [name, def] of Object.entries(model.classes)) {
    nodes.push({ data: {
      id: nid('class', name), kind: 'class', name,
      abstract: !!def.abstract,
      label: name,
      description: def.description || '',
      file: model.fileIndex[`classes:${name}`] || null,
      slotCount: (def.slots || []).length,
    }});
  }
  for (const [name, def] of Object.entries(model.slots)) {
    nodes.push({ data: {
      id: nid('slot', name), kind: 'slot', name,
      label: def.title || name,
      title: def.title || '',
      description: def.description || '',
      required: !!def.required,
      ranges: slotRanges(def),
      file: model.fileIndex[`slots:${name}`] || null,
    }});
  }
  for (const [name, def] of Object.entries(model.enums)) {
    const pv = def.permissible_values || {};
    const values = Object.entries(pv).map(([v, vdef]) => ({
      value: v,
      meaning: vdef?.meaning || null,
      source: vdef?.source || null,
      description: vdef?.description || '',
    }));
    nodes.push({ data: {
      id: nid('enum', name), kind: 'enum', name,
      label: name,
      description: def.description || '',
      file: model.fileIndex[`enums:${name}`] || null,
      valueCount: values.length,
      mappedCount: values.filter(v => v.meaning).length,
      values,
    }});
  }

  for (const [name, def] of Object.entries(model.classes)) {
    const cid = nid('class', name);
    if (def.is_a && model.classes[def.is_a]) addEdge(cid, nid('class', def.is_a), 'is_a');
    for (const slotName of def.slots || []) {
      if (model.slots[slotName]) addEdge(cid, nid('slot', slotName), 'uses');
    }
    // slot_usage range overrides connect a class directly to an enum/class
    for (const [slotName, override] of Object.entries(def.slot_usage || {})) {
      for (const r of slotRanges(override)) {
        const kind = classifyRange(r, model);
        if (kind === 'enum') addEdge(cid, nid('enum', r), 'usage');
        else if (kind === 'class') addEdge(cid, nid('class', r), 'usage');
      }
    }
  }
  for (const [name, def] of Object.entries(model.slots)) {
    const sid = nid('slot', name);
    for (const r of slotRanges(def)) {
      const kind = classifyRange(r, model);
      if (kind === 'enum') addEdge(sid, nid('enum', r), 'range');
      else if (kind === 'class') addEdge(sid, nid('class', r), 'range');
    }
  }

  return { nodes, edges };
}

/** Summary stats + the file list for the UI. */
export function modelSummary(model) {
  const enumVals = Object.values(model.enums).reduce(
    (acc, e) => {
      const pv = e.permissible_values || {};
      const vals = Object.values(pv);
      acc.total += vals.length;
      acc.mapped += vals.filter(v => v?.meaning).length;
      return acc;
    }, { total: 0, mapped: 0 });
  return {
    classes: Object.keys(model.classes).length,
    slots: Object.keys(model.slots).length,
    enums: Object.keys(model.enums).length,
    enumValues: enumVals.total,
    mappedEnumValues: enumVals.mapped,
    files: [...new Set(Object.values(model.fileIndex))].sort(),
  };
}

/**
 * Write a single entity definition back to its source file.
 * kind: 'classes' | 'slots' | 'enums'. If the entity is new, `targetFile`
 * (repo-relative) decides where it lands.
 * Returns { file, created }.
 */
export function writeEntity(kind, name, def, targetFile = null) {
  const idxKey = `${kind}:${name}`;
  const model = loadModel();
  let rel = model.fileIndex[idxKey] || targetFile;
  if (!rel) throw new Error(`No source file known for ${idxKey} and no targetFile given`);
  const abs = resolve(ROOT, rel);
  let doc = {};
  if (existsSync(abs)) {
    doc = yaml.load(readFileSync(abs, 'utf-8')) || {};
  } else {
    mkdirSync(dirname(abs), { recursive: true });
  }
  const created = !(doc[kind] && doc[kind][name]);
  if (!doc[kind]) doc[kind] = {};
  doc[kind][name] = def;
  writeFileSync(abs, yaml.dump(doc, DUMP_OPTS));
  return { file: rel, created };
}

/** Read the raw text of a repo-relative source file (for diff preview). */
export function readSourceFile(rel) {
  const abs = resolve(ROOT, rel);
  if (!existsSync(abs)) return '';
  return readFileSync(abs, 'utf-8');
}

export { classifyRange, slotRanges, DUMP_OPTS };
