#!/usr/bin/env python3
"""
NF Auto-fill Service for Synapse Curation Grids

This service provides dynamic auto-fill functionality for Synapse file views
by querying the NF research tools database directly. It integrates with
curation grids created via create-curation-task.yml.

Architecture:
    Synapse Table (syn51730943) → Auto-fill Service → Curation Grid
    (Source of truth)            (This service)       (File view)

Usage:
    # Start service
    export SYNAPSE_AUTH_TOKEN=your_token
    python services/autofill_service.py

    # Query auto-fill
    curl -X POST http://localhost:8000/api/v1/autofill \
      -H "Content-Type: application/json" \
      -d '{
        "template": "AnimalIndividualTemplate",
        "trigger_field": "modelSystemName",
        "trigger_value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
        "row_id": "12345"
      }'

    # Get enum values
    curl http://localhost:8000/api/v1/enums/AnimalIndividualTemplate/modelSystemName

Requirements:
    pip install fastapi uvicorn synapseclient pandas pydantic
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import synapseclient
import pandas as pd
import os
import logging
from functools import lru_cache
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NF Auto-fill Service",
    description="Dynamic auto-fill service for NF metadata curation grids",
    version="1.0.0"
)

# Add CORS middleware for browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Synapse client (lazy initialization)
_synapse_client = None


def get_synapse_client():
    """Get or create Synapse client singleton."""
    global _synapse_client

    if _synapse_client is None:
        auth_token = os.getenv('SYNAPSE_AUTH_TOKEN')
        if not auth_token:
            raise ValueError("SYNAPSE_AUTH_TOKEN environment variable required")

        _synapse_client = synapseclient.Synapse()
        _synapse_client.login(authToken=auth_token, silent=True)
        logger.info("✓ Synapse client initialized")

    return _synapse_client


# Template configuration
TEMPLATE_CONFIG = {
    'AnimalIndividualTemplate': {
        'table_id': 'syn51730943',
        'tool_type': 'animal',
        'key_field': 'toolName',
        'fields': {
            'modelSystemName': 'toolName',
            'species': 'species',
            'organism': 'organism',
            'genotype': 'genotype',
            'backgroundStrain': 'backgroundStrain',
            'RRID': 'RRID',
            'modelSystemType': 'modelSystemType',
            'geneticModification': 'geneticModification',
            'manifestation': 'manifestation',
            'institution': 'institution',
            'description': 'description'
        }
    },
    'BiospecimenTemplate': {
        'table_id': 'syn51730943',
        'tool_type': 'cell_line',
        'key_field': 'toolName',
        'fields': {
            'cellLineName': 'toolName',
            'species': 'species',
            'tissue': 'tissue',
            'organ': 'organ',
            'cellType': 'cellType',
            'disease': 'disease',
            'RRID': 'RRID'
        }
    }
}


class AutofillRequest(BaseModel):
    """Request model for auto-fill lookup."""
    template: str = Field(..., description="Template name (e.g., AnimalIndividualTemplate)")
    trigger_field: str = Field(..., description="Field that triggered auto-fill (e.g., modelSystemName)")
    trigger_value: str = Field(..., description="Value of trigger field")
    row_id: Optional[str] = Field(None, description="Optional row ID in file view")

    class Config:
        json_schema_extra = {
            "example": {
                "template": "AnimalIndividualTemplate",
                "trigger_field": "modelSystemName",
                "trigger_value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
                "row_id": "12345"
            }
        }


class AutofillResponse(BaseModel):
    """Response model for auto-fill lookup."""
    success: bool
    template: str
    trigger_field: str
    trigger_value: str
    autofill: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "template": "AnimalIndividualTemplate",
                "trigger_field": "modelSystemName",
                "trigger_value": "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
                "autofill": {
                    "species": "Mus musculus",
                    "genotype": "C57BL/6",
                    "backgroundStrain": "C57BL/6",
                    "RRID": "rrid:IMSR_JAX:017640"
                }
            }
        }


class EnumResponse(BaseModel):
    """Response model for enum values."""
    field: str
    template: str
    values: List[str]
    count: int


@lru_cache(maxsize=100, typed=False)
def _cached_query(query: str, cache_timeout: int = 300) -> pd.DataFrame:
    """
    Execute Synapse query with caching.

    Args:
        query: SQL query string
        cache_timeout: Cache timeout in seconds (default 5 minutes)

    Returns:
        DataFrame with query results
    """
    syn = get_synapse_client()
    logger.info(f"Executing query: {query}")

    try:
        results = syn.tableQuery(query)
        df = results.asDataFrame()
        logger.info(f"  → Returned {len(df)} rows")
        return df
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise


def query_synapse_table(table_id: str, where_clause: str = None) -> pd.DataFrame:
    """
    Query Synapse table with optional where clause.

    Args:
        table_id: Synapse table ID
        where_clause: Optional SQL WHERE clause

    Returns:
        DataFrame with results
    """
    query = f"SELECT * FROM {table_id}"
    if where_clause:
        query += f" WHERE {where_clause}"

    return _cached_query(query)


@app.on_event("startup")
async def startup_event():
    """Initialize service on startup."""
    logger.info("=" * 70)
    logger.info("NF Auto-fill Service Starting")
    logger.info("=" * 70)

    # Test Synapse connection
    try:
        syn = get_synapse_client()
        profile = syn.getUserProfile()
        logger.info(f"✓ Connected as: {profile['userName']}")
    except Exception as e:
        logger.error(f"✗ Failed to connect to Synapse: {e}")
        raise

    logger.info(f"✓ Loaded {len(TEMPLATE_CONFIG)} template configurations")
    logger.info("✓ Service ready")


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "NF Auto-fill Service",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "autofill": "POST /api/v1/autofill",
            "enums": "GET /api/v1/enums/{template}/{field}",
            "health": "GET /health",
            "templates": "GET /api/v1/templates"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        syn = get_synapse_client()
        # Quick check - get user profile
        profile = syn.getUserProfile()

        return {
            "status": "healthy",
            "synapse_connected": True,
            "synapse_user": profile.get('userName'),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")


@app.get("/api/v1/templates")
async def list_templates():
    """List available templates and their configurations."""
    templates = {}
    for name, config in TEMPLATE_CONFIG.items():
        templates[name] = {
            "table_id": config['table_id'],
            "tool_type": config['tool_type'],
            "key_field": config['key_field'],
            "autofill_fields": list(config['fields'].keys())
        }

    return {
        "count": len(templates),
        "templates": templates
    }


@app.post("/api/v1/autofill", response_model=AutofillResponse)
async def autofill_lookup(request: AutofillRequest):
    """
    Look up auto-fill values for a template field.

    This endpoint queries the NF research tools database to find metadata
    associated with the trigger value and returns fields to auto-fill.
    """
    logger.info(f"Auto-fill request: {request.template}.{request.trigger_field} = {request.trigger_value}")

    # Validate template
    if request.template not in TEMPLATE_CONFIG:
        raise HTTPException(
            status_code=404,
            detail=f"Template not found: {request.template}. Available: {list(TEMPLATE_CONFIG.keys())}"
        )

    config = TEMPLATE_CONFIG[request.template]

    # Validate trigger field
    if request.trigger_field not in config['fields']:
        raise HTTPException(
            status_code=400,
            detail=f"Field not configured for auto-fill: {request.trigger_field}"
        )

    # Get column name in tools table
    column_name = config['fields'][request.trigger_field]

    # Build query
    where_clause = f"{column_name} = '{request.trigger_value}' AND toolType = '{config['tool_type']}'"

    try:
        # Query tools table
        df = query_synapse_table(config['table_id'], where_clause)

        if df.empty:
            return AutofillResponse(
                success=False,
                template=request.template,
                trigger_field=request.trigger_field,
                trigger_value=request.trigger_value,
                message=f"No data found for: {request.trigger_value}"
            )

        # Get first row
        row = df.iloc[0]

        # Build auto-fill dictionary
        autofill = {}
        for field_name, column_name in config['fields'].items():
            # Skip trigger field (already set by user)
            if field_name == request.trigger_field:
                continue

            # Get value from row
            if column_name in row and pd.notna(row[column_name]):
                value = row[column_name]

                # Convert to string for JSON serialization
                if isinstance(value, (pd.Timestamp, datetime)):
                    value = value.isoformat()
                elif isinstance(value, (int, float)):
                    value = str(value) if pd.notna(value) else None
                elif not isinstance(value, str):
                    value = str(value)

                autofill[field_name] = value

        logger.info(f"  → Auto-filling {len(autofill)} fields")

        return AutofillResponse(
            success=True,
            template=request.template,
            trigger_field=request.trigger_field,
            trigger_value=request.trigger_value,
            autofill=autofill,
            message=f"Found data for {request.trigger_value}"
        )

    except Exception as e:
        logger.error(f"  ✗ Lookup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Lookup failed: {str(e)}")


@app.get("/api/v1/enums/{template}/{field}", response_model=EnumResponse)
async def get_enum_values(template: str, field: str):
    """
    Get enum values for a field in a template.

    This endpoint queries the tools database to get all distinct values
    for a field, suitable for use as dropdown options in forms.
    """
    logger.info(f"Enum request: {template}.{field}")

    # Validate template
    if template not in TEMPLATE_CONFIG:
        raise HTTPException(
            status_code=404,
            detail=f"Template not found: {template}. Available: {list(TEMPLATE_CONFIG.keys())}"
        )

    config = TEMPLATE_CONFIG[template]

    # Validate field
    if field not in config['fields']:
        raise HTTPException(
            status_code=400,
            detail=f"Field not configured: {field}"
        )

    column_name = config['fields'][field]

    # Build query for distinct values
    where_clause = f"toolType = '{config['tool_type']}'"

    try:
        df = query_synapse_table(config['table_id'], where_clause)

        if column_name not in df.columns:
            raise HTTPException(
                status_code=500,
                detail=f"Column not found in table: {column_name}"
            )

        # Get distinct values, remove nulls, sort
        values = df[column_name].dropna().unique().tolist()
        values.sort()

        logger.info(f"  → Returned {len(values)} enum values")

        return EnumResponse(
            field=field,
            template=template,
            values=values,
            count=len(values)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"  ✗ Enum query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.get("/api/v1/cache/clear")
async def clear_cache():
    """Clear the query cache (admin endpoint)."""
    _cached_query.cache_clear()
    logger.info("Cache cleared")
    return {"message": "Cache cleared successfully"}


@app.get("/api/v1/cache/info")
async def cache_info():
    """Get cache statistics."""
    info = _cached_query.cache_info()
    return {
        "hits": info.hits,
        "misses": info.misses,
        "size": info.currsize,
        "maxsize": info.maxsize
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv('PORT', 8000))
    host = os.getenv('HOST', '0.0.0.0')

    logger.info(f"Starting server on {host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
