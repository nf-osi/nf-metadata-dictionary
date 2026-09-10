# Contribution Guide

_This guide was adopted and modified from the Sage-Bionetworks/synapseAnnotations guide._ 

Welcome! This project is for managing annotations and controlled vocabularies for use in the NF-OSI. 

## Modifying the dictionary

If you are adding a value to an existing term:

0) If you are not comfortable using GitHub, or would prefer that we make a change on your behalf, please go to the [Issues](https://github.com/nf-osi/nf-metadata-dictionary/issues) tab and file a new issue, selecting the appropriate issue template as needed.

Otherwise...
1) Create a new branch or fork to make your changes. 
2) Edit the relevant source file under `modules/` to make your proposed addition, removal, or modification. `modules/` holds the term definitions. Do not hand-edit `dist/`, `registered-json-schemas/`, or `NF.jsonld`: the first two are build outputs, and `NF.jsonld` is a legacy artifact that is no longer rebuilt by the pipeline.
3) Push the change to your branch. A GitHub Action will rebuild the generated artifacts and validate them, reporting back on your pull request. Do not commit rebuilt artifacts yourself - `dist/` and `registered-json-schemas/` are regenerated and committed automatically after merge. _Your change should be as atomic as possible - e.g., don't lump together many unrelated changes into a single issue or pull request. You may be requested to split them out._
4) File a pull request with your change and request review from [someone in the nf-osi organization](https://github.com/orgs/nf-osi/people).
5) If your pull request is accepted, we'll create a new release with your changes. 

## Guidelines for proposing new terms

Our strategy is to rely on annotation terms and definitions that have already been made and standardized whenever possible for use with Sage Bionetworks supported communities. In general, we will not include terms in this repository that are not needed and vetted by our communities - but don't let that stop you from using this! Feel free to fork and include terminology that you require for your own use.

If you are proposing a new term, then we require a source for the definition. The first place to look for an existing term is the EMBL-EBI Ontology Lookup Service. We have some preferred ontology term sources: EDAM, EFO, OBI, and NCIT. It's OK if your term comes from another source, but use the preferred sources whenever possible. You should use the term as defined in the source, or one of its synonyms. If your term does not currently exist, or has a different definition than existing ones, then:

    Provide a different source URL - this may be a Wikipedia entry, link to a commercial web site, or other URL.
    If you are a Sage Bionetworks employee and cannot find a source URL, then use "Sage Bionetworks" as the source and your own definition.
    If you are not (nor are you working with a Sage Bionetworks supported community) it is up to you for a strategy for controlling new terms to be added.

## Guidelines for modifying existing terms

**Deprecate; never rename or delete a permissible value.** Renaming a value is a breaking change: it invalidates every annotation in Synapse that uses the old label. Instead, add the new label and mark the old one `deprecated:` with free-text naming the replacement. A deprecated value is still emitted into the generated JSON Schema, so existing annotations stay valid and the release stays non-breaking. Actually removing it is a separate step, taken at a major release and gated on a query confirming zero remaining uses in Synapse.

Use free-text `deprecated:`, not `deprecated_element_has_exact_replacement:` - the latter is typed as a URI or CURIE and fails on a plain label.

Do not add explanatory YAML comments to files under `modules/`. The synonyms workflow rewrites those files with `yaml.dump()`, which discards comments. Put the explanation in `description:` or `notes:` instead, which round-trip and also render in the published docs.

## Guidelines for specific term types
In some situations (e.g. drug names), terms are not always well-captured by the ontologies found in the Ontology Lookup Service. We've defined some best practices for contributing these terms here.

### Contribution of tumorType terms
ONCOTREE _names_ are the preferred tumorType values, with one exception: do not carry over an OncoTree `NOS` ("not otherwise specified") qualifier. `NOS` records only that a tumor was not subtyped, which is meaningful in a pathology report but not in a portal facet. Prefer `High-Grade Glioma` over OncoTree's `High-Grade Glioma NOS`.

### Relationship between `tumorType` and `manifestation`
File-level `tumorType` (range: `Tumor`) is rolled up onto dataset- and study-level `manifestation` (range: `ManifestationEnum`) to populate the portal's facet search. For that rollup to work without a translation table, **every non-deprecated neoplasm value in `ManifestationEnum` must use a label string identical to its counterpart in `Tumor`**. When adding a neoplasm term to one enum, check whether the other needs it too, and copy the `meaning:` or `source:` verbatim rather than writing a new one.

