#!/bin/bash

# Extract enums as JSON array
class="bts:$1"

cat NF.jsonld | jq  --arg class "$class" '(."@graph"[] | select(."@id" == $class)."schema:rangeIncludes"[]."@id") as $ids | ."@graph"[] | select(."@id"|IN($ids))."sms:displayName"' | sort --ignore-case | jq -n '[inputs]'
