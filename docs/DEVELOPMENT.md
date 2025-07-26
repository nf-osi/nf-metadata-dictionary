## Development

Data model developer-oriented information. 
While the root README gives a general overview of the repo organization and LinkML framework, this goes into history and implementation details helpful to know.

### A brief history

Initially, the source file for the data model was a single `.csv` that compiled to a JSONLD file compliant with the Sage-specific [schematic]() framework/ 
Later the `.csv` was modularized to make development easier and friendlier. 
Later still, the `.csv`s became YAML files as the framework transitioned to LinkML to get additional developer-friendly benefits and become part of a much larger ecosystem, with some custom interop to generate the main schematic-compliant JSONLD to enable using schematic validation. It was considered the best of both worlds.

Currently, the *implementation* for validation is changing so that the schematic Python package will no longer handle much of validation at all (with much of the underlying implementation using Great Expectations). Instead, it will now be handled by the Synapse platform directly, and the Synapse platform understands relatively standard JSON schemas. 

The main artifacts to provide for the downstream validation implementation is now a set of JSON schemas that covers all org-defined entities of interest. The JSONLD is still very useful in its way, since that format is easier for comparing data models *semantically*, but that is a different use case.

### Working with JSON schemas with regard to Synapse

You are developing a data model as JSON schemas with the knowledge that they will be used by Synapse. 
So there are a couple of things to keep in mind in how Synapse deals with/uses the JSON schema.

#### 1: Schema registration and binding

Before a schema can actually be used for validation, the schema must be registered in Synapse and then "bound" to an entity of interest. Children entities (e.g. a folder or file under another folder) inherit the same bound schema of a parent unless they have a schema bound to them, similar to local sharing settings.

#### 2: About $refs

[$refs](https://json-schema.org/understanding-json-schema/structuring#dollarref) are a standard part of the JSON schema specification that Synapse supports in a limited/specific way ([docs](https://rest-docs.synapse.org/rest/POST/schema/type/create/async/start.html)). The current conversion pipelines use a deref step for simplicity. 

> All $ref within a JSON schema must either be references to "definitions" within the schema or references other registered JSON schemas. References to non-registered schemas is not currently supported.  


#### 3: About If-then-else

The specification describes [If-Then-Else](https://json-schema.org/understanding-json-schema/reference/conditionals#ifthenelse), which in Synapse [parlance/docs](https://help.synapse.org/docs/JSON-Schemas.3107291536.html#JSONSchemas-DerivedAnnotations) is called "derived annotations". 
This means that on Synapse, the schema can help materialize an annotation value based on another value. 
In this repo, this type of definition is most often referred to as "rules" and stored separately under `rules` for now, though that may change.

**However**, thinking of this as only "derived annotations" may not fully convey what can be done with If-then-else definitions. If-then-else can also be used to apply an appropriate schema based on a value. This is better used with an "abstract" schema applied at the top-level. When the value for dataType is changed, the relevant attributes, allowable values, and validation requirements may be able to be updated instantly. This is useful because when dataType is (raw) "gene expression", the ranges for "assay", "platform", "fileFormat", etc. that are selectable and validated against are different than when dataType is "image". As well, "image" expects different attributes, where "libraryPrep" is irrelevant and not seen in that template.

(Note: Currently, the templates are mostly developed by assay, but they should more correctly developed for data type, so the example below is still messy and non-ideal.)

Example: 
```
{
	"$schema": "http://json-schema.org/draft-07/schema#",
	"$id": "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-data",
	"properties": {
		"dataType": {
			"enum": [
				"gene expression",
				"aligned reads",
                "image",
                "clinical data",
                "manifest",
				...
			]
		},
	},
	"allOf": [{
		"if": {
			"properties": {
				"dataType": {
					"const": "gene expression"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-genomicsassaytemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "aligned reads"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-processedalignedreadstemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "image"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-imagingassaytemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "clinical"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-clinicaldatatemplate"
		}
	}, {
		"if": {
			"properties": {
				"dataType": {
					"const": "manifest"
				}
			}
		},
		"then": {
			"$ref": "org.synapse.nf-metadata"
		}
	},
    ...
    ]
}
```
