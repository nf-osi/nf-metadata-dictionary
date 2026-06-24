# Search Management Canonical Example

## Purpose

This document provides an overview of the Synapse search management configuration and how it relates to the data model.

The NF metadata model is the source of truth for domain terminology: canonical labels, controlled values, and documented aliases. **Synapse search configuration is a downstream deployment artifact built from that terminology.**

In practice:

1. LinkML schema files *already* define `aliases`.
2. A generation step compiles relevant aliases into a (JSON) Synapse search resource called `SynonymSet`. `SynonymSet`s (there can be multiple) are registered to an org just like how current JSON schemas are registered today.
3. Other search resources, `TextAnalyzer` and `SearchConfiguration`, reference `SynonymSet` to control search behavior.
4. The resulting configuration is bound in Synapse where search behavior should apply.

## Test Examples

- Synonym set fixture (`synonym_graph`): [synonym_set_nf_domain.json](/tests/search/synonym_set_nf_domain.json)
- Synonym set fixture (`rules`): [synonym_set_nf_rules.json](/tests/search/synonym_set_nf_rules.json)
- Text analyzer fixture: [text_analyzer_standard_with_nf_synonyms.json](/tests/search/text_analyzer_standard_with_nf_synonyms.json)

## Registering a Synonym Set

Use `utils/register-synonyms.py` to register or update a `SynonymSet`. It resolves the live `id` and `etag` automatically (matching by `name`, or pass `--synonym-set-id`), then issues the `PUT /search/synonym/set/{id}` update (or a `POST` create with `--create`). Auth comes from `SYNAPSE_AUTH_TOKEN` (needs the `modify` scope).

```bash
export SYNAPSE_AUTH_TOKEN=<token>
python utils/register-synonyms.py --file tests/search/synonym_set_nf_domain.json
# --dry-run to preview, --create to make a new set
```

## Implementation Note

The JSON files above are intentionally minimal test fixtures. They are useful as understandable examples and for verifying the Synapse search-management, but they are not yet a complete source for NF search synonyms.

**TODO:** We will need a workflow step that compiles known aliases from the schema into the synonym format required by the Synapse search configuration. For example, `modules/Assay/Assay.yaml` already records aliases for `next-generation sequencing`, including `NGS` and `next generation sequencing`. Those documented aliases should feed the generated synonym configuration rather than being maintained manually only in standalone test fixtures.

One caveat: if the target field uses the OpenSearch `standard` analyzer, punctuation and common delimiters are already split during analysis. In that case, a spacing variant like `next generation sequencing` may be redundant for search relative to `next-generation sequencing`, while a true alias like `NGS` is still useful. **The eventual synonym-compilation script should account for this so analyzer-equivalent variants do not add unnecessary synonym rules.**

## Canonical Example

### Organization Prerequisite

