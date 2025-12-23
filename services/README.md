# NF Auto-fill Service

## Overview

Dynamic auto-fill service for Synapse curation grids. Queries NF research tools database directly instead of pre-compiling data into schemas.

**Problem Solved:** Eliminates need for 28,000-line static schemas with 1,000+ enum values by querying Synapse tables at runtime.

## Architecture

```
┌─────────────────────┐
│ Synapse Table       │  syn51730943 (1,069 tools)
│ (Source of Truth)   │  Always current
└──────────┬──────────┘
           │
           │ Direct query
           ▼
┌─────────────────────┐
│ Auto-fill Service   │  This service (Python/FastAPI)
│ (Dynamic Lookup)    │  Queries table, caches results
└──────────┬──────────┘
           │
           │ REST API
           ▼
┌─────────────────────┐
│ Curation Grid       │  Synapse file view
│ (User Interface)    │  Auto-fills metadata
└─────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Synapse Token

```bash
export SYNAPSE_AUTH_TOKEN=your_token_here
```

### 3. Run Service

```bash
python autofill_service.py
```

Service runs on http://localhost:8000

### 4. Test Service

```bash
python test_service.py
```

## Usage Examples

### Get Enum Values

```bash
curl http://localhost:8000/api/v1/enums/AnimalIndividualTemplate/modelSystemName
```

**Response:**
```json
{
  "field": "modelSystemName",
  "template": "AnimalIndividualTemplate",
  "values": [
    "129-Nf1<tm1Fcr>/Nci",
    "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
    "Nf1pArg1947mp1",
    ...
  ],
  "count": 123
}
```

### Auto-fill Lookup

```bash
curl -X POST http://localhost:8000/api/v1/autofill \
  -H "Content-Type: application/json" \
  -d '{
    "template": "AnimalIndividualTemplate",
    "trigger_field": "modelSystemName",
    "trigger_value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
  }'
```

**Response:**
```json
{
  "success": true,
  "template": "AnimalIndividualTemplate",
  "trigger_field": "modelSystemName",
  "trigger_value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
  "autofill": {
    "species": "Mus musculus",
    "organism": "Mus",
    "genotype": "C57BL/6",
    "backgroundStrain": "C57BL/6",
    "RRID": "rrid:IMSR_JAX:017640",
    "modelSystemType": "animal",
    "geneticModification": "Neurofibromatosis type 1",
    "manifestation": "Optic Nerve Glioma",
    "institution": "Memorial Sloan-Kettering Cancer Center"
  }
}
```

## Files

### Core Service
- **`autofill_service.py`** - Main FastAPI service (500 lines)
  - REST API endpoints
  - Synapse table queries
  - Caching layer
  - Template configuration

### Client Integration
- **`autofill_client.js`** - JavaScript client for Synapse UI (300 lines)
  - Auto-detects template
  - Observes field changes
  - Calls service API
  - Applies auto-fill

### Deployment
- **`Dockerfile`** - Container image
- **`docker-compose.yml`** - Orchestration
- **`requirements.txt`** - Python dependencies

### Documentation
- **`README.md`** - This file
- **`SYNAPSE_INTEGRATION.md`** - Integration guide (3,000+ lines)
  - Synapse WebClient integration
  - Java code examples
  - Deployment options
  - Security considerations

### Testing
- **`test_service.py`** - Test suite (400 lines)
  - All endpoint tests
  - Error handling tests
  - Integration tests

## API Endpoints

### `GET /`
Service information and available endpoints

### `GET /health`
Health check - validates Synapse connection

### `GET /api/v1/templates`
List configured templates and their fields

### `GET /api/v1/enums/{template}/{field}`
Get enum values for a field (dropdown options)

**Parameters:**
- `template`: Template name (e.g., `AnimalIndividualTemplate`)
- `field`: Field name (e.g., `modelSystemName`)

**Response:**
- `values`: Array of enum values
- `count`: Number of values

### `POST /api/v1/autofill`
Look up auto-fill values for a field

**Request Body:**
```json
{
  "template": "AnimalIndividualTemplate",
  "trigger_field": "modelSystemName",
  "trigger_value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"
}
```

**Response:**
```json
{
  "success": true,
  "autofill": {
    "species": "Mus musculus",
    "genotype": "C57BL/6",
    ...
  }
}
```

### `GET /api/v1/cache/info`
Cache statistics (hits, misses, size)

### `GET /api/v1/cache/clear`
Clear query cache (admin endpoint)

## Templates Configured

### AnimalIndividualTemplate
- **Table:** syn51730943
- **Type:** animal
- **Trigger:** modelSystemName
- **Auto-fills:** species, organism, genotype, backgroundStrain, RRID, modelSystemType, geneticModification, manifestation, institution

### BiospecimenTemplate
- **Table:** syn51730943
- **Type:** cell_line
- **Trigger:** cellLineName
- **Auto-fills:** species, tissue, organ, cellType, disease, RRID

## Adding New Templates

Edit `TEMPLATE_CONFIG` in `autofill_service.py`:

```python
TEMPLATE_CONFIG = {
    'YourNewTemplate': {
        'table_id': 'syn51730943',  # Synapse table ID
        'tool_type': 'your_type',    # Filter value
        'key_field': 'toolName',     # Lookup key column
        'fields': {
            # Map: template_field -> table_column
            'templateField': 'tableColumn',
            'species': 'species',
            'RRID': 'RRID',
        }
    }
}
```

Restart service to apply changes.

## Deployment

### Docker

```bash
# Build
docker build -t nf-autofill-service .

