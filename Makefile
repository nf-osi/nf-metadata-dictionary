all: convert

# TODO Implement analysis on data model changes
analyze:
	@echo "Analyzing data model..."

convert:
	bb ./retold/retold as-jsonld --dir modules --out NF.jsonld 

# Recompile json schemas with LinkML, select only needed props, enums, and template 
# LinkML output still needs to be edited bc Synapse doesn't suppport full specs such as $defs
PortalDataset:
	yq '.slots |= with_entries(select(.value.in_subset[] == "portal"))' modules/props.yaml > relevant_props.yaml
	yq '. *= load("modules/Data/Data.yaml")' modules/DCC/Status.yaml > relevant_enums.yaml
	cat header.yaml relevant_props.yaml relevant_enums.yaml modules/Template/PortalDataset.yaml > temp.yaml
	gen-json-schema --inline --no-metadata --not-closed temp.yaml > tmp.json
	rm relevant_props.yaml relevant_enums.yaml temp.yaml
	json-dereference -s tmp.json -o tmp.json
	jq '{ schema: { "$$schema": "http://json-schema.org/draft-07/schema#", "$$id": "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-portaldataset", properties: ."$$defs".PortalDataset.properties }}' tmp.json > registered-json-schemas/PortalDataset.json
	rm tmp.json
	echo "Saved PortalDataset to registered-json-schemas/PortalDataset.json"

