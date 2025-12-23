# Dynamic Approach: Synapse Table References

## The Question

**"Can Synapse reference our Synapse tables directly instead of pre-compiling YAML/JSON?"**

## TL;DR

**Yes, this is the ideal long-term solution!** But requires Synapse platform enhancements.

---

## Current Approach (Pre-compiled)

```
┌─────────────────┐
│ Synapse Table   │  syn51730943 (1,069 tools)
│ (Source of      │
│  Truth)         │
└────────┬────────┘
         │
         │ Weekly GitHub Action
         ▼
┌─────────────────┐
│ Python Scripts  │  Fetch, transform, generate
│                 │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Static YAML     │  AnimalIndividualTemplate.yaml (2,653 lines)
│ with 123 rules  │  CellLineTemplate.yaml (17,000 lines)
│                 │  etc.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ JSON Schema     │  Uploaded to Synapse
│                 │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ DCA Form        │  Uses static enum + mappings
│                 │  Auto-fill from pre-compiled data
└─────────────────┘
```

**Problems:**
- ❌ Data duplicated (table → YAML → JSON → form)
- ❌ Stale data between updates
- ❌ Large file sizes (scales poorly)
- ❌ Complex regeneration process
- ❌ Change latency (weekly updates only)

---

## Dynamic Approach (Table References)

```
┌─────────────────┐
│ Synapse Table   │  syn51730943 (1,069 tools)
│ (Single Source  │  ← Only place data lives
│  of Truth)      │
└────────┬────────┘
         │
         │ Direct reference (no pre-compilation)
         ▼
┌─────────────────┐
│ Lightweight     │  AnimalIndividualTemplate.yaml (50 lines)
│ Schema          │  References: syn51730943
│                 │  Query: "SELECT * WHERE type='animal'"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ DCA Form        │  Queries table at runtime
│                 │  Auto-fill from live data
│                 │  Always current!
└─────────────────┘
```

**Benefits:**
- ✅ Single source of truth (no duplication)
- ✅ Always up-to-date (real-time)
- ✅ Small schemas (doesn't scale with data)
- ✅ No regeneration needed
- ✅ Instant updates when table changes

---

## Implementation Options

### Option 1: JSON Schema Extension (Custom Keywords)

Extend JSON Schema with Synapse-specific keywords:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AnimalIndividualTemplate",
  "properties": {
    "modelSystemName": {
      "type": "string",
      "x-synapse-ref": {
        "tableId": "syn51730943",
        "column": "toolName",
        "filter": {
          "toolType": "animal"
        }
      }
    },
    "species": {
      "type": "string",
      "x-synapse-autofill": {
        "tableId": "syn51730943",
        "lookupBy": "modelSystemName",
        "returnColumn": "species"
      }
    }
  }
}
```

**How it works:**
1. Form loads schema
2. Sees `x-synapse-ref` → queries syn51730943 for enum values
3. User selects modelSystemName
4. Sees `x-synapse-autofill` → queries table for species value
5. Auto-fills species field

**Pros:**
- ✅ Small, stable schemas
- ✅ Real-time data
- ✅ Standard JSON Schema + extensions
- ✅ Backward compatible

**Cons:**
- ⚠️ Requires Synapse platform support
- ⚠️ Custom JSON Schema keywords
- ⚠️ DCA/Schematic changes needed

---

### Option 2: LinkML External References

Use LinkML's external reference capabilities:

```yaml
classes:
  AnimalIndividualTemplate:
    slots:
      - modelSystemName
      - species
      - genotype

slots:
  modelSystemName:
    range: string
    annotations:
      synapse_table: syn51730943
      synapse_column: toolName
      synapse_filter: "toolType = 'animal'"

  species:
    range: string
    annotations:
      synapse_lookup_table: syn51730943
      synapse_lookup_by: modelSystemName
      synapse_return_column: species