Two categories are exempt from that rule.
First, `ManifestationEnum` additionally holds non-neoplasm phenotype and outcome values (`Behavioral`, `Cognition`, `Hearing Loss`, `Memory`, `Pain`, `Quality of Life`, `Vision Loss`) which have no `Tumor` counterpart.
Second, values carrying `deprecated:` are exempt by definition: they exist precisely because their labels diverge, and they are retained only so that existing annotations stay valid until those annotations are migrated and the values are removed at a major release.

Label identity says the two enums must agree; it does not say which spelling wins.
Spelling the term out is the default - that is why the `(MPNST)`, `(JMML)` and `(SMN)` forms were deprecated in favor of their expanded labels - but a community-standard acronym may be the canonical label where the acronym is the term of art at the file level and in existing annotations, and then the spelled-out variant is the one deprecated.
`ANNUBP` is the case in point: the `Tumor` enum and live study-level annotations both use the bare acronym, it is a provisional pathology classification with no NCIT or MONDO term (hence no `meaning:` in either enum), and its 77-character spelled-out variant would otherwise pin the label length permanently against the 80-character list column item width - keeping that variant in the deprecated tier means the headroom returns when deprecated values are removed at the major release.

`ManifestationEnum` is deliberately narrower than `Tumor` in the other direction, because a term that carries no facet information does not earn a facet option.
The test to apply is whether the value names a tumor **type**: a recurrence- or atypia-qualified entity that names a specific type is faceted (`Recurrent MPNST` and `Atypical MPNST` both do, and `Recurrent MPNST` carries its own `NCIT:C8823`), while a bare state descriptor that names no type at all (`tumor`, `recurrent tumor`, `metastatic tumor`, `metastatic/recurrent tumor`) is not.
Illustrative examples of the 27 excluded values: bare sample-state descriptors (`tumor`, `recurrent tumor`), placeholders (`Unknown`, `Not Applicable` - `manifestation` is optional, so omit the property instead), and terms redundant with `diseaseFocus` (`NF1-Associated Tumor`, `NF2-Associated Tumor`).
That list is not exhaustive; the `INTENTIONALLY_NOT_FACETED` literal in `tests/test_enum_harmonization.py` is the authoritative decision record, grouped by exclusion reason.

Faceted sibling entities do not currently roll into a shared parent facet: no `is_a` relation between permissible values survives into the generated artifacts, so filtering on `Malignant Peripheral Nerve Sheath Tumor` does not match a dataset annotated only `Atypical MPNST` or `Recurrent MPNST`.
That fragmentation is known and tracked as the `is_a` follow-up rather than solved here.

The invariant, together with the exemptions above, is enforced by `tests/test_enum_harmonization.py`.
Because the test checks both directions, adding a value to `Tumor` now requires either mirroring it into `ManifestationEnum` or adding it to `INTENTIONALLY_NOT_FACETED` with a stated reason; `test_every_tumor_value_is_faceted_or_explicitly_excluded` fails until you do one of the two.

### Contribution of drug terms
The preferred first-pass strategy for chemical name annotation is to search the EMBL-EBI ontology lookup service to find names, descriptions, and sources. Typically, the NCI Thesaurus will provide a suitable description for drugs and other biologically active molecules. In situations where the query molecule is not found in EMBL-EBI Ontology Lookup Service, a helpful secondary location to find chemical descriptions is MeSH.
In situations where novel molecules (such as newly-synthesized research compounds or proprietary pharmaceutical molecules) require annotation, the only suitable description and source might be the paper describing the synthesis or discovery, or information from the pharmaceutical company that created the identifier.

### Contribution of species terms
The preferred strategy for species name annotation is to search the NCBI Taxonomy Browser to find names, descriptions, and sources. The format of the description should be "Species name with taxonomy ID: taxonomyID and Genbank common name common name". The species name, taxonomyID, and Genbank common name can all be found in the NCBI Taxonomy Browser entry for the species.

### Contribution of file formats
We use the fileFormat key to indicate, well, the file format of a file uploaded to Synapse. Given the bias towards genomics files in Synapse, our source for file formats tends to come from EDAM, NCIT, but also Wikipedia and corporate web site descriptions. One thing to note is that the value to be contributed does not need to be the same as the commonly used file extension. For example, we describe GZipped files as gzip, while a GZipped file generally has an extension of gz.
