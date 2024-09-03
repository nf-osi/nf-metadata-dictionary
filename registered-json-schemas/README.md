## Registered JSON Schemas

These are JSON schemas registered to the Synapse platform. 
See https://help.synapse.org/docs/JSON-Schemas.3107291536.html#JSONSchemas-CreateaJSONSchema.

Of these files, only `super_rules.json` should be edited by hand.
These are generated files, compiled to JSON from the YAML source using LinkML (see the Makefile at the root of this repo).

To edit PortalDataset, edit modules/Template/PortalDataset.yaml
To edit PortalStudy, edit modules/Template/PortalStudy.yaml

`Superdataset.json` composes PortalDataset. Important things to note:
- It adds materialization powers defined in `super_rules.json`. When applied to Synapse objects, there is additional derivation checking if the object is a folder and creating additional annotations.
- Technically, it wraps a softer version of PortalDataset that removes required because for derived annotations to work, we can't have missing data. See PLFM-8560.
