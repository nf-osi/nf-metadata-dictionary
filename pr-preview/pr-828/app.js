/**
 * NF Metadata Dictionary - Main SPA Logic
 * Vanilla ES module, no framework dependencies
 */

let DATA = null;
let searchIndex = [];

// --- Init ---
async function init() {
  try {
    const resp = await fetch('data.json');
    DATA = await resp.json();
  } catch (e) {
    document.body.innerHTML = '<div class="loading">Failed to load data.json. Run the build first: <code>cd docs && npm install && node build.mjs</code></div>';
    return;
  }

  buildSearchIndex();
  initLastUpdated();
  initTabs();
  initGlobalSearch();
  initTemplates();
  initVocabulary();
  initAbout();
  handleRoute();
  window.addEventListener('hashchange', handleRoute);
}

// --- Search Index ---
function buildSearchIndex() {
  searchIndex = [];
  for (const t of DATA.templates) {
    searchIndex.push({ type: 'template', name: t.name, display: t.name, desc: t.description });
  }
  for (const s of Object.values(DATA.slots)) {
    searchIndex.push({ type: 'slot', name: s.name, display: s.displayName, desc: s.description });
  }
  for (const e of Object.values(DATA.enums)) {
    searchIndex.push({ type: 'enum', name: e.name, display: e.name, desc: `${e.valueCount} values` });
    for (const v of e.values) {
      searchIndex.push({ type: 'value', name: v.name, display: v.name, desc: v.definition, parent: e.name });
    }
  }
}

// --- Last Updated ---
function initLastUpdated() {
  const el = document.getElementById('last-updated');
  if (!el || !DATA.meta.generatedAt) return;
  const d = new Date(DATA.meta.generatedAt);
  el.textContent = 'Updated ' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// --- Tabs ---
function initTabs() {
  const btns = document.querySelectorAll('.tab-btn');
  btns.forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      activateTab(tab);
      if (tab === 'sparql') loadSparql();
    });
  });
}

function activateTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
    b.setAttribute('aria-selected', b.dataset.tab === tab);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    const isActive = p.id === `tab-${tab}`;
    p.classList.toggle('active', isActive);
    p.hidden = !isActive;
  });
}

// --- Global Search ---
function initGlobalSearch() {
  const input = document.getElementById('global-search');
  const results = document.getElementById('search-results');
  let timer = null;

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const q = input.value.trim().toLowerCase();
      if (q.length < 2) { results.hidden = true; return; }
      const matches = searchIndex.filter(item =>
        item.name.toLowerCase().includes(q) ||
        item.display.toLowerCase().includes(q) ||
        (item.desc && item.desc.toLowerCase().includes(q))
      ).slice(0, 20);

      if (matches.length === 0) {
        results.innerHTML = '<div class="search-result-item" style="color:var(--color-text-muted)">No results found</div>';
      } else {
        results.innerHTML = matches.map(m => `
          <div class="search-result-item" data-type="${m.type}" data-name="${esc(m.name)}" data-parent="${esc(m.parent || '')}">
            <span class="search-badge ${m.type}">${m.type}</span>
            <span>${esc(m.display || m.name)}</span>
          </div>
        `).join('');
      }
      results.hidden = false;
    }, 200);
  });

  results.addEventListener('click', e => {
    const item = e.target.closest('.search-result-item');
    if (!item) return;
    const type = item.dataset.type;
    const name = item.dataset.name;
    const parent = item.dataset.parent;

    if (type === 'template') location.hash = `#template/${name}`;
    else if (type === 'enum') location.hash = `#vocab/${name}`;
    else if (type === 'value') location.hash = `#vocab/${parent}`;
    else if (type === 'slot') {
      // Find a template that uses this slot and navigate there
      const t = DATA.templates.find(t => t.slots.includes(name));
      if (t) location.hash = `#template/${t.name}`;
    }
    results.hidden = true;
    input.value = '';
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('.global-search-wrapper')) results.hidden = true;
  });
}

