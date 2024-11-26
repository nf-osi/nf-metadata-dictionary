#!/bin/bash

for FILE in $1
do
    # Synapse does not allow additionalProperties in schema, so remove that first
    jq 'del(.additionalProperties)' $FILE > temp.json
    REQUEST_BODY=$(jq '{schema : ., concreteType: "org.sagebionetworks.repo.model.schema.CreateSchemaRequest", dryRun: false }' temp.json)
    RESPONSE=$(curl -X POST https://repo-prod.prod.sagebase.org/repo/v1/schema/type/create/async/start \
    -H "Authorization: Bearer $SYNAPSE_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$REQUEST_BODY")
    rm temp.json

    # Will error if token not within response
    echo $RESPONSE
    TOKEN=$( echo $RESPONSE | jq -e -r '.token')
    sleep 1
    STATUS=$(curl "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/create/async/get/$TOKEN" \
    -H "Authorization: Bearer $SYNAPSE_AUTH_TOKEN")
    while true; do
        if echo "$STATUS" | jq -e '.jobState == "PROCESSING"' > /dev/null; then
            sleep 1
            STATUS=$(curl "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/create/async/get/$TOKEN" \
            -H "Authorization: Bearer $SYNAPSE_AUTH_TOKEN")
        elif echo "$STATUS" | jq -e '.concreteType == "org.sagebionetworks.repo.model.ErrorResponse"' > /dev/null; then
            echo "Error: $(echo $STATUS | jq -r '.reason')"
            exit 1
        else
            echo "Success:"
            echo "$STATUS" | jq -e '.newVersionInfo'
            break
        fi
    done
