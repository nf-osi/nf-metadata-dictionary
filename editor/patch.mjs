/**
 * Surgical, line-based YAML patching.
 *
 * The source modules are hand-formatted with varying style (single vs. double
 * quotes, indented vs. flush sequences). A full js-yaml re-dump would reformat
 * whole files and bury a one-line change in 90 lines of noise. These helpers
 * instead navigate by indentation and touch only the lines that actually change,
 * so `git diff` stays honest.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { resolve, dirname } from 'path';
import { ROOT } from './model.mjs';

const indentOf = (line) => line.match(/^(\s*)/)[0].length;
const isBlank = (line) => line.trim() === '';
const isComment = (line) => line.trim().startsWith('#');
const isListItem = (line) => line.trim().startsWith('- ') || line.trim() === '-';

/** Extract the (unquoted) key from a `key:` line, else null. */
function keyOf(line) {
  const t = line.trim();
  if (!t || t.startsWith('#') || t.startsWith('-')) return null;
  let m;
  if ((m = t.match(/^'((?:[^']|'')*)'\s*:(?:\s|$)/))) return m[1].replace(/''/g, "'");
  if ((m = t.match(/^"((?:[^"\\]|\\.)*)"\s*:(?:\s|$)/))) { try { return JSON.parse('"' + m[1] + '"'); } catch { return m[1]; } }
  if ((m = t.match(/^([^:]+?)\s*:(?:\s|$)/))) return m[1].trim();
  return null;
}

/** End (exclusive) of the block owned by the key at `keyIdx`. */
function blockEnd(lines, keyIdx) {
  const base = indentOf(lines[keyIdx]);
  let i = keyIdx + 1;
  for (; i < lines.length; i++) {
    if (isBlank(lines[i]) || isComment(lines[i])) continue;
    if (indentOf(lines[i]) <= base) break;
  }
  // back up over trailing blanks/comments so they belong to the next sibling
  let end = i;
  while (end > keyIdx + 1 && (isBlank(lines[end - 1]) || isComment(lines[end - 1]))) end--;
  return end;
}

/** Indentation shared by the direct children of the key at `keyIdx` (or null). */
function childIndent(lines, keyIdx) {
  const base = indentOf(lines[keyIdx]);
  const end = blockEnd(lines, keyIdx);
  for (let i = keyIdx + 1; i < end; i++) {
    if (isBlank(lines[i]) || isComment(lines[i])) continue;
    if (indentOf(lines[i]) > base) return indentOf(lines[i]);
  }
  return null;
}

/** Find a top-level key line index (indent 0). */
function findTopKey(lines, name) {
  for (let i = 0; i < lines.length; i++) {
    if (indentOf(lines[i]) === 0 && keyOf(lines[i]) === name) return i;
  }
  return -1;
}

/** Find a direct child key of the block at `parentIdx`. */
function findChild(lines, parentIdx, name) {
  const ci = childIndent(lines, parentIdx);
  if (ci == null) return -1;
  const end = blockEnd(lines, parentIdx);
  for (let i = parentIdx + 1; i < end; i++) {
    if (indentOf(lines[i]) === ci && keyOf(lines[i]) === name) return i;
  }
  return -1;
}

/** Resolve a path of keys (top-level first) to the deepest key's line index. */
function findPath(lines, segs) {
  let idx = findTopKey(lines, segs[0]);
  for (let s = 1; s < segs.length && idx >= 0; s++) idx = findChild(lines, idx, segs[s]);
  return idx;
}