// --- Templates ---
function initTemplates() {
  renderHierarchyTree();
  renderTemplateCards();

  document.getElementById('template-search').addEventListener('input', renderTemplateCards);
  document.getElementById('filter-type').addEventListener('change', renderTemplateCards);
  document.getElementById('filter-granularity').addEventListener('change', renderTemplateCards);
  document.getElementById('filter-abstract').addEventListener('change', renderTemplateCards);
  document.getElementById('filter-min-fields').addEventListener('input', renderTemplateCards);
  document.getElementById('back-to-templates').addEventListener('click', () => {
    location.hash = '#templates';
  });
}

function renderHierarchyTree() {
  const container = document.getElementById('hierarchy-tree');
  const templateMap = {};
  DATA.templates.forEach(t => templateMap[t.name] = t);

  // Collect all concrete (non-abstract) descendants of a template
  function getConcreteDescendants(name) {
    const result = [];
    for (const c of DATA.templates.filter(c => c.parent === name)) {
      if (!c.isAbstract) result.push(c);
      result.push(...getConcreteDescendants(c.name));
    }
    return result;
  }

  // Human-readable group labels for abstract branch nodes
  const groupLabels = {
    'Template': 'All Templates',
    'GeneticsAssayTemplate': 'Sequencing & Genetics',
    'ProteinAssayTemplate': 'Proteomics',
    'NonBiologicalAssayDataTemplate': 'Material Science',
    'BiologicalAssayDataTemplate': 'Biological Assays',
    'FileBasedTemplate': 'File-Based Data',
    'RecordBasedTemplate': 'Record-Based Data',
    'PartialTemplate': 'Partial Templates',
  };

  // Concrete templates that should render as group headers (like abstract groups)
  // because they are domain parents with children
  const concreteGroupLabels = {
    'ImagingAssayTemplate': 'Imaging',
  };

  // Render a concrete template as a group header (similar to abstract groups).
  // The template itself appears as the first clickable item under the header.
  function buildConcreteGroup(t) {
    const label = concreteGroupLabels[t.name];
    const directChildren = DATA.templates.filter(c => c.parent === t.name);
    const visibleChildren = [];
    for (const child of directChildren) {
      if (!child.isAbstract) {
        visibleChildren.push(child);
      } else {
        visibleChildren.push(...getConcreteDescendants(child.name));
      }
    }
    const sorted = visibleChildren.sort((a, b) =>
      (a.displayName || a.name).localeCompare(b.displayName || b.name)
    );

    let childHtml = `<li>
      <span class="tree-toggle">\u00A0</span>
      <span class="tree-label" data-name="${esc(t.name)}">${esc(t.name)}</span>
    </li>`;
    for (const c of sorted) {
      childHtml += buildLeaf(c);
    }

    return `<li>
      <span class="tree-toggle">\u25BC</span>
      <span class="tree-group-label">${esc(label)}</span>
      <div class="tree-children"><ul>${childHtml}</ul></div>
    </li>`;
  }

  // Render a concrete template as a leaf, with optional nested children.
  // Only shows direct children (not all descendants) to avoid duplicates.
  function buildLeaf(t) {
    // Get direct concrete children + concrete descendants of direct abstract children
    const directChildren = DATA.templates.filter(c => c.parent === t.name);
    const visibleChildren = [];
    for (const child of directChildren) {
      if (!child.isAbstract) {
        visibleChildren.push(child);
      } else {
        // Flatten through abstract intermediaries
        visibleChildren.push(...getConcreteDescendants(child.name));
      }
    }

    if (visibleChildren.length === 0) {
      return `<li>
        <span class="tree-toggle">\u00A0</span>
        <span class="tree-label" data-name="${esc(t.name)}">${esc(t.name)}</span>
      </li>`;
    }
    // Concrete template with children: show as expandable
    const sorted = visibleChildren.sort((a, b) => a.name.localeCompare(b.name));
    const childHtml = sorted.map(c => buildLeaf(c)).join('');
    return `<li>
      <span class="tree-toggle">\u25BC</span>
      <span class="tree-label" data-name="${esc(t.name)}">${esc(t.name)}</span>
      <div class="tree-children"><ul>${childHtml}</ul></div>
    </li>`;
  }

  // Build a grouped tree. For abstract nodes, collect concrete descendants
  // and flatten through intermediate abstract-only layers so users see
  // usable templates directly under meaningful group headers.
  function buildGroup(t, depth) {
    const directChildren = DATA.templates.filter(c => c.parent === t.name);
    if (directChildren.length === 0 && t.isAbstract) return '';

    // Split into sub-groups (abstract with descendants), concrete groups, and leaves
    const subGroups = [];
    const concreteGroups = [];
    const leaves = [];
    for (const child of directChildren) {
      if (child.isAbstract) {
        const desc = getConcreteDescendants(child.name);
        if (desc.length > 0) {
          subGroups.push(child);
        }
        // Skip abstract nodes with no concrete descendants
      } else if (concreteGroupLabels[child.name]) {
        concreteGroups.push(child);
      } else {
        leaves.push(child);
      }
    }

    // Keep abstract children as sub-groups only if they have an explicit
    // group label. Otherwise flatten all their concrete descendants into
    // this level so users see usable templates without wading through
    // intermediate abstract classes.
    const flattenedLeaves = [];
    const keptSubGroups = [];
    for (const sg of subGroups) {
      if (groupLabels[sg.name]) {
        keptSubGroups.push(sg);
      } else {
        flattenedLeaves.push(...getConcreteDescendants(sg.name));
      }
    }

    const allLeaves = [...leaves, ...flattenedLeaves].sort((a, b) => {
      const aName = a.displayName || a.name;
      const bName = b.displayName || b.name;
      return aName.localeCompare(bName);
    });

    // Merge abstract sub-groups and concrete groups, sorted by label
    const allSubGroupItems = [
      ...keptSubGroups.map(sg => ({ t: sg, label: groupLabels[sg.name] || humanize(sg.name), isConcrete: false })),
      ...concreteGroups.map(cg => ({ t: cg, label: concreteGroupLabels[cg.name], isConcrete: true })),
    ];
    allSubGroupItems.sort((a, b) => a.label.localeCompare(b.label));

    let inner = '';
    // Sub-groups first (abstract and concrete groups)
    for (const item of allSubGroupItems) {
      inner += item.isConcrete ? buildConcreteGroup(item.t) : buildGroup(item.t, depth + 1);
    }
    // Then remaining concrete templates as leaves
    for (const leaf of allLeaves) {
      inner += buildLeaf(leaf);
    }

    if (!inner) return '';

    const label = groupLabels[t.name] || humanize(t.name);
    return `<li>
      <span class="tree-toggle">\u25BC</span>
      <span class="tree-group-label" data-name="${esc(t.name)}">${esc(label)}</span>
      <div class="tree-children"><ul>${inner}</ul></div>
    </li>`;
  }

  // Find root templates
  const roots = DATA.templates.filter(t => !t.parent || !templateMap[t.parent]);

  // Separate: abstract roots with descendants vs standalone concrete roots
  const treeRoots = roots.filter(t => t.isAbstract && getConcreteDescendants(t.name).length > 0);
  const standaloneRoots = roots.filter(t => !t.isAbstract || getConcreteDescendants(t.name).length === 0);
  // Standalone concrete roots also include concrete roots that are parents themselves
  const concreteStandalone = standaloneRoots.filter(t => !t.isAbstract);

  // Sort so "All Templates" (Template) comes first, then others alphabetically
  treeRoots.sort((a, b) => {
    if (a.name === 'Template') return -1;
    if (b.name === 'Template') return 1;
    return (groupLabels[a.name] || a.name).localeCompare(groupLabels[b.name] || b.name);
  });

  let html = '<ul>';
  for (const root of treeRoots) {
    html += buildGroup(root, 0);
  }

  // "Other" group for standalone concrete templates without a tree parent
  if (concreteStandalone.length > 0) {
    const items = concreteStandalone.sort((a, b) => a.name.localeCompare(b.name));
    let inner = '';
    for (const t of items) {
      inner += `<li>
        <span class="tree-toggle">\u00A0</span>
        <span class="tree-label" data-name="${esc(t.name)}">${esc(t.name)}</span>
      </li>`;
    }
    html += `<li>
      <span class="tree-toggle">\u25BC</span>
      <span class="tree-group-label">Other</span>
      <div class="tree-children"><ul>${inner}</ul></div>
    </li>`;
  }
  html += '</ul>';

  container.innerHTML = html;

  container.addEventListener('click', e => {
    const toggle = e.target.closest('.tree-toggle');
    if (toggle) {
      const li = toggle.closest('li');
      const children = li.querySelector('.tree-children');
      if (children) {
        children.classList.toggle('collapsed');
        toggle.textContent = children.classList.contains('collapsed') ? '\u25B6' : '\u25BC';
      }
      return;
    }
    const label = e.target.closest('.tree-label');
    if (label) {
      location.hash = `#template/${label.dataset.name}`;
    }
    const groupLabel = e.target.closest('.tree-group-label');
    if (groupLabel && groupLabel.dataset.name) {
      location.hash = `#template/${groupLabel.dataset.name}`;
    }
  });
}

