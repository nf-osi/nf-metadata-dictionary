#!/bin/bash
# Test generate excel manifests -- artifacts can be published as a bundle for convenient reference and offline usage when needed  

mkdir publish
schematic manifest -c config.yml get -dt 'DynamicLightScatteringTemplate' --jsonld NF.jsonld  --output_xlsx publish/DynamicLightScatteringTemplate.xlsx