```

**Pros:**
- ✅ Uses LinkML annotation system
- ✅ Clear, readable YAML
- ✅ LinkML tooling could generate dynamic schemas

**Cons:**
- ⚠️ LinkML doesn't natively support this yet
- ⚠️ Would need custom LinkML generator
- ⚠️ Still requires Synapse platform support

---

### Option 3: Synapse Schema API Extension

Add native Synapse schema features:

```json
{
  "$schema": "https://repo-prod.prod.sagebase.org/repo/v1/schema/synapse-dynamic-v1",
  "title": "AnimalIndividualTemplate",
  "properties": {
    "modelSystemName": {
      "type": "string",
      "synapse:enumSource": {
        "type": "tableColumn",
        "tableId": "syn51730943",
        "column": "toolName",
        "where": "toolType = 'animal'",
        "orderBy": "toolName ASC"
      }
    },
    "species": {
      "type": "string",
      "synapse:autoFill": {
        "type": "tableLookup",
        "tableId": "syn51730943",
        "lookupColumn": "toolName",
        "lookupValue": "$.modelSystemName",
        "returnColumn": "species"
      }
    }
  }
}
```

**How it works:**
1. Synapse natively understands `synapse:enumSource`
2. At form load time, executes query to get enum values
3. Caches results for performance
4. When field changes, executes `synapse:autoFill` lookup
5. Returns value from table

**Pros:**
- ✅ Native Synapse feature
- ✅ Clear intent
- ✅ Synapse can optimize queries
- ✅ Works with any table
- ✅ Permissions handled by Synapse

**Cons:**
- ⚠️ Requires Synapse platform development
- ⚠️ New schema format
- ⚠️ Breaking change from current approach

---

### Option 4: External Auto-fill Service

Create a microservice that DCA/Schematic can call:

```yaml
# Small schema with service references
classes:
  AnimalIndividualTemplate:
    slots:
      - modelSystemName
      - species
    annotations:
      autofill_service: https://autofill.nf-osi.org/api/v1
```

```javascript
// DCA form behavior
onFieldChange('modelSystemName', async (value) => {
  const response = await fetch(
    'https://autofill.nf-osi.org/api/v1/lookup',
    {
      method: 'POST',
      body: JSON.stringify({
        template: 'AnimalIndividualTemplate',
        field: 'modelSystemName',
        value: value
      })
    }
  );

  const autofillData = await response.json();
  // { species: "Mus musculus", genotype: "C57BL/6", ... }

  Object.entries(autofillData).forEach(([field, value]) => {
    setFieldValue(field, value);
  });
});
```

**Service implementation:**
```python
# autofill-service/app.py
from fastapi import FastAPI
import synapseclient

app = FastAPI()
syn = synapseclient.Synapse()

@app.post("/api/v1/lookup")
async def lookup(request: LookupRequest):
    # Query Synapse table directly
    query = f"""
        SELECT * FROM syn51730943
        WHERE toolName = '{request.value}'
        AND toolType = 'animal'
    """

    results = syn.tableQuery(query)
    row = results.asDataFrame().iloc[0]

    return {
        'species': row['species'],
        'genotype': row['genotype'],
        'backgroundStrain': row['backgroundStrain'],
        # ... etc
    }
```

**Pros:**
- ✅ Can implement immediately (no Synapse changes)
- ✅ Flexible (can add features without schema changes)
- ✅ Works with any data source
- ✅ Can cache for performance
- ✅ Separate concerns (service vs schema)

**Cons:**
- ⚠️ Requires hosting service
- ⚠️ Network dependency
- ⚠️ DCA/Schematic integration needed
- ⚠️ Not "native" to Synapse

---

### Option 5: Hybrid Approach (Practical for Now)

Combine static enums with dynamic lookups:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "properties": {
    "modelSystemName": {
      "type": "string",
      "enum": [
        "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
        "... 122 more ..."
      ],
      "x-autofill-config": {
        "lookupService": "https://autofill.nf-osi.org/api/v1",
        "template": "AnimalIndividualTemplate"
      }
    }
  }
}
```

**How it works:**
1. Enum values are still static (for validation)
2. But auto-fill is dynamic (queries service)
3. Enum updated weekly (current approach)
4. Auto-fill always current (live data)

