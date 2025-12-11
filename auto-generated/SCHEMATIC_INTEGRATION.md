# Schematic Integration Guide

## Overview

This guide explains how to integrate auto-generated research tool enums and mappings
with schematic for automatic field population.

## Integration Steps

### 1. Reference Auto-Generated Enums

The registered JSON schemas have been updated to use auto-generated enums.
These are automatically updated weekly via GitHub Actions.

### 2. Implement Auto-Fill in Schematic

Use the auto-fill configuration file to implement field population:

```python
import json

# Load auto-fill config
with open('auto-generated/autofill-config.json') as f:
    autofill_config = json.load(f)

# Load lookup service
with open('auto-generated/lookup-service.json') as f:
    lookup_service = json.load(f)

# Example: Auto-fill when modelSystemName is selected
def autofill_fields(schema_name, trigger_field, selected_value):
    # Find applicable rule
    for rule in autofill_config['rules']:
        if rule['schema'] == schema_name and rule['triggerField'] == trigger_field:
            # Get tool type from mapping source
            tool_type = rule['mappingSource'].split('/')[-1].replace('_mappings.json', '')

            # Lookup the tool's attributes
            if tool_type in lookup_service['tools']:
                mappings = lookup_service['tools'][tool_type]['mappings']
                if selected_value in mappings:
                    attributes = mappings[selected_value]

                    # Auto-fill fields
                    auto_values = {}
                    for schema_field, mapping_field in rule['autoFields'].items():
                        if mapping_field in attributes:
                            auto_values[schema_field] = attributes[mapping_field]

                    return auto_values

    return {}

# Usage example
selected_model = "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
auto_values = autofill_fields(
    'AnimalIndividualTemplate.json',
    'modelSystemName',
    selected_model
)
# Returns: {'species': 'Mus musculus', 'genotype': '...', 'backgroundStrain': '...'}
```

### 3. Update DCA Configuration

For Data Curator App integration:

```javascript
// In DCA config
{
  "autoFill": {
    "enabled": true,
    "configFile": "auto-generated/autofill-config.json",
    "lookupService": "auto-generated/lookup-service.json",
    "behavior": "suggest" // or "force"
  }
}
```

### 4. Validation

When validating metadata, ensure that auto-filled values match the mappings:

```python
def validate_autofilled_fields(schema_name, data):
    # If modelSystemName is set, validate other fields match mappings
    if 'modelSystemName' in data:
        expected = autofill_fields(schema_name, 'modelSystemName', data['modelSystemName'])

        for field, expected_value in expected.items():
            if field in data and data[field] != expected_value:
                warnings.append(f"Field {field} doesn't match expected value for {data['modelSystemName']}")
```

## Files Generated

- `auto-generated/autofill-config.json` - Configuration for auto-fill rules
- `auto-generated/lookup-service.json` - Unified lookup for all tool metadata
- `auto-generated/enums/*.json` - JSON Schema enumerations
- `auto-generated/mappings/*.json` - Tool attribute mappings

## Behavior Options

### Suggest (Recommended)
- Auto-fills empty fields
- Doesn't override user-entered values
- Shows suggestions/warnings for mismatches

### Force
- Always overwrites with mapped values
- Prevents user from entering conflicting data
- Use with caution

## Testing

Test auto-fill functionality:

```bash
# Run schematic with auto-fill enabled
schematic model   --config config.yml   --autofill auto-generated/autofill-config.json   validate   --manifest test_manifest.csv
```

## Questions?

See `auto-generated/README.md` for more information.
