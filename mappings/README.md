## Mappings 

This directory stores mapping specifications from the NF data model to other data model/dictionaries as needed in a specific YAML/JSON format. 
These mappings are very much in development so both format and content may change.
Currently, the map spec is inspired by and vaguely resembles a [concept map](https://build.fhir.org/conceptmap-example.json.html), 
though [SSOM](https://github.com/mapping-commons/sssom) was also considered. 

Mappings may not map from NF to other models in full scope; that is, often we don't map every single data element, only what is needed and applicable given the two models.
Additional future mappings that might be useful are:

- NF to [CSBC](https://www.synapse.org/#!Synapse:syn26433610/tables/)
- NF to [HTAN](https://github.com/ncihtan/data-models)
- NF to [synapseAnnotations](https://github.com/Sage-Bionetworks/synapseAnnotations/) (NF terms originally derived from here, but there has been some drift/divergence)


