# Search Management Canonical Example

## Purpose

This document provides a canonical example for Synapse search management configuration as we (NF) verify them in practice. 

Current scope:

1. A `SynonymSet` in the `org.synapse.nf` organization
2. A `TextAnalyzer` that references that synonym set via `"$ref"`
3. A contextual explanation of where `SearchConfiguration` fits

## How This Relates to the Data Model

The NF metadata model is the source of truth for domain terminology: canonical labels, controlled values, and documented aliases. Synapse search configuration is a downstream deployment artifact built from that terminology.

In practice:

1. LinkML schema files *already* define `aliases`.
2. A generation step compiles relevant aliases into Synapse search resources such as `SynonymSet` (JSON). `SynonymSet`s are registered just like how other resource template JSON schemas are registered today.
3. Synapse `TextAnalyzer` and `SearchConfiguration` reference those resources to control search behavior.
4. The resulting configuration is bound in Synapse where search behavior should apply.

## Test Examples

- Synonym set fixture (`synonym_graph`): [synonym_set_nf_domain.json](/tests/search/synonym_set_nf_domain.json)
- Synonym set fixture (`rules`): [synonym_set_nf_rules.json](/tests/search/synonym_set_nf_rules.json)
- Text analyzer fixture: [text_analyzer_standard_with_nf_synonyms.json](/tests/search/text_analyzer_standard_with_nf_synonyms.json)

## Implementation Note

The JSON files above are intentionally minimal test fixtures. They are useful as understandable examples and for verifying the Synapse search-management, but they are not yet a complete source for NF search synonyms.

**TODO:** We will need a workflow step that compiles known aliases from the schema into the synonym format required by the Synapse search configuration. For example, `modules/Assay/Assay.yaml` already documents aliases for `next-generation sequencing`, including `NGS` and `next generation sequencing`. Those documented aliases should feed the generated synonym configuration rather than being maintained manually only in standalone test fixtures.

One caveat: if the target field uses the OpenSearch `standard` analyzer, punctuation and common delimiters are already split during analysis. In that case, a spacing variant like `next generation sequencing` may be redundant for search relative to `next-generation sequencing`, while a true alias like `NGS` is still useful. The eventual synonym-compilation script should account for this so analyzer-equivalent variants do not add unnecessary synonym rules.

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

The synonym set resource:

- Uses `organizationName`
- Uses `name`
- Stores the OpenSearch synonym definition under `definition`

Guidance on rule direction:

- Use equivalent rules like `a, b, c` when the terms are genuinely interchangeable for search.
- Use directional rules like `a => b` when expansion should flow one way only.
- Directional rules are usually better for abbreviations or shorthand that should expand to a canonical phrase without forcing the canonical phrase to match every short form in reverse.
- In this NF example, `cnf => cutaneous neurofibroma` and `pnf => plexiform neurofibroma` are directional because the abbreviations should expand to the full term, but the full term should not necessarily be rewritten back to the abbreviation.

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
      "cnf => cutaneous neurofibroma",
      "mpnst, malignant peripheral nerve sheath tumor",
      "sc => schwann cell",
      "pnf => plexiform neurofibroma"
    ]
  }
}
```

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

## Working Interpretation

Based on the public REST docs and the example we verified:

- The organization must exist and should be the same as the one to which JSON schemas are already registered (unless for some reason you want to create a new one).
- `SynonymSet` is a named organization-scoped resource.
- `TextAnalyzer.settings` can use an OpenSearch-style structure with named `filter` entries.
- A filter can reference a synonym set by qualified name using `"$ref"`.
- The canonical reference to the synonym set above is `org.synapse.nf-standard_synonyms`.

## Reusing Existing Analyzers

Reference:
- [`POST /search/text/analyzer/list`](https://rest-docs.synapse.org/rest/POST/search/text/analyzer/list.html)
- [`TextAnalyzer`](https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/TextAnalyzer.html)
- [OpenSearch token filters](https://docs.opensearch.org/latest/analyzers/token-filters/index/)

Before creating a new analyzer, check the platform-provided analyzers under `org.sagebionetworks`.

At the time of writing, the public analyzer list includes:

- `SCIENTIFIC`
- `STANDARD`
- `IDENTIFIER`
- `KEYWORD`
- `AUTOCOMPLETE`
- `AUTOCOMPLETE_SEARCH`

For many organizations, these existing analyzers can be reused directly instead of creating new analyzer resources.

When reviewing or defining analyzers:

- `indexFilterOrder` and `searchFilterOrder` specify the order in which token filters are applied.
- The supported underlying filter types come from OpenSearch token filters.
- Names such as `sci_word_delimiter` or `std_word_delimiter` are local analyzer filter names that wrap an underlying OpenSearch filter type.

Practical guidance:

- Reuse `STANDARD` for general-purpose searchable text.
- Reuse `SCIENTIFIC` for scientific metadata where stemming and stop-word handling are useful.
- Reuse `IDENTIFIER` for DOI, PMID, RRID, and similar identifier-like fields.
- Reuse `KEYWORD` for exact-match, facet, or filter-style fields.
- Reuse `AUTOCOMPLETE` and `AUTOCOMPLETE_SEARCH` when you need type-ahead behavior.

For the NF example in this document, our custom work is centered on the synonym set. If the built-in analyzers already fit the desired tokenization behavior, the next step may be to reference those existing analyzers from a `SearchConfiguration` rather than creating a new custom analyzer.

## SearchConfiguration

Reference:
- [`POST /search/configuration/list`](https://rest-docs.synapse.org/rest/POST/search/configuration/list.html)
- [`POST /search/configuration`](https://rest-docs.synapse.org/rest/POST/search/configuration.html)
- [`SearchConfiguration`](https://rest-docs.synapse.org/rest/org/sagebionetworks/repo/model/search/table/SearchConfiguration.html)

The `SearchConfiguration` is the composition layer that bundles those reusable resources into one search setup that can be applied to content. The practical relationship is:

1. The synonym set named `standard_synonyms` lives in `org.synapse.nf`.
2. The text analyzer named `standard_with_nf_synonyms` references that synonym set with `"$ref": "org.synapse.nf-standard_synonyms"`.
3. A future `SearchConfiguration` can either use that custom analyzer or reuse an existing analyzer from `org.sagebionetworks`, plus any synonym sets or per-column overrides needed for a complete configuration.

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

