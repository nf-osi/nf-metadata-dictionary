#!/bin/bash
# Test validate manifests with schematic with output log


MANIFESTS=($(jq -r '.tests[].manifest' tests.json | tr -d '"'))
TEMPLATES=($(jq -r '.tests[].template' tests.json | tr -d '"'))

for i in ${!MANIFESTS[@]}
do
  echo ">>>>>>> Testing ${MANIFESTS[$i]} "
  schematic model --config config.yml validate -mp ${MANIFESTS[$i]} -dt ${TEMPLATES[$i]} -rr 2>&1 | tee ${MANIFESTS[$i]%.*}_log.txt
done