function humanize(name) {
  return name
    .replace(/Template$/, '')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
}

function renderTemplateCards() {
  const container = document.getElementById('template-cards');
  const query = document.getElementById('template-search').value.toLowerCase();
  const typeFilter = document.getElementById('filter-type').value;
  const granFilter = document.getElementById('filter-granularity').value;
  const curateOnly = document.getElementById('filter-abstract').checked;
  const minFields = parseInt(document.getElementById('filter-min-fields').value, 10) || 0;

  let filtered = DATA.templates;
  if (query) filtered = filtered.filter(t =>
    t.name.toLowerCase().includes(query) ||
    t.description.toLowerCase().includes(query)
  );
  if (typeFilter) filtered = filtered.filter(t => t.templateType === typeFilter);
  if (granFilter) filtered = filtered.filter(t => t.dataGranularity === granFilter);
  if (curateOnly) filtered = filtered.filter(t => !t.isAbstract);
  if (minFields > 0) filtered = filtered.filter(t => t.slots.length >= minFields);

  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty-state">No templates match your filters</div>';
    return;
  }

  container.innerHTML = filtered.map(t => `
    <div class="template-card" data-name="${esc(t.name)}">
      <div class="template-card-header">
        <span class="template-card-name">${esc(t.name)}</span>
      </div>
      ${t.description ? `<div class="template-card-desc">${esc(t.description)}</div>` : ''}
      <div class="template-card-fields">${t.slots.length} fields${t.parent ? ` · ${esc(t.parent)}` : ''}</div>
      <div class="template-card-meta">
        ${t.isAbstract ? '<span class="badge badge-abstract">Abstract</span>' : ''}
        ${t.templateType ? `<span class="badge badge-type">${esc(t.templateType === 'file' ? 'File-based' : t.templateType === 'record' ? 'Record-based' : t.templateType === 'partial' ? 'Partial' : t.templateType)}</span>` : ''}
        ${t.dataGranularity ? `<span class="badge badge-granularity">${esc(t.dataGranularity)}</span>` : ''}
      </div>
    </div>
  `).join('');

  container.querySelectorAll('.template-card').forEach(card => {
    card.addEventListener('click', () => {
      location.hash = `#template/${card.dataset.name}`;
    });
  });
}

