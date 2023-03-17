## Mappings 

This directory stores mapping specifications for the NF data model in a specific YAML/JSON format:
1. Translation of NF concepts to *other* data models/dictionaries. 
2. Translation of messy or legacy NF Data Portal annotations to versioned, standardized NF data model concepts.

These mappings help document what was done when metadata are translated or updated in harmonization or migration efforts. 
The mappings themselves are in development so both format and content may change.
Currently, the map spec is inspired by and vaguely resembles a [concept map](https://build.fhir.org/conceptmap-example.json.html), 
though [SSOM](https://github.com/mapping-commons/sssom) was also considered. 

Mappings may not map from NF to other models in full scope; that is, often we don't map every single data element, only what is needed and applicable at the time.
Additional future mappings that might be useful are:

(To other data models)
- NF to [CSBC](https://www.synapse.org/#!Synapse:syn26433610/tables/)
- NF to [HTAN](https://github.com/ncihtan/data-models)
- NF to [synapseAnnotations](https://github.com/Sage-Bionetworks/synapseAnnotations/) (NF terms originally derived from here, but there has been some drift/divergence)