**Pros:**
- ✅ Can implement now
- ✅ Gradual migration path
- ✅ Enum provides validation
- ✅ Service provides freshness

**Cons:**
- ⚠️ Still has enum staleness
- ⚠️ Two systems to maintain

---

## Comparison Matrix

| Approach | Implementation | Synapse Changes | Real-time | File Size | Difficulty |
|----------|----------------|-----------------|-----------|-----------|------------|
| **Current (pre-compiled)** | ✅ Done | None | ❌ Weekly | 758 KB | Easy |
| **JSON Schema Extension** | Needs DCA changes | Moderate | ✅ Yes | 10 KB | Medium |
| **LinkML External Refs** | Needs custom generator | Moderate | ✅ Yes | 10 KB | Medium |
| **Synapse Schema API** | Needs Synapse dev | Major | ✅ Yes | 10 KB | Hard |
| **External Service** | Can do now | None | ✅ Yes | 10 KB | Medium |
| **Hybrid** | Can do now | None | ⚠️ Partial | 100 KB | Easy |

---

## Recommended Path Forward

### Phase 1: Today (Using What We Built)
Use pre-compiled LinkML rules approach:
- ✅ Works now
- ✅ No Synapse changes needed
- ✅ Demonstrates value
- ⚠️ File size limitations

### Phase 2: Near-term (3-6 months)
Implement **External Auto-fill Service**:
```bash
# Simple service
docker run -p 8000:8000 nf-osi/autofill-service

# DCA points to service
export AUTOFILL_SERVICE_URL=https://autofill.nf-osi.org
```

- ✅ Can implement without Synapse changes
- ✅ Real-time data
- ✅ Small schemas
- Works alongside current approach

### Phase 3: Long-term (6-12 months)
Engage Synapse team for **native table references**:

```json
{
  "properties": {
    "modelSystemName": {
      "synapse:enumSource": "syn51730943.toolName WHERE toolType='animal'"
    },
    "species": {
      "synapse:autoFill": {
        "lookup": "syn51730943",
        "by": "modelSystemName",
        "return": "species"
      }
    }
  }
}
```

- ✅ Native Synapse feature
- ✅ Best UX
- ✅ Most maintainable
- Requires Synapse platform work

---

## Proof of Concept: External Service

Here's a minimal working example:

```python
#!/usr/bin/env python3
"""
Minimal auto-fill service proof of concept.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import synapseclient
import os

app = FastAPI(title="NF Auto-fill Service")

# Initialize Synapse client
syn = synapseclient.Synapse()
syn.login(authToken=os.getenv('SYNAPSE_AUTH_TOKEN'))

class LookupRequest(BaseModel):
    template: str
    field: str
    value: str

class LookupResponse(BaseModel):
    autofill: dict

@app.post("/api/v1/lookup", response_model=LookupResponse)
async def lookup(request: LookupRequest):
    """Look up auto-fill values for a field."""

    # Map templates to tables
    TEMPLATE_CONFIG = {
        'AnimalIndividualTemplate': {
            'table': 'syn51730943',
            'type_filter': 'animal',
            'key_field': 'toolName'
        }
    }

    if request.template not in TEMPLATE_CONFIG:
        raise HTTPException(404, f"Template not found: {request.template}")

    config = TEMPLATE_CONFIG[request.template]

    # Query Synapse table
    query = f"""
        SELECT * FROM {config['table']}
        WHERE {config['key_field']} = '{request.value}'
        AND toolType = '{config['type_filter']}'
    """

    try:
        results = syn.tableQuery(query)
        df = results.asDataFrame()

        if df.empty:
            raise HTTPException(404, f"No data found for: {request.value}")

        # Return first row as auto-fill data
        row = df.iloc[0].to_dict()

        # Filter to relevant fields
        autofill = {
            'species': row.get('species'),
            'organism': row.get('organism'),
            'genotype': row.get('genotype'),
            'backgroundStrain': row.get('backgroundStrain'),
            'RRID': row.get('RRID'),
            'modelSystemType': row.get('modelSystemType'),
            'geneticModification': row.get('geneticModification'),
            'manifestation': row.get('manifestation'),
            'institution': row.get('institution')
        }

        # Remove None values
        autofill = {k: v for k, v in autofill.items() if v is not None}

        return LookupResponse(autofill=autofill)

    except Exception as e:
        raise HTTPException(500, f"Query failed: {str(e)}")

@app.get("/api/v1/enums/{template}/{field}")
async def get_enum(template: str, field: str):
    """Get enum values for a field."""

    TEMPLATE_CONFIG = {
        'AnimalIndividualTemplate': {
            'table': 'syn51730943',
            'type_filter': 'animal',
            'fields': {
                'modelSystemName': 'toolName'
            }
        }
    }

    if template not in TEMPLATE_CONFIG:
        raise HTTPException(404, f"Template not found: {template}")

    config = TEMPLATE_CONFIG[template]

    if field not in config['fields']:
        raise HTTPException(404, f"Field not found: {field}")

    column = config['fields'][field]

    # Query for distinct values
    query = f"""
        SELECT DISTINCT {column} FROM {config['table']}
        WHERE toolType = '{config['type_filter']}'
        ORDER BY {column}
    """

    try:
        results = syn.tableQuery(query)
        df = results.asDataFrame()

        values = df[column].dropna().tolist()

        return {"enum": values}

    except Exception as e:
        raise HTTPException(500, f"Query failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Usage:**
```bash
# Start service
export SYNAPSE_AUTH_TOKEN=your_token
python autofill_service.py

