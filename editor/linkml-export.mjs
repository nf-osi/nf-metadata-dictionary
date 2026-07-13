/**
 * Export the editor's internal model ({classes, slots, enums}) as a LinkML schema.
 *
 * The point: a repo whose model is a schematic/DCA CSV (loaded read-only) can emit
 * valid LinkML YAML and use it to *migrate* to LinkML — after which the editor edits
 * it read/write like any other LinkML repo. Works on any loaded model regardless of
 * its source dialect (LinkML in -> LinkML out is a harmless re-serialization).
 */
import yaml from 'js-yaml';

const DUMP_OPTS = { lineWidth: -1, noRefs: true, indent: 2, sortKeys: false, quotingType: '"' };

const slugify = (s) => (s || 'model').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'model';

/** Build a LinkML schema object from the internal model. `title` seeds id/name. */
export function toLinkMLObject(model, title = 'model') {
  const name = slugify(title);

  // Collect CURIE prefixes actually used in `meaning:` so the schema declares them.
  const prefixSet = new Set();
  for (const e of Object.values(model.enums)) {
    for (const pv of Object.values(e.permissible_values || {})) {
      const m = pv?.meaning;
      if (typeof m === 'string' && m.includes(':') && !/^https?:\/\//i.test(m)) prefixSet.add(m.split(':')[0]);
    }
  }

  const slots = {};
  for (const [sn, def] of Object.entries(model.slots)) {
    const s = {};
    if (def.description) s.description = def.description;
    if (def.range) s.range = def.range;
    if (def.required) s.required = true;
    if (def.multivalued) s.multivalued = true;
    slots[sn] = s;
  }

  const classes = {};
  for (const [cn, def] of Object.entries(model.classes)) {
    const c = {};
    if (def.description) c.description = def.description;
    const cslots = (def.slots || []).filter((s) => model.slots[s]);
    if (cslots.length) c.slots = cslots;
    // keep the schematic module grouping as provenance, drop internal-only annotations
    const mod = def.annotations?.module?.value;
    if (mod) c.annotations = { module: { value: mod } };
    classes[cn] = c;
  }

  const enums = {};
  for (const [en, def] of Object.entries(model.enums)) {
    const pvs = {};
    for (const [v, vdef] of Object.entries(def.permissible_values || {})) {
      const pv = {};
      if (vdef?.description) pv.description = vdef.description;
      if (vdef?.meaning) pv.meaning = vdef.meaning;
      pvs[v] = Object.keys(pv).length ? pv : null; // LinkML allows a bare value with a null body
    }
    const e = {};
    if (def.description) e.description = def.description;
    e.permissible_values = pvs;
    enums[en] = e;
  }

  const prefixes = { linkml: 'https://w3id.org/linkml/', [name]: `https://w3id.org/${name}/` };
  return {
    id: `https://w3id.org/${name}`,
    name,
    title,
    description: `${title} — converted to LinkML by the linkml-model-editor. Starting point for migrating this model off schematic CSV.`,
    prefixes,
    // resolve OBO/semweb CURIEs (NCIT, MONDO, UBERON, …) without hand-declaring every prefix
    default_curi_maps: ['semweb_context', 'obo_context'],
    default_prefix: name,
    default_range: 'string',
    imports: ['linkml:types'],
    classes,
    slots,
    enums,
  };
}

/** LinkML schema as a YAML string. */
export function toLinkMLYaml(model, title = 'model') {
  return yaml.dump(toLinkMLObject(model, title), DUMP_OPTS);
}

export { slugify };
