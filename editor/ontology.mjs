/**
 * Thin client for the EBI Ontology Lookup Service (OLS4).
 * No API key required. Used for term suggestions (gap-filling) and for
 * pulling ontology subsets wholesale.
 */
const OLS = 'https://www.ebi.ac.uk/ols4/api';

async function getJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`OLS ${res.status} for ${url}`);
  return res.json();
}

function normTerm(doc) {
  const syn = doc.synonym || doc.obo_synonym || [];
  return {
    label: doc.label,
    iri: doc.iri,
    curie: doc.obo_id || doc.short_form || null,
    ontology: doc.ontology_name || doc.ontology_prefix || null,
    description: Array.isArray(doc.description) ? doc.description.join(' ') : (doc.description || ''),
    synonyms: (Array.isArray(syn) ? syn : [syn]).map((s) => (typeof s === 'string' ? s : s && (s.label || s.name || s.value))).filter(Boolean),
    hasChildren: !!doc.has_children,
    obsolete: !!doc.is_obsolete,
  };
}

/** Does this term actually have children? Probes the hierarchy (the search
 *  index's has_children flag is unreliable, e.g. for NCIT). */
export async function hasChildren({ ontology, iri } = {}) {
  if (!ontology || !iri) return false;
  try {
    const encoded = encodeURIComponent(encodeURIComponent(iri));
    const data = await getJson(`${OLS}/ontologies/${ontology.toLowerCase()}/terms/${encoded}/children?size=1`);
    return (data?._embedded?.terms || []).length > 0;
  } catch { return false; }
}

/**
 * Free-text search. ontology is optional (comma-separated lowercase prefixes).
 * branchesOnly=true keeps only terms that actually have children — for picking a
 * root to pull a subset under (a leaf has nothing beneath it). Because the search
 * index's has_children is unreliable, each candidate is probed for real children.
 */
export async function searchOntology({ q, ontology = '', rows = 12, exact = false, branchesOnly = false } = {}) {
  const params = new URLSearchParams({ q, rows: String(branchesOnly ? 30 : rows) });
  if (ontology) params.set('ontology', ontology.toLowerCase());
  if (exact) params.set('exact', 'true');
  params.set('fieldList', 'iri,label,obo_id,short_form,ontology_name,description,synonym,has_children,is_obsolete');
  const data = await getJson(`${OLS}/search?${params}`);
  let out = (data?.response?.docs || []).map(normTerm).filter(t => !t.obsolete);
  if (branchesOnly) {
    const probed = await Promise.all(out.map(async (t) => ({ t, ok: await hasChildren({ ontology: t.ontology, iri: t.iri }) })));
    out = probed.filter((p) => p.ok).map((p) => p.t).slice(0, rows);
  }
  return out;
}

/**
 * Domain hint for an enum: which ontologies to scope a search to, following the
 * repo's sourcing conventions (CONTRIBUTING.md). Returns { ontology, note }.
 */
export function domainHint(enumName = '') {
  const n = enumName.toLowerCase();
  const rules = [
    [/tumor|diagnos|disease|cancer|carcinoma|sarcoma|glioma|neoplasm|manifest|syndrome/, 'mondo,ncit', 'MONDO/OncoTree preferred for diseases & tumors'],
    [/cell.?line/, 'clo,cl,ncit', 'Cell lines often use Cellosaurus (rrid:CVCL_…) — paste a CURIE if OLS lacks it'],
    [/cell|celltype/, 'cl,ncit', 'CL (Cell Ontology) for cell types'],
    [/species|organism|taxon/, 'ncbitaxon', 'NCBI Taxonomy for species'],
    [/tissue|bodypart|body.?part|organ|anatom|specimen/, 'uberon,bto,ncit', 'UBERON/BTO for anatomy & tissues'],
    [/file.?format|format/, 'edam,ncit', 'EDAM for file formats'],
    [/platform|instrument|device|sequenc.*platform/, 'obi,ncit', 'OBI/NCIT for platforms & instruments'],
    [/assay|method|protocol|technique/, 'obi,efo,ncit,bao', 'OBI/EFO/NCIT for assays & methods'],
    [/unit/, 'uo', 'UO (Units of measurement)'],
    [/antibody|reagent|geneticreagent/, 'ncit,obi', 'NCIT/OBI for reagents'],
    [/drug|compound|chemic|therap/, 'ncit,chebi', 'NCIT/ChEBI for drugs & compounds'],
    [/gene|genotype/, 'ncit,so', 'NCIT/SO for genes & genotypes'],
    [/organization|institution|funder|center/, '', 'Organizations rarely have ontology terms — ROR IDs go in source:'],
    [/phenotyp|behavior/, 'hp,ncit', 'HP/NCIT for phenotypes'],
  ];
  for (const [re, ontology, note] of rules) if (re.test(n)) return { ontology, note };
  return { ontology: '', note: 'Searching all ontologies' };
}

/**
 * Fetch descendants (or direct children) of a term, for wholesale import.
 * `ontology` is the lowercase prefix (e.g. "ncit"); `iri` is the full term IRI.
 */
export async function getDescendants({ ontology, iri, direct = false, size = 200 } = {}) {
  const encoded = encodeURIComponent(encodeURIComponent(iri));
  const rel = direct ? 'children' : 'hierarchicalDescendants';
  const url = `${OLS}/ontologies/${ontology.toLowerCase()}/terms/${encoded}/${rel}?size=${size}`;
  const data = await getJson(url);
  const terms = data?._embedded?.terms || [];
  return terms.map(normTerm).filter(t => !t.obsolete);
}

/** Resolve a single term by IRI (used to confirm a chosen root before import). */
export async function getTerm({ ontology, iri } = {}) {
  const encoded = encodeURIComponent(encodeURIComponent(iri));
  const url = `${OLS}/ontologies/${ontology.toLowerCase()}/terms/${encoded}`;
  return normTerm(await getJson(url));
}

/** Direct parents of a term — used to jump to a branch root ("find siblings"). */
export async function getParents({ ontology, iri } = {}) {
  const encoded = encodeURIComponent(encodeURIComponent(iri));
  const url = `${OLS}/ontologies/${ontology.toLowerCase()}/terms/${encoded}/parents`;
  const data = await getJson(url);
  return (data?._embedded?.terms || []).map(normTerm).filter((t) => !t.obsolete);
}
