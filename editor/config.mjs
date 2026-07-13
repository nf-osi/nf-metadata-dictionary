/**
 * Editor configuration — makes the app reusable across LinkML model repos
 * (NF, AD, etc.) instead of hardcoding NF specifics.
 *
 * Defaults reproduce the NF metadata dictionary exactly, so with no config file
 * present nothing changes. To reuse the editor in another repo (e.g. as a
 * submodule), drop a `model-editor.config.json` at that repo's root (or in the
 * editor/ dir) overriding any of the keys below. All paths are relative to `root`.
 */
import { existsSync, readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const EDITOR_PARENT = resolve(__dirname, '..'); // repo root when editor/ sits at the top

const DEFAULTS = {
  title: 'NF Metadata Model',
  subtitle: 'visual editor & ontology tools',
  // source dialect: 'linkml' (YAML modules) or 'schematic-csv' (a single DCA/schematic CSV).
  // schematic-csv models load read-only (visualize + ontology-gap analysis; no write-back yet).
  format: 'linkml',
  // for format 'schematic-csv': path to the compiled model CSV (e.g. 'AD.model.csv')
  csvModel: null,
  // repo root that holds the model source (relative to editor/'s parent, or absolute)
  root: '.',
  // top-level YAML files merged first (prefixes/defaults live here)
  sourceFiles: ['header.yaml'],
  // directories recursively globbed for *.yaml source
  sourceDirs: ['modules'],
  // file that declares CURIE `prefixes:` (for guardrails)
  headerFile: 'header.yaml',
  // dir whose classes are curation "templates" (for the dataType QC check); null disables
  templateDir: 'modules/Template',
  // enums whose permissible values are the valid `dataType` annotations; null disables that feature
  dataTypeEnums: ['Data', 'MetadataEnum'],
  // Data Curator App registry to also write when creating a template; null disables DCA registration
  dcaConfig: 'dca-template-config.json',
  // paths considered "model files" for the Changes diff + PR flow; null => derived
  modelPaths: null,
  // one-click build/validate commands ({python} is substituted with the resolved interpreter)
  build: {
    ttl: 'make NF.ttl',
    schemas: '{python} utils/gen-json-schema-class.py --skip-validation',
    limits: '{python} utils/check_schema_limits.py --strict',
    tests: '{python} -m pytest tests/ -q',
    lint: 'linkml-lint dist/NF.yaml',
  },
  // ontology-priority hints per enum. null => built-in NF rules (see ontology.mjs domainHint).
  // To override: [{ match: "tumor|disease", ontology: "mondo,ncit", note: "…" }, …]
  domainHints: null,
};

function loadConfig() {
  const candidates = [resolve(EDITOR_PARENT, 'model-editor.config.json'), resolve(__dirname, 'model-editor.config.json')];
  let user = {};
  for (const p of candidates) {
    if (existsSync(p)) { try { user = JSON.parse(readFileSync(p, 'utf-8')); } catch (e) { console.warn(`[config] ignoring bad ${p}: ${e.message}`); } break; }
  }
  const cfg = { ...DEFAULTS, ...user, build: { ...DEFAULTS.build, ...(user.build || {}) } };
  cfg.root = resolve(EDITOR_PARENT, cfg.root || '.');
  cfg.readOnly = cfg.format !== 'linkml'; // only LinkML write-back is wired
  if (!cfg.modelPaths) {
    cfg.modelPaths = cfg.format === 'schematic-csv'
      ? [cfg.csvModel].filter(Boolean)
      : [...cfg.sourceDirs, ...cfg.sourceFiles, cfg.dcaConfig].filter(Boolean);
  }
  return cfg;
}

export const CONFIG = loadConfig();
export const ROOT = CONFIG.root;
