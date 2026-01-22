all: NF.jsonld NF.yaml NF.ttl

# TODO Implement analysis on data model changes
analyze:
	@echo "Analyzing data model..."

NF.jsonld:
	bb ./retold/retold as-jsonld --dir modules --out retold_NF.jsonld
	cp retold_NF.jsonld NF.jsonld 


NF.yaml:
	yq eval-all '. as $$item ireduce ({}; . *+ $$item )' header.yaml modules/props.yaml modules/**/*.yaml > merged.yaml
	yq 'del(.. | select(has("annotations")).annotations)' merged.yaml > merged_no_extra_meta.yaml
	yq 'del(.. | select(has("enum_range")).enum_range)' merged_no_extra_meta.yaml > merged_no_inlined_range.yaml
	yq 'del(.. | select(has("in_subset")).in_subset)' merged_no_inlined_range.yaml > dist/NF.yaml
	rm -f merged*.yaml

NF.ttl:
	make dist/NF.yaml
	gen-rdf dist/NF.yaml > dist/NF.ttl

linkml_jsonld:
	gen-jsonld dist/NF.yaml > dist/NF_linkml.jsonld

# Example generation of manifests as Excel using LinkML -- each manifest is a sheet with dropdowns where appropriate
# We DON'T normally use these products, but this step is useful to provide as example for some
# There seems to be a bug where enum_range seems to be handled correctly, but this is relevant for only small set of attributes
# where we can migrate to using defined enums instead of inlined enums
ManifestLinkMLDemo: NF.yaml
	gen-excel dist/NF.yaml

Superdataset:
	jq '. += input | del(.required) | ."$$id"="https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-superdataset"' registered-json-schemas/PortalDataset.json rules/super_rules.json > registered-json-schemas/Superdataset.json
	@echo "--- Saved registered-json-schemas/Superdataset.json ---"
