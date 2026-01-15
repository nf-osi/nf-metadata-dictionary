# Enum Metadata Implementation

## Overview

This implementation adds enum value metadata (source, description, meaning) from LinkML YAML definitions to the generated JSON schemas as a custom `x-enum-metadata` field. This enables frontends to display tooltips with additional information about enum values.

## Changes Made

### Modified File: `utils/gen-json-schema-class.py`

#### 1. Added `load_enum_metadata()` function
- Loads enum metadata from the LinkML YAML schema
- Builds a mapping from property names to their enum definitions
- Handles class inheritance to collect slots from parent classes
- Extracts `source`, `description`, and `meaning` fields for each enum value

#### 2. Added `add_enum_metadata()` function
- Traverses the JSON schema properties
- Adds `x-enum-metadata` to properties that have enums
- Handles both direct enum properties and array properties (nested in `items`)
- Combines metadata from multiple enum ranges when using `any_of`

#### 3. Modified `process_schema()` function
- Calls `load_enum_metadata()` to load enum metadata for the current class
- Calls `add_enum_metadata()` to inject metadata into the JSON schema

## JSON Schema Output Format

Properties with enum metadata now include an `x-enum-metadata` field:

```json
{
  "properties": {
    "modelSystemName": {
      "description": "...",
      "items": {
        "type": "string",
        "enum": ["JH-2-002", "JH-2-009", "JH-2-031", ...],
        "x-enum-metadata": {
          "JH-2-002": {
            "source": "https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=1bc84ef2-208f-4f0e-8045-6be47fd968de",
            "description": "Collected during surgical resection from patients with NF1-MPNST"
          },
          "JH-2-009": {
            "source": "https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=0bc812b4-f2af-40c4-8245-1070ab12f627",
            "description": "Collected during surgical resection from patients with NF1-MPNST"
          }
        }
      },
      "type": "array",
      "title": "modelSystemName"
    }
  }
}
```

## Frontend Usage Example

Here's how a frontend can display tooltips using the metadata:

### JavaScript/TypeScript Example

```javascript
// Load the JSON schema
const schema = await fetch('registered-json-schemas/RNASeqTemplate.json').then(r => r.json());

// Get enum metadata for a property
function getEnumMetadata(schema, propertyName) {
  const property = schema.properties[propertyName];

  // Check direct enum metadata
  if (property['x-enum-metadata']) {
    return property['x-enum-metadata'];
  }

  // Check items for array properties
  if (property.items && property.items['x-enum-metadata']) {
    return property.items['x-enum-metadata'];
  }

  return null;
}

// Get metadata for a specific value
function getValueMetadata(schema, propertyName, value) {
  const metadata = getEnumMetadata(schema, propertyName);
  return metadata ? metadata[value] : null;
}

// Usage in UI component
const modelSystemName = 'JH-2-002';
const metadata = getValueMetadata(schema, 'modelSystemName', modelSystemName);

if (metadata) {
  // Display tooltip with source link
  console.log(`Description: ${metadata.description}`);
  console.log(`Source: ${metadata.source}`);

  // Example: Render as tooltip
  const tooltip = `
    <div class="tooltip">
      <div class="description">${metadata.description}</div>
      <a href="${metadata.source}" target="_blank">View details</a>
    </div>
  `;
}
```

### React Example

```jsx
import React from 'react';
import { Tooltip } from '@mui/material';

function EnumValueWithTooltip({ schema, propertyName, value }) {
  // Get metadata for this value
  const property = schema.properties[propertyName];
  const enumMetadata = property.items?.['x-enum-metadata'] || property['x-enum-metadata'];
  const metadata = enumMetadata?.[value];

  if (!metadata) {
    return <span>{value}</span>;
  }

  const tooltipContent = (
    <div>
      {metadata.description && <p>{metadata.description}</p>}
      {metadata.source && (
        <a href={metadata.source} target="_blank" rel="noopener noreferrer">
          View details
        </a>
      )}
    </div>
  );

  return (
    <Tooltip title={tooltipContent} arrow>
      <span className="enum-value-with-tooltip">{value}</span>
    </Tooltip>
  );
}
```

## Testing

### Verify Implementation

1. **Generate schemas with metadata:**
   ```bash
   python utils/gen-json-schema-class.py --skip-validation
   ```

2. **Check specific schema:**
   ```bash
   python -c "
   import json
   with open('registered-json-schemas/RNASeqTemplate.json') as f:
       data = json.load(f)
       metadata = data['properties']['modelSystemName']['items']['x-enum-metadata']
       print(f'Found metadata for {len(metadata)} values')
       print(f'JH-2-002 source: {metadata[\"JH-2-002\"][\"source\"]}')
   "
   ```

3. **Expected output:**
   ```
   Found metadata for 809 values
   JH-2-002 source: https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId=1bc84ef2-208f-4f0e-8045-6be47fd968de
   ```

## Coverage

The implementation automatically adds metadata for all enum values that have:
- `source` field (URL to additional information)
- `description` field (human-readable description)
- `meaning` field (semantic URI/identifier)

Only enum values with at least one of these fields will have metadata added.

## Statistics

From the current schema generation:
- **Total schemas generated:** 56
- **Example: RNASeqTemplate.modelSystemName:** 809 enum values with metadata
- **Example: ImmunoMicroscopyTemplate.ageUnit:** 7 enum values with metadata

## Backward Compatibility

- The `x-enum-metadata` field is a vendor extension following JSON Schema conventions (prefix `x-`)
- Existing consumers that don't recognize this field will simply ignore it
- No breaking changes to existing schema validation or structure

## Future Enhancements

Potential improvements:
1. Add `x-enum-metadata` at the root level for frequently used enums
2. Include additional metadata fields (aliases, examples, etc.)
3. Generate TypeScript types from metadata for type-safe tooltip rendering
