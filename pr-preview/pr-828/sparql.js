/**
 * NF Metadata Dictionary - SPARQL Explorer Module
 * Lazy-loaded when SPARQL tab is activated.
 * Uses Oxigraph WASM for in-browser SPARQL query execution.
 */

const PREFIXES = `PREFIX linkml: <https://w3id.org/linkml/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX nf: <https://w3id.org/synapse/nfosi/vocab/>
`;

const EXAMPLES = [
  {
    name: 'List all templates',
    query: `SELECT ?name ?description ?abstract WHERE {
  ?class a linkml:ClassDefinition ;
         linkml:class_uri ?uri .
  BIND(REPLACE(STR(?uri), "^.*/", "") AS ?name)
  OPTIONAL { ?class skos:definition ?description }
  OPTIONAL { ?class linkml:abstract ?abstract }
}
ORDER BY ?name`
  },
  {
    name: 'Template hierarchy',
    query: `SELECT ?child ?parent WHERE {
  ?c a linkml:ClassDefinition ;
     linkml:is_a ?p .
  BIND(REPLACE(STR(?c), "^.*/", "") AS ?child)
  BIND(REPLACE(STR(?p), "^.*/", "") AS ?parent)
}
ORDER BY ?parent ?child`
  },
  {
    name: 'Fields for a template (WGSTemplate)',
    query: `SELECT ?field ?title WHERE {
  nf:WGSTemplate linkml:slots ?slot .
  BIND(REPLACE(STR(?slot), "^.*/", "") AS ?field)
  OPTIONAL { ?slot dcterms:title ?title }
}
ORDER BY ?field`
  },
  {
    name: 'Required fields across templates',
    query: `SELECT ?template ?field WHERE {
  ?slot linkml:is_usage_slot true ;
        linkml:required true ;
        linkml:owner ?owner ;
        linkml:usage_slot_name ?field .
  BIND(REPLACE(STR(?owner), "^.*/", "") AS ?template)
}
ORDER BY ?template ?field`
  },
  {
    name: 'Enum values with ontology mappings',
    query: `SELECT ?enum ?value ?ontology WHERE {
  ?e linkml:permissible_values ?v .
  ?v linkml:meaning ?ontology .
  BIND(REPLACE(STR(?e), "^.*/", "") AS ?enum)
  BIND(REPLACE(STR(?v), "^.*/", "") AS ?value)
}
ORDER BY ?enum ?value
LIMIT 100`
  },
  {
    name: 'Slots by range type',
    query: `SELECT ?slot ?range WHERE {
  ?s a linkml:SlotDefinition ;
     linkml:range ?r .
  FILTER(!isBlank(?s))
  FILTER NOT EXISTS { ?s linkml:is_usage_slot true }
  BIND(REPLACE(STR(?s), "^.*/", "") AS ?slot)
  BIND(REPLACE(STR(?r), "^.*/", "") AS ?range)
}
ORDER BY ?range ?slot`
  },
  {
    name: 'Terms with synonyms',
    query: `SELECT ?term ?synonym WHERE {
  ?t skos:altLabel ?synonym .
  BIND(REPLACE(STR(?t), "^.*/", "") AS ?term)
}
ORDER BY ?term
LIMIT 100`
  },
  {
    name: 'Abstract vs concrete templates',
    query: `SELECT ?type (COUNT(?class) AS ?count) WHERE {
  ?class a linkml:ClassDefinition .
  OPTIONAL { ?class linkml:abstract ?abs }
  BIND(IF(BOUND(?abs) && ?abs = true, "Abstract", "Concrete") AS ?type)
}
GROUP BY ?type`
  }
];

let oxStore = null;

