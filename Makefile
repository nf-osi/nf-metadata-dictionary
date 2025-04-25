all: NF.jsonld NF.yaml NF.ttl

# TODO Implement analysis on data model changes
analyze:
	@echo "Analyzing data model..."

NF.jsonld:
	bb ./retold/retold as-jsonld --dir modules --out NF.jsonld 


NF.yaml:
	yq eval-all '. as $$item ireduce ({}; . * $$item )' header.yaml modules/props.yaml modules/**/*.yaml > merged.yaml
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

# Recompile certain json schemas with LinkML with selective import of props, enums, and template 
# LinkML output needs to be dereferenced bc Synapse doesn't suppport full specs such as $defs
PortalDataset:
	yq '.slots |= with_entries(select(.value.in_subset[] == "portal"))' modules/props.yaml > relevant_props.yaml
	yq ea '. as $$item ireduce ({}; . * $$item )' modules/Data/Data.yaml modules/Assay/Assay.yaml modules/Sample/Species.yaml modules/DCC/Portal.yaml > relevant_enums.yaml
	cat header.yaml relevant_props.yaml relevant_enums.yaml modules/Template/PortalDataset.yaml > temp.yaml
	gen-json-schema --inline --no-metadata --title-from=title --not-closed temp.yaml > tmp.json
	json-dereference -s tmp.json -o tmp.json
	jq '."$$defs".PortalDataset | ."$$id"="https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-portaldataset"' tmp.json > registered-json-schemas/PortalDataset.json
	rm -f relevant_props.yaml relevant_enums.yaml temp.yaml tmp.json
	@echo "--- Saved registered-json-schemas/PortalDataset.json ---"


# yq '.slots |= with_entries(select(.value.in_subset[] == "portal"))' modules/props.yaml > relevant_props.yaml
PortalStudy:
	yq eval-all '. as $$item ireduce ({}; . * $$item )' modules/Data/Data.yaml modules/DCC/Portal.yaml modules/Other/Organization.yaml > relevant_enums.yaml
	cat header.yaml relevant_enums.yaml modules/Template/PortalStudy.yaml > temp.yaml
	gen-json-schema --inline --no-metadata --not-closed temp.yaml > tmp.json
	json-dereference -s tmp.json -o tmp.json
	jq '."$$defs".PortalStudy | ."$$id"="https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-portalstudy"' tmp.json > registered-json-schemas/PortalStudy.json
	rm -f relevant_enums.yaml temp.yaml tmp.json
	@echo "--- Saved registered-json-schemas/PortalStudy.json ---"

Protocol:
	yq '.slots |= with_entries(select(.value.in_subset[] == "portal" or .value.in_subset[] == "registered"))' modules/props.yaml > relevant_props.yaml
	yq ea '. as $$item ireduce ({}; . * $$item )' modules/Data/Data.yaml modules/DCC/Portal.yaml modules/Assay/Assay.yaml > relevant_enums.yaml
	cat header.yaml relevant_props.yaml relevant_enums.yaml modules/Template/Protocol.yaml > temp.yaml
	gen-json-schema --inline --no-metadata --not-closed --title-from=title temp.yaml > tmp.json
	json-dereference -s tmp.json -o tmp.json
	jq '."$$defs".ProtocolTemplate | ."$$id"="https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-protocol"' tmp.json > registered-json-schemas/Protocol.json
	rm -f relevant_props.yaml relevant_enums.yaml temp.yaml tmp.json 
	@echo "--- Saved registered-json-schemas/Protocol.json ---"

Superdataset:
	jq '. += input | del(.required) | ."$$id"="https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-superdataset"' registered-json-schemas/PortalDataset.json registered-json-schemas/super_rules.json > registered-json-schemas/Superdataset.json
	@echo "--- Saved registered-json-schemas/Superdataset.json ---"

PortalPublication:
	yq ea '. as $$item ireduce ({}; . * $$item )' modules/DCC/Portal.yaml modules/Other/PublicationEnum.yaml > relevant_enums.yaml
	cat header.yaml modules/Template/PortalPublication.yaml relevant_enums.yaml > temp.yaml
	gen-json-schema --top-class=PortalPublication --no-metadata --not-closed --title-from=title temp.yaml > tmp.json
	json-dereference -s tmp.json -o tmp.json
	jq '."$$defs".PortalPublication | ."$$id"="https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-portalpublication"' tmp.json > registered-json-schemas/PortalPublication.json
	rm -f tmp.json temp.yaml relevant_enums.yaml
	@echo "--- Saved registered-json-schemas/PortalPublication.json ---"