# Query for auto-fill
curl -X POST http://localhost:8000/api/v1/lookup \
  -H "Content-Type: application/json" \
  -d '{
    "template": "AnimalIndividualTemplate",
    "field": "modelSystemName",
    "value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
  }'

# Response:
{
  "autofill": {
    "species": "Mus musculus",
    "genotype": "C57BL/6",
    "backgroundStrain": "C57BL/6",
    "RRID": "rrid:IMSR_JAX:017640",
    ...
  }
}

# Get enum values
curl http://localhost:8000/api/v1/enums/AnimalIndividualTemplate/modelSystemName

# Response:
{
  "enum": [
    "129-Nf1<tm1Fcr>/Nci",
    "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
    ...
  ]
}
```

---

## Benefits of Dynamic Approach

### 1. Always Current
- ✅ Data updates reflected immediately
- ✅ No regeneration lag
- ✅ No stale enums

### 2. Scalable
- ✅ Schema size doesn't grow with data
- ✅ Can handle millions of tools
- ✅ Performance depends on table, not schema

### 3. Maintainable
- ✅ Single source of truth
- ✅ No duplication
- ✅ Simpler architecture

### 4. Flexible
- ✅ Can change data without schema updates
- ✅ Can add new tools instantly
- ✅ Can fix errors immediately

---

## Next Steps

### Immediate
1. ✅ Complete current pre-compiled approach (proven it works)
2. ⏳ Test with Synapse (validate performance)
3. ⏳ Gather user feedback

### Short-term (Next sprint)
1. Build POC external auto-fill service
2. Test integration with DCA/Schematic
3. Measure performance vs pre-compiled

### Medium-term (Next quarter)
1. Deploy auto-fill service to production
2. Migrate 1-2 templates to use service
3. Monitor usage and performance

### Long-term (Next year)
1. Engage Synapse platform team
2. Propose native table reference feature
3. Design API with Synapse team
4. Migrate all templates to native approach

---

## Conclusion

**Yes, dynamic table references are absolutely the right long-term solution!**

The path:
1. **Today:** Use pre-compiled approach (what we built)
2. **3-6 months:** Add external auto-fill service (can implement now)
3. **6-12 months:** Work with Synapse for native support (ideal end state)

This gives us:
- ✅ Working solution today
- ✅ Migration path to dynamic
- ✅ No wasted effort (all steps useful)
- ✅ Incrementally better

Would you like me to build a proof-of-concept auto-fill service?