Reference:
- [`POST /schema/organization`](https://rest-docs.synapse.org/rest/POST/schema/organization.html)
- [`CreateOrganizationRequest`](https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/schema/CreateOrganizationRequest.html)
- [`Organization`](https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/schema/Organization.html)

Before creating a `SynonymSet`, `TextAnalyzer`, or related search-management resource, the organization must already exist.

In our case, `org.synapse.nf` already exists, so organization creation is not shown. (If you are doing this for a different organization, first read those REST reference pages.)

### 1. Synonym Set

Reference:
- [`SynonymSet`](https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/SynonymSet.html)

The synonym set resource can be defined in two formats. The preferred one is the `synonym_graph` format:

```json
{
  "organizationName": "org.synapse.nf",
  "name": "standard_synonyms",
  "description": "Example NF domain synonym set for OpenSearch analyzers.",
  "definition": {
    "type": "synonym_graph",
    "synonyms": [
      "nf, neurofibromatosis",
      "nf1, neurofibromatosis type 1",
      "cnf => cnf, cutaneous neurofibroma",
      "mpnst, malignant peripheral nerve sheath tumor",
      "sc => schwann cell",
      "pnf => pnf, plexiform neurofibroma"
    ]
  }
}
```

#### Choosing a rule form

These are **search-time** synonyms (`synonym_graph`): expansion happens on the query, never on indexed docs, so query text is lowercased before the filter — keep rule keys lowercase.

| Form | Example | Effect |
| --- | --- | --- |
| **Equivalent** `a, b` | `mpnst, malignant peripheral nerve sheath tumor` | symmetric — a search for *either* form matches docs containing *either*; keeps all literal hits |
| **Replace** `a => b` | `sc => schwann cell` | query `a` is rewritten to `b`; literal `a` hits are **dropped** |
| **Keep** `a => a, b` | `pnf => pnf, plexiform neurofibroma` | `a` expands to find the concept **and** retains its own literal hits; `b` does not drag `a` back in |

**Default to equivalent (`a, b`)** — simplest and lossless. Switch to directional only when the short form is a noisy token (very short, a common word, appears in unrelated contexts):

- **Replace (`a => b`)** when literal short-form hits are themselves noise — e.g. `sc => schwann cell` (a bare `sc` matches `sc`-prefixed IDs everywhere).
- **Keep (`a => a, b`)** when the abbreviation should find the concept yet retain real entities that contain it — e.g. `pnf` must keep the `3PNF_*` cell lines, `cnf` its 7 literal docs. Prefer this over a bare `a => b`, which silently drops them.

### 2. Text Analyzer Referencing the Synonym Set

Reference:
- [`POST /search/text/analyzer`](https://rest-docs.synapse.org/rest/POST/search/text/analyzer.html)
- [`TextAnalyzer`](https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/TextAnalyzer.html)

The analyzer references the synonym set using a qualified name in a filter entry:

- Qualified reference format: `{organizationName}-{resourceName}`
- In this example: `org.synapse.nf-standard_synonyms`

```json
{
  "organizationName": "org.synapse.nf",
  "name": "standard_with_nf_synonyms",
  "description": "Example text analyzer referencing the org.synapse.nf-standard_synonyms synonym set.",
  "settings": {
    "tokenizer": {
      "std": {
        "type": "standard"
      }
    },
    "filter": {
      "nf_syn": {
        "$ref": "org.synapse.nf-standard_synonyms"
      }
    },
    "analyzer": {
      "default": {
        "type": "custom",
        "tokenizer": "std",
        "filter": [
          "lowercase",
          "nf_syn"
        ],
        "position_increment_gap": 100
      }
    }
  }
}
```

## Reference for Existing Analyzers

Reference:
- [`POST /search/text/analyzer/list`](https://rest-docs.synapse.org/rest/POST/search/text/analyzer/list.html)
- [`TextAnalyzer`](https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/TextAnalyzer.html)
- [OpenSearch token filters](https://docs.opensearch.org/latest/analyzers/token-filters/index/)

A quick overview of existing analyzers may also provide helpful context. But what's also important is that column-specific analyzer overrides can be configured. 

TODO: we *may* want to map the appropriate analyzer to certain properties in our data model. For example, `specimenID` would be annotated with `analyzer: IDENTIFIER`.

At the time of writing, the platform-provided analyzers under `org.sagebionetworks` include:

- `SCIENTIFIC`: for scientific metadata where stemming and stop-word handling are useful
- `STANDARD`: for general-purpose searchable text
- `IDENTIFIER`: for DOI, PMID, RRID, and similar identifier-like fields
- `KEYWORD`: for exact-match, facet, or filter-style fields
- `AUTOCOMPLETE`: for type-ahead behavior
- `AUTOCOMPLETE_SEARCH`: for type-ahead behaviorv

When reviewing or defining analyzers:

- `indexFilterOrder` and `searchFilterOrder` specify the order in which token filters are applied.
- The supported underlying filter types come from OpenSearch token filters.
- Names such as `sci_word_delimiter` or `std_word_delimiter` are local analyzer filter names that wrap an underlying OpenSearch filter type.

## Public REST Docs

- `POST /schema/organization`: https://rest-docs.synapse.org/rest/POST/schema/organization.html
- `CreateOrganizationRequest`: https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/schema/CreateOrganizationRequest.html
- `Organization`: https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/schema/Organization.html
- `SynonymSet`: https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/SynonymSet.html
- `POST /search/text/analyzer`: https://rest-docs.synapse.org/rest/POST/search/text/analyzer.html
- `TextAnalyzer`: https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/TextAnalyzer.html
- `POST /search/configuration/list`: https://rest-docs.synapse.org/rest/POST/search/configuration/list.html
- `POST /search/configuration`: https://rest-docs.synapse.org/rest/POST/search/configuration.html
- `SearchConfiguration`: https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/SearchConfiguration.html