function showTemplateDetail(name) {
  const t = DATA.templates.find(t => t.name === name);
  if (!t) return;

  document.getElementById('templates-list-view').hidden = true;
  document.getElementById('template-detail-view').hidden = false;

  // Highlight in tree
  document.querySelectorAll('.tree-label').forEach(l => {
    l.classList.toggle('active', l.dataset.name === name);
  });

  const content = document.getElementById('template-detail-content');
  const slots = t.resolvedSlots || [];

  content.innerHTML = `
    <div class="detail-header">
      <h2 class="detail-title">${esc(t.name)}</h2>
    </div>
    ${t.description ? `<p class="detail-desc">${esc(t.description)}</p>` : ''}
    ${t.parent ? `<p class="detail-meta">${slots.length} fields · Inherits from ${esc(t.parent)}</p>` : `<p class="detail-meta">${slots.length} fields</p>`}
    <div class="detail-badges">
      ${t.isAbstract ? '<span class="badge badge-abstract">Abstract</span>' : ''}
      ${t.templateType ? `<span class="badge badge-type">${esc(t.templateType === 'file' ? 'File-based' : t.templateType === 'record' ? 'Record-based' : t.templateType === 'partial' ? 'Partial' : t.templateType)}</span>` : ''}
      ${t.dataGranularity ? `<span class="badge badge-granularity">${esc(t.dataGranularity)}</span>` : ''}
    </div>
    ${slots.length > 0 ? `
    <div class="slot-table-wrapper">
      <div class="slot-table-header">
        <span class="slot-table-title">Fields</span>
        <input type="search" class="slot-filter" id="slot-filter" placeholder="Filter fields...">
      </div>
      <table class="slot-table">
        <thead>
          <tr>
            <th data-sort="name">Field <span class="sort-arrow"></span></th>
            <th data-sort="desc">Description <span class="sort-arrow"></span></th>
            <th data-sort="range">Type / Range <span class="sort-arrow"></span></th>
            <th data-sort="required">Required <span class="sort-arrow"></span></th>
          </tr>
        </thead>
        <tbody id="slot-table-body">
          ${renderSlotRows(slots)}
        </tbody>
      </table>
    </div>` : '<div class="empty-state">No fields defined</div>'}
  `;

  // Slot filtering
  const slotFilter = document.getElementById('slot-filter');
  if (slotFilter) {
    slotFilter.addEventListener('input', () => {
      const q = slotFilter.value.toLowerCase();
      const filtered = q ? slots.filter(s =>
        s.name.toLowerCase().includes(q) ||
        s.displayName.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q)
      ) : slots;
      document.getElementById('slot-table-body').innerHTML = renderSlotRows(filtered);
      bindRangeLinks();
    });
  }

  // Sort
  let sortCol = null, sortAsc = true;
  content.querySelectorAll('.slot-table th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (sortCol === col) sortAsc = !sortAsc;
      else { sortCol = col; sortAsc = true; }

      const sorted = [...slots].sort((a, b) => {
        let va, vb;
        if (col === 'name') { va = a.name; vb = b.name; }
        else if (col === 'desc') { va = a.description; vb = b.description; }
        else if (col === 'range') { va = a.range; vb = b.range; }
        else if (col === 'required') { va = a.required ? 1 : 0; vb = b.required ? 1 : 0; }
        if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        return sortAsc ? va - vb : vb - va;
      });
      document.getElementById('slot-table-body').innerHTML = renderSlotRows(sorted);
      bindRangeLinks();
    });
  });

  bindRangeLinks();
}

