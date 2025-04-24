#!/bin/bash
# Test submit manifests with schematic

CONFIG=config.json
LOG_DIR=logs
TEST_WORK_DIR=work
SYN_PROJECT=syn26462036 # NF-dev-playground
DATA_MODEL_PATH=../../NF.jsonld
DATA_MODEL=NF.jsonld

MANIFEST_DIR=($(jq -r '.manifest_directory' $CONFIG | tr -d '"'))
MANIFEST_VALIDATION_LOGS=($(jq -r '.manifest_validation_logs' $CONFIG | tr -d '"'))

# Setup logs and work directory
mkdir -p $LOG_DIR
mkdir -p $TEST_WORK_DIR

echo "Done setting up directories for test..."

# Setup data model
cp $DATA_MODEL_PATH $DATA_MODEL
echo "✓ Set up $DATA_MODEL for test"

# Check for which manifests to submit
echo "Using '$MANIFEST_DIR' as the scope containing all possible manifests for submission tests."

# Currently we require validation to run first and use the results instead of hard-coding which manifests go to submission
echo "Using '$MANIFEST_VALIDATION_LOGS' to filter for valid/qualifying manifests."

# Use validation results to determine which manifests will be submitted
MANIFESTS=($(grep -rl "Your manifest has been validated successfully." $MANIFEST_VALIDATION_LOGS))

for i in ${!MANIFESTS[@]}
do
  M=${MANIFESTS[$i]##*/}
  CSV=$MANIFEST_DIR/${M%.*}.csv
  echo "This manifest qualifies for and will undergo test submission: $CSV"
  echo "Creating mock dataset folder..."
  DATASET_FOLDER=$(synapse -p $SYNAPSE_AUTH_TOKEN create Folder --name "submission-test-dataset" --parentid $SYN_PROJECT | grep -Po "syn[0-9]+")
  
  # Given schematic internals here: https://github.com/Sage-Bionetworks/schematic/blob/develop/schematic/store/synapse.py#L484,
  # schematic does compare file names with the contents in the dataset folder, so entities should be created with consistent names, 
  # otherwise there is an id is "nan" error during submission
  # currently extract names from hard-coded col #2
  echo "Creating mock entities..."
  COL=($(csvtool col 2 $CSV))
  FILES=("${COL[@]:1}")
  echo "Filename" > $TEST_WORK_DIR/filenames.csv
  printf 'submission-test-dataset/%s\n' "${FILES[@]}" >> $TEST_WORK_DIR/filenames.csv
  IDS=()

  for i in "${FILES[@]}"
    do
      echo "I am a mock data file entity" > "$TEST_WORK_DIR/${i}"
      id=$(synapse -p $SYNAPSE_AUTH_TOKEN store --parentid $DATASET_FOLDER "$TEST_WORK_DIR/${i}" | grep -Po "syn[0-9]+")
      IDS+=($id)
    done
  echo "entityId" > $TEST_WORK_DIR/ids.csv
  printf '%s\n' "${IDS[@]}" >> $TEST_WORK_DIR/ids.csv
  echo "Add entity ids and submit manifest..."
  csvtool paste $CSV $TEST_WORK_DIR/ids.csv > $TEST_WORK_DIR/temp.csv
  csvtool pastecol 2 1 $TEST_WORK_DIR/temp.csv $TEST_WORK_DIR/filenames.csv > $TEST_WORK_DIR/manifest.csv

  schematic model --config config.yml submit \
  --manifest_path $TEST_WORK_DIR/manifest.csv \
  --dataset_id $DATASET_FOLDER \
  --hide_blanks \
  --manifest_record_type "file_only" \
  --file_annotations_upload \
  --table_column_names "display_name" \
  --annotation_keys "display_label" 2>&1 | tee $LOG_DIR/${M}.log

  echo "Downloading the just-submitted metadata for logging and analysis..."
  for i in ${IDS[@]}
    do
    synapse -p $SYNAPSE_AUTH_TOKEN get-annotations --id $i >> $LOG_DIR/${M%.*}-${DATASET_FOLDER}_tmp.json
    done

  cat $LOG_DIR/${M%.*}-${DATASET_FOLDER}_tmp.json | jq -n [inputs] > $LOG_DIR/${M%.*}-${DATASET_FOLDER}.json

  echo "Removing test dataset..."
  synapse  -p $SYNAPSE_AUTH_TOKEN delete $DATASET_FOLDER

done



