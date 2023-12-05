#!/bin/bash
# Test generate GoogleSheets templates

TEST_CONFIG=../../dca-template-config.json
CREDS=creds.json
DATA_MODEL_PATH=../../NF.jsonld
DATA_MODEL=NF.jsonld
LOG_DIR=logs
SLEEP_THROTTLE=17 # API rate-limiting, need to better figure out dynamically based on # of templates

# Setup for creds
# If testing locally, it might already be in folder; 
# Else, especially if in Actions or Codespace, we need to create it from env var
# See https://github.com/nf-osi/nf-metadata-dictionary/settings/secrets/codespaces
if [ -f "$CREDS" ]; then
  echo "✓ $CREDS -- running tests locally"
elif [ -n "${SCHEMATIC_SERVICE_ACCT_CREDS}" ]; then
  echo "${SCHEMATIC_SERVICE_ACCT_CREDS}" | base64 -d > $CREDS
  echo "✓ Created temp $CREDS for test"
else
  echo "✗ Failed to access stored creds. Aborting test."
  exit 1
fi


TEMPLATES=($(jq '.manifest_schemas[] | .schema_name' $TEST_CONFIG | tr -d '"'))
#TITLES=($(jq '.manifest_schemas[] | .display_name' $TEST_CONFIG | tr -d '"'))
echo "✓ Using config with ${#TEMPLATES[@]} templates..."

# Setup data model
cp $DATA_MODEL_PATH $DATA_MODEL
echo "✓ Set up $DATA_MODEL for test"

# Setup logs
mkdir -p $LOG_DIR

for i in ${!TEMPLATES[@]}
do
  echo ">>>>>>> Generating ${TEMPLATES[$i]}"
  schematic manifest --config config.yml \
  get -dt ${TEMPLATES[$i]} --title ${TEMPLATES[$i]} -s | tee $LOG_DIR/${TEMPLATES[$i]%.*}_log.txt
  sleep $SLEEP_THROTTLE
done

echo "Cleaning up test fixtures and intermediates..."
rm -f $CREDS $TEST_CONFIG $DATA_MODEL *.schema.json *.manifest.csv

echo "✓ Done!"