function renderSlotRows(slots) {
  return slots.map(s => {
    const rangeHtml = renderRange(s);
    return `<tr class="${s.required ? 'required' : ''}">
      <td><strong>${esc(s.displayName || s.name)}</strong>${s.displayName && s.displayName !== s.name ? `<br><small style="color:var(--color-text-muted)">${esc(s.name)}</small>` : ''}${s.multivalued ? '<br><small style="color:var(--color-accent)">multi-valued</small>' : ''}</td>
      <td>${esc(s.description)}</td>
      <td>${rangeHtml}</td>
      <td>${s.required ? 'Yes' : 'No'}</td>
    </tr>`;
  }).join('');
}

function renderRange(slot) {
  if (slot.rangeUnion && slot.rangeUnion.length > 0) {
    return '<span class="range-union">' +
      slot.rangeUnion.map(r => isEnum(r) ? `<span class="range-link" data-enum="${esc(r)}">${esc(r)}</span>` : esc(r))
        .join(' | ') +
      '</span>';
  }
  const r = slot.range || 'string';
  if (isEnum(r)) return `<span class="range-link" data-enum="${esc(r)}">${esc(r)}</span>`;
  return esc(r);
}

function isEnum(name) {
  return DATA.enums.hasOwnProperty(name);
}

function bindRangeLinks() {
  document.querySelectorAll('.range-link[data-enum]').forEach(el => {
    el.addEventListener('click', e => {
      e.stopPropagation();
      location.hash = `#vocab/${el.dataset.enum}`;
    });
  });
}

