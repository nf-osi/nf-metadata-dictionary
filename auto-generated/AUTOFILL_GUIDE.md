# Auto-Fill Integration Guide

## Overview

This guide explains how auto-generated research tool mappings integrate with registered JSON schemas to enable automatic field population when users select a research tool.

## How It Works

### 1. User Selects a Research Tool

When a researcher selects a research tool (e.g., an animal model) by its name:

```
User selects: modelSystemName = "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
```

### 2. System Looks Up Tool Metadata

The system uses the **lookup service** (`lookup-service.json`) to find all attributes for that tool:

```json
{
  "species": "Mus musculus",
  "organism": "Mus",
  "genotype": "C57BL/6",
  "backgroundStrain": "C57BL/6",
  "RRID": "rrid:IMSR_JAX:017640",
  "modelSystemType": "animal",
  "geneticModification": "Neurofibromatosis type 1",
  "manifestation": "Optic Nerve Glioma",
  "institution": "Memorial Sloan-Kettering Cancer Center",
  "description": "[From JAX]: These mice possess loxP sites..."
}
```

### 3. System Auto-Fills Related Fields

Based on the **auto-fill configuration** (`autofill-config.json`), the system populates:

```
✓ species = "Mus musculus"
✓ genotype = "C57BL/6"
✓ backgroundStrain = "C57BL/6"
```

### 4. User Continues with Pre-Populated Form

The researcher can now continue filling out other fields, with core metadata already populated correctly.

## Files Involved

### 1. Auto-Fill Configuration (`autofill-config.json`)

Defines which fields should be auto-filled for each schema:

```json
{
  "rules": [
    {
      "schema": "AnimalIndividualTemplate.json",
      "triggerField": "modelSystemName",
      "mappingSource": "auto-generated/mappings/animal_models_mappings.json",
      "autoFields": {
        "species": "species",
        "genotype": "genotype",
        "backgroundStrain": "backgroundStrain"
      },
      "behavior": "suggest"
    }
  ]
}
```