export async function initSparql() {
  const editor = document.getElementById('sparql-editor');
  const status = document.getElementById('sparql-status');
  const resultsDiv = document.getElementById('sparql-results');
  const runBtn = document.getElementById('sparql-run');
  const clearBtn = document.getElementById('sparql-clear');
  const examplesSelect = document.getElementById('sparql-examples');

  // Populate example queries
  for (const ex of EXAMPLES) {
    const opt = document.createElement('option');
    opt.value = ex.query;
    opt.textContent = ex.name;
    examplesSelect.appendChild(opt);
  }

  examplesSelect.addEventListener('change', () => {
    if (examplesSelect.value) editor.value = PREFIXES + '\n' + examplesSelect.value;
  });

  runBtn.addEventListener('click', runQuery);
  clearBtn.addEventListener('click', () => {
    editor.value = '';
    resultsDiv.innerHTML = '';
    status.textContent = '';
    examplesSelect.value = '';
  });

  // Allow Ctrl+Enter to run
  editor.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      runQuery();
    }
  });

  // Load Oxigraph
  status.textContent = 'Loading Oxigraph WASM...';
  try {
    const ox = await import('https://cdn.jsdelivr.net/npm/oxigraph@0.4.4/web.js');
    await ox.default();
    status.textContent = 'Loading NF.ttl...';

    const resp = await fetch('NF.ttl');
    const ttlText = await resp.text();

    oxStore = new ox.Store();
    oxStore.load(ttlText, { format: "text/turtle" });
    const size = oxStore.size;
    status.textContent = `Ready (${size.toLocaleString()} triples loaded)`;

    // Set default query
    editor.value = PREFIXES + '\n' + EXAMPLES[0].query;
  } catch (e) {
    status.textContent = 'Failed to initialize';
    resultsDiv.innerHTML = `<div class="sparql-error">Failed to load Oxigraph: ${escHtml(e.message)}\n\nNote: SPARQL Explorer requires a browser with WASM support.</div>`;
  }

  async function runQuery() {
    const queryText = editor.value.trim();
    if (!queryText) return;
    if (!oxStore) {
      resultsDiv.innerHTML = '<div class="sparql-error">Oxigraph not loaded yet</div>';
      return;
    }

    status.textContent = 'Running query...';
    const t0 = performance.now();

    try {
      const results = oxStore.query(queryText);
      const elapsed = ((performance.now() - t0) / 1000).toFixed(3);

      if (typeof results === 'boolean') {
        // ASK query
        status.textContent = `Completed in ${elapsed}s`;
        resultsDiv.innerHTML = `<p><strong>Result:</strong> ${results}</p>`;
      } else {
        // SELECT query - results is iterable of Map objects
        const rows = [];
        let cols = null;
        for (const binding of results) {
          if (!cols) cols = [...binding.keys()];
          const row = {};
          for (const [key, val] of binding) {
            row[key] = val;
          }
          rows.push(row);
        }

        if (!cols || rows.length === 0) {
          status.textContent = `0 results (${elapsed}s)`;
          resultsDiv.innerHTML = '<div class="empty-state">No results</div>';
          return;
        }

        status.textContent = `${rows.length} result${rows.length !== 1 ? 's' : ''} (${elapsed}s)`;

        const table = `<table>
          <thead><tr>${cols.map(c => `<th>${escHtml(c)}</th>`).join('')}</tr></thead>
          <tbody>${rows.map(row => `<tr>${cols.map(c => {
            const val = row[c];
            if (!val) return '<td></td>';
            const str = formatTerm(val);
            return `<td>${str}</td>`;
          }).join('')}</tr>`).join('')}</tbody>
        </table>`;
        resultsDiv.innerHTML = table;
      }
    } catch (e) {
      const elapsed = ((performance.now() - t0) / 1000).toFixed(3);
      status.textContent = `Error (${elapsed}s)`;
      resultsDiv.innerHTML = `<div class="sparql-error">${escHtml(e.message || String(e))}</div>`;
    }
  }
}

function formatTerm(term) {
  const val = term.value;
  // Shorten known namespace prefixes
  const ns = {
    'https://w3id.org/synapse/nfosi/vocab/': 'nf:',
    'https://w3id.org/linkml/': 'linkml:',
    'http://www.w3.org/2004/02/skos/core#': 'skos:',
    'http://purl.org/dc/terms/': 'dcterms:',
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#': 'rdf:',
    'http://www.w3.org/2000/01/rdf-schema#': 'rdfs:',
  };

  if (term.termType === 'NamedNode') {
    for (const [prefix, short] of Object.entries(ns)) {
      if (val.startsWith(prefix)) {
        const local = decodeURIComponent(val.slice(prefix.length));
        return escHtml(short + local);
      }
    }
    return escHtml(decodeURIComponent(val));
  }

  if (term.termType === 'Literal') {
    const text = val.length > 200 ? val.slice(0, 200) + '...' : val;
    return escHtml(text);
  }

  return escHtml(val);
}

function escHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