function showTemplateList() {
  document.getElementById('templates-list-view').hidden = false;
  document.getElementById('template-detail-view').hidden = true;
  document.querySelectorAll('.tree-label').forEach(l => l.classList.remove('active'));
}

// --- Vocabulary ---
function initVocabulary() {
  const select = document.getElementById('vocab-select');
  const enumNames = Object.keys(DATA.enums).sort();
  for (const name of enumNames) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = `${name} (${DATA.enums[name].valueCount})`;
    select.appendChild(opt);
  }

  select.addEventListener('change', renderVocabCards);
  document.getElementById('vocab-search').addEventListener('input', renderVocabCards);
  renderVocabCards();
}

function renderVocabCards(scrollToEnum) {
  const container = document.getElementById('vocab-cards');
  const query = document.getElementById('vocab-search').value.toLowerCase();
  const selected = document.getElementById('vocab-select').value;

  let enums = Object.values(DATA.enums);
  if (selected) enums = enums.filter(e => e.name === selected);
  if (query) {
    enums = enums.filter(e =>
      e.name.toLowerCase().includes(query) ||
      e.values.some(v =>
        v.name.toLowerCase().includes(query) ||
        (v.definition && v.definition.toLowerCase().includes(query)) ||
        (v.synonyms && v.synonyms.some(s => s.toLowerCase().includes(query)))
      )
    );
  }

  if (enums.length === 0) {
    container.innerHTML = '<div class="empty-state">No enums match your search</div>';
    return;
  }

  container.innerHTML = enums.map(e => {
    const isTarget = typeof scrollToEnum === 'string' && e.name === scrollToEnum;
    return `
    <div class="enum-card" data-name="${esc(e.name)}" id="enum-${esc(e.name)}">
      <div class="enum-card-header">
        <span class="enum-card-name">${esc(e.name)}</span>
        <span class="enum-card-count">${e.valueCount} values</span>
      </div>
      ${e.description ? `<div class="enum-card-desc">${esc(e.description)}</div>` : ''}
      <div class="enum-card-body${isTarget ? '' : ' collapsed'}">
        <ul class="enum-value-list">
          ${e.values.map(v => `
            <li class="enum-value-item">
              <span class="enum-value-name">${esc(v.name)}${v.synonyms ? v.synonyms.map(s => `<span class="synonym-tag">${esc(s)}</span>`).join('') : ''}</span>
              <span class="enum-value-def">${esc(v.definition)}</span>
              <span class="enum-value-links">
                ${v.meaning ? `<a class="ontology-link" href="${esc(resolveOntologyUri(v.meaning))}" target="_blank" rel="noopener">${esc(shortenUri(v.meaning))}</a>` : ''}
              </span>
            </li>
          `).join('')}
        </ul>
      </div>
    </div>
  `}).join('');

  // Toggle expand/collapse
  container.querySelectorAll('.enum-card-header').forEach(header => {
    header.addEventListener('click', () => {
      const body = header.closest('.enum-card').querySelector('.enum-card-body');
      body.classList.toggle('collapsed');
    });
  });

  if (typeof scrollToEnum === 'string') {
    const target = document.getElementById(`enum-${scrollToEnum}`);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function resolveOntologyUri(uri) {
  if (!uri) return '';
  // Common prefixes
  if (uri.startsWith('http')) return uri;
  // Handle CURIE-like rrid:, NCIT:, etc.
  const match = uri.match(/^(\w+):(.+)$/);
  if (match) {
    const [, prefix, local] = match;
    const prefixMap = {
      'NCIT': 'http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#',
      'rrid': 'https://scicrunch.org/resolver/',
      'OBI': 'http://purl.obolibrary.org/obo/OBI_',
      'EFO': 'http://www.ebi.ac.uk/efo/EFO_',
      'ERO': 'http://purl.obolibrary.org/obo/ERO_',
      'MI': 'http://purl.obolibrary.org/obo/MI_',
      'BTO': 'http://purl.obolibrary.org/obo/BTO_',
    };
    if (prefixMap[prefix]) return prefixMap[prefix] + local;
  }
  return uri;
}

function shortenUri(uri) {
  if (!uri) return '';
  // If already a CURIE
  if (/^\w+:/.test(uri) && !uri.startsWith('http')) return uri;
  // Try to shorten known URIs
  const patterns = [
    [/.*\/([A-Z]+)_(\d+)$/, '$1:$2'],
    [/.*#([A-Z]+\d+)$/, '$1'],
    [/.*\/([^\/]+)$/, '$1'],
  ];
  for (const [pat, rep] of patterns) {
    if (pat.test(uri)) return uri.replace(pat, rep);
  }
  return uri;
}

// --- About ---
function initAbout() {
  const stats = document.getElementById('about-stats');
  const m = DATA.meta;
  stats.innerHTML = `
    <div class="stat-card"><div class="stat-value">${m.templateCount}</div><div class="stat-label">Templates</div></div>
    <div class="stat-card"><div class="stat-value">${m.slotCount}</div><div class="stat-label">Attributes</div></div>
    <div class="stat-card"><div class="stat-value">${m.enumCount}</div><div class="stat-label">Enums</div></div>
    <div class="stat-card"><div class="stat-value">${m.totalEnumValues.toLocaleString()}</div><div class="stat-label">Total Enum Values</div></div>
  `;
}

// --- SPARQL lazy loading ---
let sparqlLoaded = false;
async function loadSparql() {
  if (sparqlLoaded) return;
  sparqlLoaded = true;
  try {
    const mod = await import('./sparql.js');
    mod.initSparql();
  } catch (e) {
    console.error('Failed to load SPARQL module:', e);
    document.getElementById('sparql-results').innerHTML =
      `<div class="sparql-error">Failed to load SPARQL module: ${esc(e.message)}</div>`;
  }
}

// --- Hash Routing ---
function handleRoute() {
  const hash = location.hash.slice(1);

  if (hash.startsWith('template/')) {
    const name = decodeURIComponent(hash.slice('template/'.length));
    activateTab('templates');
    showTemplateDetail(name);
    return;
  }

  if (hash.startsWith('vocab/')) {
    const name = decodeURIComponent(hash.slice('vocab/'.length));
    activateTab('vocabulary');
    document.getElementById('vocab-select').value = name;
    renderVocabCards(name);
    return;
  }

  if (hash === 'sparql') {
    activateTab('sparql');
    loadSparql();
    return;
  }

  if (hash === 'about') {
    activateTab('about');
    return;
  }

  // Default: templates list
  if (hash === '' || hash === 'templates') {
    activateTab('templates');
    showTemplateList();
  }
}

// --- Util ---
function esc(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Start
init();