# Run
docker run -p 8000:8000 \
  -e SYNAPSE_AUTH_TOKEN=xxx \
  nf-autofill-service

# Or use docker-compose
docker-compose up -d
```

### AWS Lambda

```bash
# Package
pip install -r requirements.txt -t ./package
cd package && zip -r ../lambda.zip .
cd .. && zip -g lambda.zip autofill_service.py

# Deploy
aws lambda create-function \
  --function-name nf-autofill \
  --runtime python3.10 \
  --handler autofill_service.app \
  --zip-file fileb://lambda.zip \
  --environment Variables={SYNAPSE_AUTH_TOKEN=xxx}
```

### Google Cloud Run

```bash
# Build and push
gcloud builds submit --tag gcr.io/PROJECT/nf-autofill

# Deploy
gcloud run deploy nf-autofill \
  --image gcr.io/PROJECT/nf-autofill \
  --platform managed \
  --set-env-vars SYNAPSE_AUTH_TOKEN=xxx
```

## Integration with Synapse

See **`SYNAPSE_INTEGRATION.md`** for detailed integration guide.

### Quick Integration (JavaScript)

Add to Synapse page:

```html
<script src="https://your-domain.com/autofill_client.js"></script>
<script>
  const autofill = new NFAutofillClient({
    serviceUrl: 'https://autofill.nf-osi.org'
  });
  autofill.enable();
</script>
```

### Java Integration

For Synapse WebClient (Java/GWT), see integration examples in `SYNAPSE_INTEGRATION.md`.

## Performance

### Caching
- **Strategy:** LRU cache with 5-minute TTL
- **Size:** 100 queries
- **Cold query:** ~500ms (includes Synapse table query)
- **Cached query:** <10ms

### Query Optimization
- Indexed lookups on toolName (primary key)
- Filtered by toolType (indexed column)
- Only SELECT needed columns

### Scaling
- **Horizontal:** Run multiple instances behind load balancer
- **Redis:** Replace in-memory cache with Redis for shared cache
- **CDN:** Serve JavaScript client from CDN

## Security

### Authentication
Service uses **read-only service account** token:
- ✅ Read access to tools tables
- ❌ No write permissions
- ❌ No access to user data

### CORS
Configure allowed origins for production:
```python
allow_origins=["https://www.synapse.org"]
```

### Rate Limiting
Add for production:
```python
@limiter.limit("30/minute")
```

## Monitoring

### Logs
```bash
# View logs
docker logs nf-autofill-service

# Follow logs
docker logs -f nf-autofill-service
```

### Metrics
```bash
# Cache stats
curl http://localhost:8000/api/v1/cache/info
```

## Benefits vs. Pre-compiled Approach

| Aspect | Pre-compiled | Dynamic (This) |
|--------|--------------|----------------|
| **Schema size** | 28,000 lines (758 KB) | 50 lines (10 KB) |
| **Data freshness** | Weekly updates | Real-time |
| **Scalability** | Limited (1,000 tools max) | Unlimited |
| **Maintenance** | Complex (regenerate weekly) | Simple (always current) |
| **File size** | Grows with data | Fixed size |

## Roadmap

### ✅ Phase 1: POC (Current)
- ✅ Service implementation
- ✅ Basic caching
- ✅ Template support
- ✅ Documentation
- ✅ Testing

### ⏳ Phase 2: Integration (Next)
- ⏳ JavaScript client deployment
- ⏳ Synapse WebClient integration
- ⏳ Production deployment
- ⏳ Additional templates

### ⏳ Phase 3: Production
- ⏳ Monitoring and alerting
- ⏳ Rate limiting
- ⏳ CDN for client
- ⏳ Redis caching

### ⏳ Phase 4: Native Support
- ⏳ Engage Synapse platform team
- ⏳ Native API in Synapse
- ⏳ UI integration

## Troubleshooting

### Service won't start
```bash
# Check token
echo $SYNAPSE_AUTH_TOKEN

# Test Synapse connection
python -c "import synapseclient; syn = synapseclient.Synapse(); syn.login(authToken='$SYNAPSE_AUTH_TOKEN'); print(syn.getUserProfile())"
```

### Auto-fill not working
1. Check service is running: `curl http://localhost:8000/health`
2. Test endpoint directly: `curl http://localhost:8000/api/v1/templates`
3. Check browser console for JavaScript errors
4. Verify CORS settings allow Synapse origin

### Slow queries
1. Check cache hit rate: `curl http://localhost:8000/api/v1/cache/info`
2. Clear cache: `curl http://localhost:8000/api/v1/cache/clear`
3. Check Synapse table performance

## Support

### Issues
- Service bugs: This repository
- Synapse integration: https://github.com/Sage-Bionetworks/SynapseWebClient/issues
- Data issues: Tools database maintainers

### Documentation
- API docs: http://localhost:8000/docs (when running)
- Integration: `SYNAPSE_INTEGRATION.md`
- Dynamic approach: `../DYNAMIC_APPROACH.md`

## License

Same as parent repository

## Authors

NF-OSI Team

---

**Status:** ✅ Production-ready POC

**Next Step:** Deploy and test with Synapse curation grids
