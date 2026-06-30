// Lightweight guided tour — spotlight + popover, no dependencies.
const $ = (s) => document.querySelector(s);
const SEEN_KEY = 'nf-editor-tour-seen';

const STEPS = [
  {
    title: 'Welcome to the Model Editor 👋',
    body: 'A visual, local-only workspace for the NF metadata model. In ~45 seconds, here\'s everything it does. Every change you make writes straight to the source YAML in your working tree — nothing is committed.',
  },
  {
    view: 'graph', target: '.tabs',
    title: 'The workspaces',
    body: 'Switch between the <b>Graph Editor</b> (explore & edit), <b>Ontology Gaps</b> (find values you\'re missing), <b>Import Ontology</b> (pull in terms wholesale), and <b>Changes</b> (review everything different from <code>main</code> before committing).',
  },
  {
    view: 'graph', target: '#entity-search',
    title: 'Find anything',
    body: 'Search across all <span style="color:#3b6ef0;font-weight:600">classes</span>, <span style="color:#0fa371;font-weight:600">slots</span>, and <span style="color:#ef8a17;font-weight:600">enums</span> — or load a whole module. Click a result to drop it on the canvas with its neighbors.',
  },
  {
    view: 'graph', target: '.canvas-wrap',
    title: 'See how it all links',
    body: 'The graph draws <code>is_a</code>, <code>uses</code>, and <code>range</code> relationships between nodes. <b>Double-click</b> any node to expand its connections, drag to pan, scroll to zoom.',
  },
  {
    view: 'graph', target: '#inspector',
    title: 'Edit in place',
    body: 'Select a node to edit it here — slot ranges, required flags, descriptions, enum values. Saves land in the correct source file as a <b>minimal one-line diff</b>.',
  },
  {
    view: 'gaps', target: '#gaps-list',
    title: 'Fill the ontology gaps',
    body: 'These enums have values with no <code>meaning:</code> CURIE. Pick one, hit <b>Find mapping</b> on a value, and click an EBI&nbsp;OLS suggestion to write it — no copy-paste.',
  },
  {
    view: 'import', target: '.import-grid',
    title: 'Import ontology subtrees',
    body: 'Search a root term (e.g. a disease or assay), pull its descendants from OLS, pick the ones you want, and import them as a new enum or append to an existing one — with <code>meaning:</code> + <code>source:</code> filled in.',
  },
  {
    view: 'graph', target: '#tutorial-btn',
    title: 'That\'s the tour!',
    body: 'Reopen this anytime from the <b>Tutorial</b> button. Remember: review your edits with <code>git diff</code> before committing. Happy curating!',
  },
];

let idx = 0;
let spot, pop, onResize;

function buildEls() {
  if (pop) return;
  spot = document.createElement('div'); spot.className = 'tour-spot';
  pop = document.createElement('div'); pop.className = 'tour-pop';
  document.body.append(spot, pop);
}

function place(rect, hasTarget) {
  const pad = 8;
  if (hasTarget) {
    spot.style.opacity = '1';
    spot.style.left = `${rect.left - pad}px`;
    spot.style.top = `${rect.top - pad}px`;
    spot.style.width = `${rect.width + pad * 2}px`;
    spot.style.height = `${rect.height + pad * 2}px`;
    spot.style.boxShadow = '0 0 0 9999px rgba(13,18,33,.6), 0 0 0 3px var(--accent-2)';
  } else {
    // no target: tiny centered hole → full dim, no ring
    spot.style.left = `${innerWidth / 2}px`; spot.style.top = `${innerHeight / 2}px`;
    spot.style.width = '0px'; spot.style.height = '0px';
    spot.style.boxShadow = '0 0 0 9999px rgba(13,18,33,.6)';
  }

  const pr = pop.getBoundingClientRect();
  const pw = pr.width || 340, ph = pr.height || 200;
  let left, top;
  if (!hasTarget) {
    left = (innerWidth - pw) / 2; top = (innerHeight - ph) / 2;
  } else if (innerHeight - rect.bottom > ph + 24) {        // below
    top = rect.bottom + 16; left = rect.left + rect.width / 2 - pw / 2;
  } else if (rect.top > ph + 24) {                          // above
    top = rect.top - ph - 16; left = rect.left + rect.width / 2 - pw / 2;
  } else if (innerWidth - rect.right > pw + 24) {           // right
    left = rect.right + 16; top = rect.top + rect.height / 2 - ph / 2;
  } else {                                                  // left
    left = rect.left - pw - 16; top = rect.top + rect.height / 2 - ph / 2;
  }
  left = Math.max(14, Math.min(left, innerWidth - pw - 14));
  top = Math.max(14, Math.min(top, innerHeight - ph - 14));
  pop.style.left = `${left}px`; pop.style.top = `${top}px`;
}

function render() {
  const step = STEPS[idx];
  const dots = STEPS.map((_, k) => `<i class="${k === idx ? 'on' : ''}"></i>`).join('');
  const last = idx === STEPS.length - 1;
  pop.innerHTML = `
    <div class="tour-step-no">Step ${idx + 1} of ${STEPS.length}</div>
    <h4>${step.title}</h4>
    <p>${step.body}</p>
    <div class="tour-foot">
      <div class="tour-dots">${dots}</div>
      ${idx > 0 ? '<button class="btn btn-sm" data-act="back">Back</button>' : '<button class="tour-skip" data-act="skip">Skip tour</button>'}
      <button class="btn btn-sm btn-primary" data-act="next">${last ? 'Done' : 'Next →'}</button>
    </div>`;
  pop.querySelector('[data-act="next"]').onclick = () => (last ? end() : go(idx + 1));
  const back = pop.querySelector('[data-act="back"]'); if (back) back.onclick = () => go(idx - 1);
  const skip = pop.querySelector('[data-act="skip"]'); if (skip) skip.onclick = end;

  const reposition = () => {
    const t = step.target && $(step.target);
    place(t ? t.getBoundingClientRect() : null, !!t);
  };
  // allow tab switch / layout to settle, then position
  requestAnimationFrame(() => requestAnimationFrame(reposition));
  onResize = reposition;
}

function go(n) {
  idx = Math.max(0, Math.min(n, STEPS.length - 1));
  const step = STEPS[idx];
  if (step.view) {
    const tab = $(`.tab[data-view="${step.view}"]`);
    if (tab && !tab.classList.contains('active')) tab.click();
  }
  render();
}

function start() {
  buildEls();
  spot.style.display = pop.style.display = 'block';
  window.addEventListener('resize', () => onResize && onResize());
  document.addEventListener('keydown', onKey);
  go(0);
}

function end() {
  if (spot) spot.style.display = 'none';
  if (pop) pop.style.display = 'none';
  document.removeEventListener('keydown', onKey);
  try { localStorage.setItem(SEEN_KEY, '1'); } catch {}
}

function onKey(e) {
  if (e.key === 'Escape') end();
  else if (e.key === 'ArrowRight' || e.key === 'Enter') go(idx + 1);
  else if (e.key === 'ArrowLeft') go(idx - 1);
}

const btn = $('#tutorial-btn');
if (btn) btn.addEventListener('click', () => { idx = 0; start(); });
// let other code dismiss the tour (e.g. when a modal opens)
window.__nfEndTour = end;

// auto-start on first visit (after the graph has had a moment to load)
let seen = true;
try { seen = !!localStorage.getItem(SEEN_KEY); } catch {}
if (new URLSearchParams(location.search).get('tour') === 'off') seen = true;
if (!seen) setTimeout(start, 900);
