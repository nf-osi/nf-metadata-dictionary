#!/usr/bin/env node
/**
 * Build script: Parses dist/NF.ttl → docs/data.json
 * Extracts templates, slots, enums, and cross-references dca-template-config.json
 */

import { readFileSync, writeFileSync, copyFileSync, existsSync, readdirSync } from 'fs';
import { Parser, Store, DataFactory } from 'n3';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import yaml from 'js-yaml';

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, '..');

// --- Namespace prefixes ---
const LINKML = 'https://w3id.org/linkml/';
const SKOS = 'http://www.w3.org/2004/02/skos/core#';
const DCTERMS = 'http://purl.org/dc/terms/';
const RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#';
const XSD = 'http://www.w3.org/2001/XMLSchema#';
const VOCAB = 'https://w3id.org/synapse/nfosi/vocab/';

const { namedNode, literal } = DataFactory;

// --- Helpers ---
function localName(uri) {
  if (!uri) return '';
  const str = typeof uri === 'string' ? uri : uri.value;
  const frag = str.lastIndexOf('#');
  const slash = str.lastIndexOf('/');
  const idx = Math.max(frag, slash);
  return idx >= 0 ? decodeURIComponent(str.slice(idx + 1)) : decodeURIComponent(str);
}

function getOne(store, s, p, o) {
  const quads = store.getQuads(s, p, o, null);
  return quads.length > 0 ? quads[0].object : null;
}

function getAll(store, s, p, o) {
  return store.getQuads(s, p, o, null).map(q => q.object);
}

function getString(store, s, p) {
  const obj = getOne(store, s, namedNode(p), null);
  return obj ? obj.value : '';
}

function getBool(store, s, p) {
  const obj = getOne(store, s, namedNode(p), null);
  if (!obj) return false;
  return obj.value === 'true' || obj.value === '1';
}

// --- Main ---
console.log('Building NF Metadata Dictionary docs...');

// 1. Load TTL
const ttlPath = resolve(rootDir, 'dist', 'NF.ttl');
if (!existsSync(ttlPath)) {
  console.error('ERROR: dist/NF.ttl not found. Run `make NF.ttl` first.');
  process.exit(1);
}

const ttlContent = readFileSync(ttlPath, 'utf-8');
const parser = new Parser();
const store = new Store();

console.log('Parsing TTL...');
const quads = parser.parse(ttlContent);
store.addQuads(quads);
console.log(`Loaded ${store.size} quads`);

// 2. Load DCA template config for public template info
const dcaPath = resolve(rootDir, 'dca-template-config.json');
let dcaTemplates = {};
if (existsSync(dcaPath)) {
  const dca = JSON.parse(readFileSync(dcaPath, 'utf-8'));
  for (const t of dca.manifest_schemas || []) {
    dcaTemplates[t.schema_name] = {
      displayName: t.display_name,
      type: t.type
    };
  }
  console.log(`Loaded ${Object.keys(dcaTemplates).length} DCA templates`);
}

// 2b. Read annotations from source YAML (stripped during TTL build)
const templateAnnotations = {};
const templateDir = resolve(rootDir, 'modules', 'Template');
if (existsSync(templateDir)) {
  for (const file of readdirSync(templateDir).filter(f => f.endsWith('.yaml'))) {
    try {
      const content = readFileSync(resolve(templateDir, file), 'utf-8');
      const data = yaml.load(content);
      if (!data?.classes) continue;
      for (const [className, classDef] of Object.entries(data.classes)) {
        if (classDef?.annotations) {
          templateAnnotations[className] = classDef.annotations;
        }
      }
    } catch (e) {
      // Skip files that can't be parsed
    }
  }
  console.log(`Read annotations for ${Object.keys(templateAnnotations).length} templates from source YAML`);
}

// 3. Extract ClassDefinitions (templates)
console.log('Extracting templates...');
const classQuads = store.getQuads(null, namedNode(RDF + 'type'), namedNode(LINKML + 'ClassDefinition'), null);
const templates = [];