// A plain scalar is safe unquoted unless it trips a YAML indicator. Keep the
// common cases (prose descriptions, CURIEs, URLs) bare to match repo style.
const YAML_RESERVED = /^(true|false|yes|no|on|off|null|~|-?\d+(\.\d+)?([eE][+-]?\d+)?)$/i;
function needsQuote(s) {
  if (s === '') return true;
  if (/[\n\t]/.test(s)) return true;
  if (s !== s.trim()) return true;                 // leading/trailing space
  if (/^[!&*?|>%@`"'#,\[\]{}]/.test(s)) return true; // starts with an indicator
  if (/^[-:?]\s/.test(s)) return true;             // "- ", ": ", "? "
  if (/:(\s|$)/.test(s)) return true;              // colon followed by space/end (key/value ambiguity)
  if (/\s#/.test(s)) return true;                  // space before comment marker
  if (YAML_RESERVED.test(s)) return true;          // would parse as bool/number/null
  return false;
}
function fmtScalar(value) {
  if (typeof value === 'boolean') return String(value);
  if (typeof value === 'number') return String(value);
  const s = String(value);
  return needsQuote(s) ? "'" + s.replace(/'/g, "''") + "'" : s;
}

// Enum value keys commonly contain spaces, which is fine unquoted; only quote
// when an actual YAML indicator would break key parsing.
function quoteKey(k) {
  return needsQuote(k) ? "'" + k.replace(/'/g, "''") + "'" : k;
}

function load(rel) {
  const abs = resolve(ROOT, rel);
  return { abs, text: existsSync(abs) ? readFileSync(abs, 'utf-8') : null };
}
function save(abs, lines) {
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, lines.join('\n'));
}

/**
 * Set (or insert) a single scalar child field on the entity at `segs`.
 * Returns { changed, action }.
 */
export function setScalarField(rel, segs, field, value) {
  const { abs, text } = load(rel);
  if (text == null) throw new Error(`file not found: ${rel}`);
  const trailingNL = text.endsWith('\n');
  const lines = text.replace(/\n$/, '').split('\n');
  const parentIdx = findPath(lines, segs);
  if (parentIdx < 0) throw new Error(`path not found: ${segs.join(' > ')}`);
  const fieldIdx = findChild(lines, parentIdx, field);
  const newLine = (indent) => ' '.repeat(indent) + `${field}: ${fmtScalar(value)}`;

  let action;
  if (fieldIdx >= 0) {
    const indent = indentOf(lines[fieldIdx]);
    if (lines[fieldIdx] === newLine(indent)) return { changed: false, action: 'noop' };
    lines[fieldIdx] = newLine(indent);
    action = 'updated';
  } else {
    const ci = childIndent(lines, parentIdx);
    const indent = ci != null ? ci : indentOf(lines[parentIdx]) + 2;
    lines.splice(parentIdx + 1, 0, newLine(indent));
    action = 'inserted';
  }
  save(abs, trailingNL ? [...lines, ''] : lines);
  return { changed: true, action };
}

/** Render a permissible-value block as text lines at the given value indent. */
function renderValue(value, fields, valIndent) {
  const fIndent = valIndent + 2;
  const out = [' '.repeat(valIndent) + `${quoteKey(value)}:`];
  for (const [k, v] of Object.entries(fields)) {
    if (v == null || v === '') continue;
    if (Array.isArray(v)) {
      if (!v.length) continue;
      out.push(' '.repeat(fIndent) + `${k}:`);
      // flush block sequence (matches repo style: dash aligned with the key)
      for (const item of v) out.push(' '.repeat(fIndent) + `- ${fmtScalar(item)}`);
    } else {
      out.push(' '.repeat(fIndent) + `${k}: ${fmtScalar(v)}`);
    }
  }
  return out;
}

/**
 * Append permissible values to an existing enum. Skips values already present.
 * `values` = [{ value, description?, meaning?, source? }]. Returns { added: [...] }.
 */
export function addEnumValues(rel, enumName, values) {
  const { abs, text } = load(rel);
  if (text == null) throw new Error(`file not found: ${rel}`);
  const trailingNL = text.endsWith('\n');
  const lines = text.replace(/\n$/, '').split('\n');
  const pvIdx = findPath(lines, ['enums', enumName, 'permissible_values']);
  if (pvIdx < 0) throw new Error(`permissible_values not found for enum ${enumName}`);
  let valIndent = childIndent(lines, pvIdx);
  if (valIndent == null) valIndent = indentOf(lines[pvIdx]) + 2;

  const existing = new Set();
  const end = blockEnd(lines, pvIdx);
  for (let i = pvIdx + 1; i < end; i++) {
    if (indentOf(lines[i]) === valIndent) { const k = keyOf(lines[i]); if (k) existing.add(k); }
  }

  const added = [];
  const newLines = [];
  for (const v of values) {
    if (existing.has(v.value)) continue;
    newLines.push(...renderValue(v.value, { description: v.description, meaning: v.meaning, source: v.source, aliases: v.aliases }, valIndent));
    added.push(v.value);
  }
  if (!newLines.length) return { added: [] };
  lines.splice(end, 0, ...newLines);
  save(abs, trailingNL ? [...lines, ''] : lines);
  return { added };
}

/**
 * Create a new enum (appended to an existing `enums:` block, or a new file).
 * `values` = [{ value, description?, meaning?, source? }].
 */
export function createEnum(rel, enumName, { description = '', values = [] } = {}) {
  const { abs, text } = load(rel);
  const enumIndent = 2, fieldIndent = 4, valIndent = 6;
  const body = [];
  body.push(' '.repeat(enumIndent) + `${quoteKey(enumName)}:`);
  if (description) body.push(' '.repeat(fieldIndent) + `description: ${fmtScalar(description)}`);
  body.push(' '.repeat(fieldIndent) + `permissible_values:`);
  for (const v of values) {
    body.push(...renderValue(v.value, { description: v.description, meaning: v.meaning, source: v.source }, valIndent));
  }

  if (text == null) {
    save(abs, ['enums:', ...body, '']);
    return { created: true, file: rel };
  }
  const trailingNL = text.endsWith('\n');
  const lines = text.replace(/\n$/, '').split('\n');
  const enumsIdx = findTopKey(lines, 'enums');
  if (enumsIdx < 0) {
    // append a fresh enums: block
    const add = (lines.length && !isBlank(lines[lines.length - 1])) ? ['', 'enums:', ...body] : ['enums:', ...body];
    const out = [...lines, ...add];
    save(abs, trailingNL ? [...out, ''] : out);
  } else {
    if (findChild(lines, enumsIdx, enumName) >= 0) throw new Error(`enum ${enumName} already exists in ${rel}`);
    const end = blockEnd(lines, enumsIdx);
    lines.splice(end, 0, ...body);
    save(abs, trailingNL ? [...lines, ''] : lines);
  }
  return { created: true, file: rel };
}

/**
 * Create a new class (appended to an existing `classes:` block, or a new file).
 * def = { is_a, description, abstract, slots:[], annotations:{...} }
 */
export function createClass(rel, name, def = {}) {
  const ci = 2, fi = 4;
  const body = [' '.repeat(ci) + `${quoteKey(name)}:`];
  if (def.is_a) body.push(' '.repeat(fi) + `is_a: ${fmtScalar(def.is_a)}`);
  if (def.abstract) body.push(' '.repeat(fi) + `abstract: true`);
  if (def.description) body.push(' '.repeat(fi) + `description: ${fmtScalar(def.description)}`);
  const a = def.annotations || {};
  const aLines = [];
  for (const k of ['required', 'requiresComponent', 'templateUsage', 'dataGranularity']) {
    if (a[k] !== undefined && a[k] !== null && a[k] !== '') aLines.push(' '.repeat(fi + 2) + `${k}: ${fmtScalar(a[k])}`);
  }
  const tf = a.templateFor || {};
  const tfLines = [];
  for (const k of ['dataType', 'assay']) {
    if (Array.isArray(tf[k]) && tf[k].length) {
      tfLines.push(' '.repeat(fi + 4) + `${k}:`);
      for (const v of tf[k]) tfLines.push(' '.repeat(fi + 4) + `- ${fmtScalar(v)}`);
    }
  }
  if (aLines.length || tfLines.length) {
    body.push(' '.repeat(fi) + `annotations:`);
    body.push(...aLines);
    if (tfLines.length) { body.push(' '.repeat(fi + 2) + `templateFor:`); body.push(...tfLines); }
  }
  if (Array.isArray(def.slots) && def.slots.length) {
    body.push(' '.repeat(fi) + `slots:`);
    for (const s of def.slots) body.push(' '.repeat(fi) + `- ${fmtScalar(s)}`);
  }

  const { abs, text } = load(rel);
  if (text == null) { save(abs, ['classes:', ...body, '']); return { created: true, file: rel }; }
  const trailingNL = text.endsWith('\n');
  const lines = text.replace(/\n$/, '').split('\n');
  const idx = findTopKey(lines, 'classes');
  if (idx < 0) {
    const add = (lines.length && !isBlank(lines[lines.length - 1])) ? ['', 'classes:', ...body] : ['classes:', ...body];
    const out = [...lines, ...add];
    save(abs, trailingNL ? [...out, ''] : out);
  } else {
    if (findChild(lines, idx, name) >= 0) throw new Error(`class ${name} already exists in ${rel}`);
    const end = blockEnd(lines, idx);
    lines.splice(end, 0, ...body);
    save(abs, trailingNL ? [...lines, ''] : lines);
  }
  return { created: true, file: rel };
}

/** Append one entry to the manifest_schemas array in dca-template-config.json (minimal diff). */
export function addDcaEntry(displayName, schemaName, type = 'file') {
  const rel = 'dca-template-config.json';
  const { abs, text } = load(rel);
  if (text == null) throw new Error('dca-template-config.json not found');
  const lines = text.split('\n');
  const startRe = /"manifest_schemas"\s*:\s*\[/;
  let start = lines.findIndex((l) => startRe.test(l));
  if (start < 0) throw new Error('manifest_schemas not found');
  // find the array close `]` after start
  let close = -1;
  for (let i = start + 1; i < lines.length; i++) { if (/^\s*\]/.test(lines[i])) { close = i; break; } }
  if (close < 0) throw new Error('could not find manifest_schemas close');
  if (lines.slice(start, close).some((l) => l.includes(`"schema_name": "${schemaName}"`))) return { added: false, file: rel };
  // ensure previous entry ends with a comma
  for (let i = close - 1; i > start; i--) { if (lines[i].trim()) { if (!lines[i].trimEnd().endsWith(',')) lines[i] = lines[i].replace(/\s*$/, ',') ; break; } }
  const entry = `      {"display_name": ${JSON.stringify(displayName)}, "schema_name": ${JSON.stringify(schemaName)}, "type": ${JSON.stringify(type)}}`;
  lines.splice(close, 0, entry);
  save(abs, lines);
  return { added: true, file: rel };
}

/** Append an item to a block sequence at `segs` (e.g. a class `slots:` list). */
export function addListItem(rel, segs, item) {
  const { abs, text } = load(rel);
  if (text == null) throw new Error(`file not found: ${rel}`);
  const trailingNL = text.endsWith('\n');
  const lines = text.replace(/\n$/, '').split('\n');
  const keyIdx = findPath(lines, segs);
  if (keyIdx < 0) throw new Error(`path not found: ${segs.join(' > ')}`);
  const end = blockEnd(lines, keyIdx);
  // detect existing list-item indent & whether item already present
  let itemIndent = null;
  for (let i = keyIdx + 1; i < end; i++) {
    if (isListItem(lines[i])) {
      itemIndent = indentOf(lines[i]);
      if (lines[i].trim().replace(/^-\s*/, '') === String(item)) return { changed: false };
    }
  }
  if (itemIndent == null) itemIndent = indentOf(lines[keyIdx]); // flush sequence (repo default)
  lines.splice(end, 0, ' '.repeat(itemIndent) + `- ${item}`);
  save(abs, trailingNL ? [...lines, ''] : lines);
  return { changed: true };
}

/**
 * Edit a slot's contextual override inside a class's `slot_usage`.
 *   ranges:   array of range names — 1 => `range:`, >1 => `any_of:`; [] / undefined => leave range untouched
 *   required: true | false (set) | null (remove the override) | undefined (leave untouched)
 * Only the range/any_of/required lines are touched; other keys (e.g. ifabsent) are preserved.
 * Empties (slot entry / slot_usage block) are cleaned up.
 */
export function setSlotUsage(rel, className, slot, { ranges, required } = {}) {
  const { abs, text } = load(rel);
  if (text == null) throw new Error(`file not found: ${rel}`);
  const trailingNL = text.endsWith('\n');
  const lines = text.replace(/\n$/, '').split('\n');

  const classesIdx = findTopKey(lines, 'classes');
  if (classesIdx < 0) throw new Error(`no classes: block in ${rel}`);
  const classIdx = findChild(lines, classesIdx, className);
  if (classIdx < 0) throw new Error(`class ${className} not found in ${rel}`);
  const cfi = childIndent(lines, classIdx) ?? indentOf(lines[classIdx]) + 2;

  let suIdx = findChild(lines, classIdx, 'slot_usage');
  if (suIdx < 0) { const end = blockEnd(lines, classIdx); lines.splice(end, 0, ' '.repeat(cfi) + 'slot_usage:'); suIdx = end; }
  const si = childIndent(lines, suIdx) ?? indentOf(lines[suIdx]) + 2; // slot-entry indent
  const fi = si + 2;                                                  // field indent within an entry

  let slotIdx = findChild(lines, suIdx, slot);
  if (slotIdx < 0) { const end = blockEnd(lines, suIdx); lines.splice(end, 0, ' '.repeat(si) + `${quoteKey(slot)}:`); slotIdx = end; }

  if (ranges && ranges.length) {
    const rm = [];
    const rIdx = findChild(lines, slotIdx, 'range'); if (rIdx >= 0) rm.push([rIdx, rIdx + 1]);
    const aIdx = findChild(lines, slotIdx, 'any_of'); if (aIdx >= 0) rm.push([aIdx, blockEnd(lines, aIdx)]);
    rm.sort((a, b) => b[0] - a[0]).forEach(([s, e]) => lines.splice(s, e - s));
    slotIdx = findChild(lines, suIdx, slot);
    const ins = [];
    if (ranges.length > 1) { ins.push(' '.repeat(fi) + 'any_of:'); ranges.forEach((r) => ins.push(' '.repeat(fi + 2) + `- range: ${fmtScalar(r)}`)); }
    else ins.push(' '.repeat(fi) + `range: ${fmtScalar(ranges[0])}`);
    lines.splice(slotIdx + 1, 0, ...ins);
  }
  if (required !== undefined) {
    slotIdx = findChild(lines, suIdx, slot);
    const qIdx = findChild(lines, slotIdx, 'required');
    if (required === null) { if (qIdx >= 0) lines.splice(qIdx, 1); }
    else { const ln = ' '.repeat(fi) + `required: ${required === true || required === 'true'}`; if (qIdx >= 0) lines[qIdx] = ln; else lines.splice(slotIdx + 1, 0, ln); }
  }
  // prune emptied entry / block
  slotIdx = findChild(lines, suIdx, slot);
  if (slotIdx >= 0 && childIndent(lines, slotIdx) == null) lines.splice(slotIdx, 1);
  suIdx = findChild(lines, classIdx, 'slot_usage');
  if (suIdx >= 0 && childIndent(lines, suIdx) == null) lines.splice(suIdx, 1);

  save(abs, trailingNL ? [...lines, ''] : lines);
  return { ok: true };
}

export { keyOf, findPath, findChild, blockEnd, childIndent };
