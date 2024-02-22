all: convert

# TODO Implement analysis on data model changes
analyze:
	@echo "Analyzing data model..."

convert:
	bb ./retold/retold as-jsonld --dir modules --out NF.jsonld 

# Recompile certain json schemas with LinkML with selective import of props, enums, and template 
# LinkML output needs to be dereferenced bc Synapse doesn't suppport full specs such as $defs
PortalDataset:
	yq '.slots |= with_entries(select(.value.in_subset[] == "portal"))' modules/props.yaml > relevant_props.yaml
	yq ea '. as $$item ireduce ({}; . * $$item )' modules/Data/Data.yaml modules/Assay/Assay.yaml modules/Sample/Species.yaml modules/DCC/Portal.yaml > relevant_enums.yaml
	cat header.yaml relevant_props.yaml relevant_enums.yaml modules/Template/PortalDataset.yaml > temp.yaml
	gen-json-schema --inline --no-metadata --not-closed temp.yaml > tmp.json
	rm relevant_props.yaml relevant_enums.yaml temp.yaml
	json-dereference -s tmp.json -o tmp.json
	jq '{ schema: { "$$schema": "http://json-schema.org/draft-07/schema#", "$$id": "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-portaldataset", properties: ."$$defs".PortalDataset.properties, required: ."$$defs".PortalDataset.required }}' tmp.json > registered-json-schemas/PortalDataset.json
	rm tmp.json
# There is a LinkML bug that needs some titles to be adjusted manually
	yq -iP '.schema.properties.accessType.title="accessType"' registered-json-schemas/PortalDataset.json -o json
	yq -iP '.schema.properties.assay.title="assay"' registered-json-schemas/PortalDataset.json -o json
	yq -iP '.schema.properties.dataType.title="dataType"' registered-json-schemas/PortalDataset.json -o json
	yq -iP '.schema.properties.fundingAgency.title="fundingAgency"' registered-json-schemas/PortalDataset.json -o json
	yq -iP '.schema.properties.license.title="license"' registered-json-schemas/PortalDataset.json -o json
	yq -iP '.schema.properties.manifestation.title="manifestation"' registered-json-schemas/PortalDataset.json -o json
	yq -iP '.schema.properties.species.title="species"' registered-json-schemas/PortalDataset.json -o json
	@echo "--- Saved registered-json-schemas/PortalDataset.json ---"


# yq '.slots |= with_entries(select(.value.in_subset[] == "portal"))' modules/props.yaml > relevant_props.yaml
PortalStudy:
	yq eval-all '. as $$item ireduce ({}; . * $$item )' modules/Data/Data.yaml modules/DCC/Portal.yaml modules/Other/Organization.yaml > relevant_enums.yaml
	cat header.yaml relevant_enums.yaml modules/Template/PortalStudy.yaml > temp.yaml
	gen-json-schema --inline --no-metadata --not-closed temp.yaml > tmp.json
	rm relevant_enums.yaml temp.yaml
	json-dereference -s tmp.json -o tmp.json
	jq '{ schema: { "$$schema": "http://json-schema.org/draft-07/schema#", "$$id": "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-portalstudy", properties: ."$$defs".PortalStudy.properties, required: ."$$defs".PortalStudy.required }}' tmp.json > registered-json-schemas/PortalStudy.json
	rm tmp.json
	@echo "--- Saved registered-json-schemas/PortalStudy.json ---"

Dataset:
	enum=$$(./utils/enumerate.sh assay); jq --argjson enum "$$enum" '.properties.assay.enum = $$enum' registered-json-schemas/Dataset.json > temp.json && mv temp.json registered-json-schemas/Dataset.json


Superdataset:
	enum=$$(./utils/enumerate.sh assay); jq --argjson enum "$$enum" '.properties.assay.enum = $$enum' registered-json-schemas/Superdataset.json > temp.json && mv temp.json registered-json-schemas/Superdataset.json