for (const q of classQuads) {
  const uri = q.subject.value;
  const name = localName(uri);
  const description = getString(store, q.subject, SKOS + 'definition');
  const isAbstract = getBool(store, q.subject, LINKML + 'abstract');
  const parentObj = getOne(store, q.subject, namedNode(LINKML + 'is_a'), null);
  const parent = parentObj ? localName(parentObj) : null;

  // Get direct slots
  const slotRefs = getAll(store, q.subject, namedNode(LINKML + 'slots'), null);
  const slotNames = slotRefs.map(s => localName(s));

  // Check DCA config
  const dcaInfo = dcaTemplates[name];

  templates.push({
    name,
    uri,
    description: description.trim(),
    isAbstract,
    parent,
    slots: slotNames,
    isPublic: !!dcaInfo,
    displayName: dcaInfo?.displayName || null,
    dcaType: dcaInfo?.type || null
  });
}

templates.sort((a, b) => a.name.localeCompare(b.name));
console.log(`Found ${templates.length} templates`);

// 4. Extract SlotDefinitions (attributes)
console.log('Extracting slots...');
const allSlotQuads = store.getQuads(null, namedNode(RDF + 'type'), namedNode(LINKML + 'SlotDefinition'), null);
const slots = {};
const usageSlots = {};

for (const q of allSlotQuads) {
  const uri = q.subject.value;
  const name = localName(uri);
  const title = getString(store, q.subject, DCTERMS + 'title');
  const description = getString(store, q.subject, SKOS + 'definition');
  const isUsageSlot = getBool(store, q.subject, LINKML + 'is_usage_slot');
  const usageSlotName = getString(store, q.subject, LINKML + 'usage_slot_name');
  const required = getBool(store, q.subject, LINKML + 'required');
  const multivalued = getBool(store, q.subject, LINKML + 'multivalued');

  // Get range - direct or from any_of
  const directRange = getOne(store, q.subject, namedNode(LINKML + 'range'), null);
  const anyOfNodes = getAll(store, q.subject, namedNode(LINKML + 'any_of'), null);

  let range = null;
  let rangeUnion = null;

  if (anyOfNodes.length > 0) {
    // Union range from any_of blank nodes
    rangeUnion = [];
    for (const bnode of anyOfNodes) {
      const r = getOne(store, bnode, namedNode(LINKML + 'range'), null);
      if (r) rangeUnion.push(localName(r));
    }
    range = rangeUnion.join(' | ');
  } else if (directRange) {
    range = localName(directRange);
  }

  // Get owner (template this usage slot belongs to)
  const ownerObj = getOne(store, q.subject, namedNode(LINKML + 'owner'), null);
  const owner = ownerObj ? localName(ownerObj) : null;

  // Get domain_of
  const domainOf = getAll(store, q.subject, namedNode(LINKML + 'domain_of'), null)
    .map(d => localName(d));

  if (isUsageSlot) {
    // Usage slots are template-specific overrides
    // Store by both the full name (e.g. WGSTemplate_assay) and the base name (e.g. assay)
    const baseName = usageSlotName || name;
    if (!usageSlots[owner]) usageSlots[owner] = {};
    const overrideData = {
      range,
      rangeUnion,
      required,
      title: title || undefined,
      description: description || undefined
    };
    usageSlots[owner][baseName] = overrideData;
    usageSlots[owner][name] = overrideData; // Also index by full URI-derived name
  } else {
    slots[name] = {
      name,
      uri,
      displayName: title || name,
      description: description.trim(),
      range: range || 'string',
      rangeUnion,
      required,
      multivalued,
      domainOf
    };
  }
}

console.log(`Found ${Object.keys(slots).length} base slots, usage overrides for ${Object.keys(usageSlots).length} templates`);

// 5. Extract EnumDefinitions
console.log('Extracting enums...');
const enumMap = {};

// Find all subjects that have linkml:permissible_values
const pvQuads = store.getQuads(null, namedNode(LINKML + 'permissible_values'), null, null);
const enumUris = new Set();
for (const q of pvQuads) {
  enumUris.add(q.subject.value);
}