**Key Fields:**
- `schema` - Which template this applies to
- `triggerField` - Field that triggers auto-fill (e.g., modelSystemName)
- `mappingSource` - Where to get the attribute mappings
- `autoFields` - Which schema fields map to which tool attributes
- `behavior` - "suggest" (don't override user input) or "force" (always override)

### 2. Lookup Service (`lookup-service.json`)

Unified index of all research tools and their attributes:

```json
{
  "tools": {
    "animal_models": {
      "count": 123,
      "mappings": {
        "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)": {
          "species": "Mus musculus",
          "genotype": "C57BL/6",
          ...
        }
      }
    },
    "cell_lines": { ... },
    "antibodies": { ... },
    "genetic_reagents": { ... },
    "biobanks": { ... }
  }
}
```

### 3. Updated Registered Schemas

The registered JSON schemas (e.g., `AnimalIndividualTemplate.json`) now reference auto-generated enums:

```json
{
  "properties": {
    "modelSystemName": {
      "items": {
        "type": "string",
        "enum": [ /* 123 animal model names */ ],
        "x-auto-generated": {
          "source": "auto-generated/enums/modelSystemName_enum.json",
          "lastUpdated": "2025-12-11T11:44:51.264470Z",
          "sourceTable": "syn51730943"
        }
      }
    }
  }
}
```

## Implementation Examples

### Example 1: Python (for Schematic)

```python
import json

# Load configuration
with open('auto-generated/autofill-config.json') as f:
    config = json.load(f)

with open('auto-generated/lookup-service.json') as f:
    lookup = json.load(f)

def autofill_fields(schema_name, trigger_field, selected_value):
    """Auto-fill metadata fields based on selected tool."""
    # Find rule
    for rule in config['rules']:
        if rule['schema'] == schema_name and rule['triggerField'] == trigger_field:
            # Get tool type
            tool_type = rule['mappingSource'].split('/')[-1].replace('_mappings.json', '')

            # Lookup attributes
            if tool_type in lookup['tools']:
                mappings = lookup['tools'][tool_type]['mappings']

                if selected_value in mappings:
                    attributes = mappings[selected_value]

                    # Build auto-fill values
                    auto_values = {}
                    for schema_field, mapping_field in rule['autoFields'].items():
                        if mapping_field in attributes:
                            auto_values[schema_field] = attributes[mapping_field]

                    return auto_values

    return {}

# Usage
model_name = "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
auto_values = autofill_fields('AnimalIndividualTemplate.json', 'modelSystemName', model_name)
# Returns: {'species': 'Mus musculus', 'genotype': 'C57BL/6', 'backgroundStrain': 'C57BL/6'}
```

### Example 2: JavaScript (for DCA)

```javascript
// Load configuration
const config = await fetch('auto-generated/autofill-config.json').then(r => r.json());
const lookup = await fetch('auto-generated/lookup-service.json').then(r => r.json());

function autofillFields(schemaName, triggerField, selectedValue) {
  // Find rule
  const rule = config.rules.find(r =>
    r.schema === schemaName && r.triggerField === triggerField
  );

  if (!rule) return {};

  // Get tool type
  const toolType = rule.mappingSource.split('/').pop().replace('_mappings.json', '');

  // Lookup attributes
  if (toolType in lookup.tools) {
    const mappings = lookup.tools[toolType].mappings;

    if (selectedValue in mappings) {
      const attributes = mappings[selectedValue];

      // Build auto-fill values
      const autoValues = {};
      for (const [schemaField, mappingField] of Object.entries(rule.autoFields)) {
        if (mappingField in attributes) {
          autoValues[schemaField] = attributes[mappingField];
        }
      }

      return autoValues;
    }
  }

  return {};
}

// Usage
const modelName = "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)";
const autoValues = autofillFields('AnimalIndividualTemplate.json', 'modelSystemName', modelName);
// Returns: {species: 'Mus musculus', genotype: 'C57BL/6', backgroundStrain: 'C57BL/6'}
```

## Validation with Auto-Fill

### Scenario: User Enters Conflicting Data

If a user manually enters data that conflicts with the expected values:

```python
def validate_with_autofill(schema_name, trigger_field, user_data, lookup, config):
    """Validate that user data matches expected values from mappings."""

    if trigger_field not in user_data:
        return []  # No trigger field set, nothing to validate

    # Get expected values
    expected = autofill_fields(schema_name, trigger_field, user_data[trigger_field])

    warnings = []
    for field, expected_value in expected.items():
        if field in user_data and user_data[field] != expected_value:
            warnings.append({
                'field': field,
                'userValue': user_data[field],
                'expectedValue': expected_value,
                'message': f"Field '{field}' doesn't match expected value for {trigger_field}='{user_data[trigger_field]}'"
            })

    return warnings

# Example
user_data = {
    'modelSystemName': 'B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)',
    'species': 'Rattus norvegicus'  # Wrong!
}

warnings = validate_with_autofill('AnimalIndividualTemplate.json', 'modelSystemName', user_data, lookup, config)
# Returns: [{'field': 'species', 'userValue': 'Rattus norvegicus', 'expectedValue': 'Mus musculus', ...}]
```

## Behavior Modes

### "suggest" (Recommended Default)

- Auto-fills empty fields only
- Doesn't override user-entered values
- Shows warnings/suggestions for mismatches
- Gives users control while providing guidance

**Best for:** Most use cases, especially when users might have edge cases or custom variations

### "force"

- Always overwrites fields with mapped values
- Prevents conflicting data entry
- Locks fields after trigger field is set
- Ensures 100% consistency

**Best for:** Strict validation requirements, high-stakes data submissions

## Testing Auto-Fill

Run the test script to see auto-fill in action:

```bash
python scripts/test_autofill.py
```

**Output:**
```
======================================================================
TEST 1: Animal Model Auto-Fill
======================================================================

Scenario: User selects modelSystemName = 'B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)'

✓ Auto-fill SUCCESS

Fields to auto-populate:
  species              = Mus musculus
  genotype             = C57BL/6
  backgroundStrain     = C57BL/6

All available attributes for this tool:
  organism             = Mus
  RRID                 = rrid:IMSR_JAX:017640
  modelSystemType      = animal
  geneticModification  = Neurofibromatosis type 1
  ...
```

## Lookup by RRID

The lookup service also supports searching by RRID:

```python
def find_tool_by_rrid(rrid, lookup_service):
    """Find tools matching a specific RRID."""
    results = []

    for tool_type, data in lookup_service['tools'].items():
        for tool_name, attributes in data['mappings'].items():
            if rrid in attributes.get('RRID', '') or rrid in tool_name:
                results.append({
                    'type': tool_type,
                    'name': tool_name,
                    'attributes': attributes
                })

    return results

# Usage
tools = find_tool_by_rrid('IMSR_JAX:017640', lookup)
# Returns: [{'type': 'animal_models', 'name': 'B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)', ...}]
```

## Benefits

### For Researchers
- ✅ **Faster data entry** - Core fields auto-populated
- ✅ **Fewer errors** - Correct species, genotype, etc. automatically
- ✅ **Consistent naming** - Uses standardized tool names
- ✅ **Discovery** - Learn about tool attributes during entry

### For Data Curators
- ✅ **Quality improvement** - Reduced inconsistencies
- ✅ **Less manual review** - Auto-filled data is pre-validated
- ✅ **Standardization** - Enforces use of controlled vocabularies

### For Data Consumers
- ✅ **Better filtering** - Consistent metadata enables precise queries
- ✅ **Cross-study comparison** - Same tool referenced identically
- ✅ **RRID tracking** - Research Resource Identifiers preserved

## Current Integration Status

| Template | Trigger Field | Auto-Fill Fields | Status |
|----------|--------------|------------------|--------|
| **AnimalIndividualTemplate** | `modelSystemName` | species, genotype, backgroundStrain | ✅ Integrated |
| **BiospecimenTemplate** | (pending) | species, tissue, organ | ⏸️ Pending field mapping |

## Extending to More Templates

To add auto-fill to additional templates:

1. **Identify trigger field** - Which field contains the research tool name?
2. **Map schema fields to attributes** - Which fields should be auto-filled?
3. **Update integration config** - Add to `SCHEMA_INTEGRATIONS` in `scripts/integrate_tool_mappings.py`
4. **Run integration** - `python scripts/integrate_tool_mappings.py`
5. **Test** - Use `scripts/test_autofill.py` or manual testing

## Troubleshooting

### Auto-Fill Not Working

**Symptoms:** Fields not auto-populating

**Checks:**
1. Is the tool name spelled exactly as in the enum?
2. Does the schema have a rule in `autofill-config.json`?
3. Are the field names correct in the `autoFields` mapping?
4. Check browser console / application logs for errors

### Wrong Values Auto-Filled

**Symptoms:** Incorrect data populated

**Checks:**
1. Verify source data in `auto-generated/mappings/*.json`
2. Check if tool attributes were updated recently
3. Clear cache and reload lookup service
4. Report issue if source data is incorrect

### Tool Not Found in Lookup

**Symptoms:** "Tool not found in mappings" error

**Checks:**
1. Check if tool exists in source Synapse table
2. Verify tool wasn't filtered out during generation
3. Check tool name formatting (RRIDs, special characters)
4. Re-run `scripts/generate_tool_schemas_from_view.py`

## Maintenance

Auto-fill configuration and lookup service are automatically regenerated:

- **Weekly** - GitHub Actions workflow updates all files
- **Manual** - Run `scripts/integrate_tool_mappings.py`
- **After changes** - Run whenever mappings are regenerated

No manual maintenance required for production use.

## Questions?

- **Technical issues:** Open issue in GitHub repository
- **Data corrections:** Submit to source Synapse tables
- **Integration help:** See `auto-generated/SCHEMATIC_INTEGRATION.md`

---

**Last Updated:** 2025-12-11
**Version:** 1.0.0
**Status:** ✅ Production Ready
