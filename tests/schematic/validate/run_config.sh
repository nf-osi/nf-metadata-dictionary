#!/bin/bash
# Test validate manifests with schematic with output log

CONFIG=config.json
LOG_DIR=logs
DATA_MODEL_PATH=../../NF.jsonld
DATA_MODEL=NF.jsonld

MANIFESTS=($(jq -r '.tests[].manifest' $CONFIG | tr -d '"'))
TEMPLATES=($(jq -r '.tests[].template' $CONFIG | tr -d '"'))

# Setup logs
mkdir -p $LOG_DIR

# Setup data model
cp $DATA_MODEL_PATH $DATA_MODEL
echo "✓ Set up $DATA_MODEL for test"

for i in ${!MANIFESTS[@]}
do
  echo ">>>>>>> Testing ${MANIFESTS[$i]} "
  schematic model --config config.yml \
  validate -mp ${MANIFESTS[$i]} -dt ${TEMPLATES[$i]} 2>&1 | tee $LOG_DIR/${MANIFESTS[$i]%.*}.txt
done

echo "Cleaning up test fixtures and intermediates..."
rm -f $DATA_MODEL *.schema.json