for (const enumUri of enumUris) {
  const enumNode = namedNode(enumUri);
  const name = localName(enumUri);
  const description = getString(store, enumNode, SKOS + 'definition');

  // Get permissible values
  const pvRefs = getAll(store, enumNode, namedNode(LINKML + 'permissible_values'), null);
  const values = [];

  for (const pvRef of pvRefs) {
    const pvName = localName(pvRef);
    const pvDef = getString(store, pvRef, SKOS + 'definition');
    const pvMeaning = getOne(store, pvRef, namedNode(LINKML + 'meaning'), null);
    const pvSource = getOne(store, pvRef, namedNode(DCTERMS + 'source'), null);

    // Get synonyms (skos:altLabel)
    const altLabels = getAll(store, pvRef, namedNode(SKOS + 'altLabel'), null)
      .map(l => l.value);

    values.push({
      name: pvName,
      definition: pvDef.trim(),
      meaning: pvMeaning ? pvMeaning.value : null,
      source: pvSource ? pvSource.value : null,
      synonyms: altLabels.length > 0 ? altLabels : undefined
    });
  }

  values.sort((a, b) => a.name.localeCompare(b.name));

  enumMap[name] = {
    name,
    uri: enumUri,
    description: description.trim(),
    values,
    valueCount: values.length
  };
}

console.log(`Found ${Object.keys(enumMap).length} enums`);

// 6. Build resolved template data (slots with usage overrides applied)
for (const template of templates) {
  const overrides = usageSlots[template.name] || {};
  template.resolvedSlots = template.slots.map(slotName => {
    // Usage slots are named like "WGSTemplate_assay" in the slots list
    // Try to find override by full name first, then by base name
    const override = overrides[slotName];
    // Resolve the base slot: for a usage slot like "WGSTemplate_assay",
    // the base slot name is the usage_slot_name (e.g. "assay")
    const baseName = override?.title
      ? slotName  // has an override, use it
      : slotName; // no override, slotName is the base
    // Look up in base slots - try the slotName directly, or strip template prefix
    let base = slots[slotName];
    if (!base) {
      // Try stripping template prefix (e.g. "WGSTemplate_assay" -> "assay")
      const underscoreIdx = slotName.indexOf('_');
      if (underscoreIdx > 0) {
        const stripped = slotName.slice(underscoreIdx + 1);
        base = slots[stripped];
      }
    }
    if (!base) {
      base = { name: slotName, displayName: slotName, description: '', range: 'string', required: false, multivalued: false };
    }

    // Determine display name: prefer override title, then base displayName
    const displayName = override?.title || base.displayName;
    // Use the base slot name (without template prefix) as the canonical name
    const canonicalName = base.name || slotName;

    return {
      name: canonicalName,
      displayName,
      description: override?.description || base.description,
      range: override?.range || base.range,
      rangeUnion: override?.rangeUnion || base.rangeUnion || null,
      required: override ? override.required : base.required,
      multivalued: base.multivalued
    };
  });
}

// 7. Build hierarchy info
const templateMap = {};
for (const t of templates) templateMap[t.name] = t;

for (const t of templates) {
  t.children = templates.filter(c => c.parent === t.name).map(c => c.name);
}

// 8. Compute templateType from hierarchy and attach annotations
function computeTemplateType(name) {
  const visited = new Set();
  let current = name;
  while (current && !visited.has(current)) {
    visited.add(current);
    if (current === 'FileBasedTemplate') return 'file';
    if (current === 'RecordBasedTemplate') return 'record';
    if (current === 'PartialTemplate') return 'partial';
    const t = templateMap[current];
    current = t ? t.parent : null;
  }
  return null;
}

for (const t of templates) {
  t.templateType = computeTemplateType(t.name) || t.dcaType || null;
  const annots = templateAnnotations[t.name];
  t.dataGranularity = annots?.dataGranularity || null;
}

// 9. Compile output
const output = {
  meta: {
    generatedAt: new Date().toISOString(),
    templateCount: templates.length,
    slotCount: Object.keys(slots).length,
    enumCount: Object.keys(enumMap).length,
    totalEnumValues: Object.values(enumMap).reduce((sum, e) => sum + e.valueCount, 0)
  },
  templates,
  slots,
  enums: enumMap
};

// 9. Write data.json
const outPath = resolve(__dirname, 'data.json');
writeFileSync(outPath, JSON.stringify(output, null, 2));
console.log(`Wrote ${outPath} (${(readFileSync(outPath).length / 1024).toFixed(0)} KB)`);

// 10. Copy NF.ttl for SPARQL explorer
const ttlDest = resolve(__dirname, 'NF.ttl');
copyFileSync(ttlPath, ttlDest);
console.log(`Copied NF.ttl to docs/`);

console.log('Build complete!');
