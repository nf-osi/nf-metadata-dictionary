#!/usr/bin/env python3
"""
NF Resource Reference Service for Synapse Curation Grids

This service provides tooltip/reference data for research tools in Synapse curation grids
by querying the NF research tools database. Instead of auto-filling form fields, it displays
rich metadata in tooltips, keeping schemas minimal and data centralized.

Architecture:
    Synapse Table (syn51730943) → Tooltip Service → Tooltip Display
    (Source of truth)            (This service)    (Hover/click UI)

Approach:
    - Users select resource type and name in form
    - Hover over selection shows tooltip with metadata
    - Click opens detail page or edit form
    - Schema only stores: resourceType + resourceName (not all metadata)

Usage:
    # Start service
    export SYNAPSE_AUTH_TOKEN=your_token
    python services/tooltip_service.py

    # Query tooltip data
    curl http://localhost:8000/api/v1/tooltip/Cell%20Line/JH-2-002

Requirements:
    pip install fastapi uvicorn synapseclient pandas pydantic
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, Any
import synapseclient
import pandas as pd
import os
import logging
from functools import lru_cache
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NF Resource Reference Service",
    description="Tooltip/reference service for NF research tools in curation grids",
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


# Resource configuration
RESOURCE_CONFIG = {
    'Cell Line': {
        'table_id': 'syn51730943',
        'tool_type': 'cell_line',
        'key_field': 'toolName'
    },
    'Animal Model': {
        'table_id': 'syn51730943',
        'tool_type': 'animal',
        'key_field': 'toolName'
    },
    'Antibody': {
        'table_id': 'syn51730943',
        'tool_type': 'antibody',
        'key_field': 'toolName'
    },
    'Genetic Reagent': {
        'table_id': 'syn51730943',
        'tool_type': 'genetic_reagent',
        'key_field': 'toolName'
    }
}


class TooltipResponse(BaseModel):
    """Response model for tooltip data."""
    display_name: str
    type: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    detail_url: Optional[str] = None
    edit_url: Optional[str] = None
    last_updated: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "display_name": "JH-2-002",
                "type": "Cell Line",
                "metadata": {
                    "Species": "Homo sapiens",
                    "Tissue": "Brain",
                    "Diagnosis": "Glioblastoma",
                    "RRID": "CVCL_1234"
                },
                "detail_url": "https://synapse.org/tools/syn12345678",
                "edit_url": "https://synapse.org/tools/syn12345678/edit"
            }
        }


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
    logger.info("NF Resource Reference Service Starting")
    logger.info("=" * 70)

    # Test Synapse connection
    try:
        syn = get_synapse_client()
        profile = syn.getUserProfile()
        logger.info(f"✓ Connected as: {profile['userName']}")
    except Exception as e:
        logger.error(f"✗ Failed to connect to Synapse: {e}")
        raise

    logger.info(f"✓ Loaded {len(RESOURCE_CONFIG)} resource type configurations")
    logger.info("✓ Service ready")


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "NF Resource Reference Service",
        "version": "1.0.0",
        "status": "running",
        "approach": "Display tool metadata in tooltips instead of auto-filling form fields",
        "benefits": [
            "Minimal schema (only resourceType + resourceName)",
            "No data duplication",
            "Single source of truth",
            "Real-time metadata",
            "Easy to suggest edits"
        ],
        "endpoints": {
            "tooltip": "GET /api/v1/tooltip/{resource_type}/{resource_name}",
            "resources": "GET /api/v1/resources",
            "health": "GET /health"
        },
        "documentation": "See TOOLTIP_APPROACH.md for details"
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


@app.get("/api/v1/resources")
async def list_resources():
    """List available resource types."""
    resources = {}
    for resource_type, config in RESOURCE_CONFIG.items():
        resources[resource_type] = {
            "table_id": config['table_id'],
            "tool_type": config['tool_type'],
            "key_field": config['key_field']
        }

    return {
        "count": len(resources),
        "resource_types": resources
    }


@app.get("/api/v1/tooltip/{resource_type}/{resource_name}", response_model=TooltipResponse)
async def get_tooltip_data(resource_type: str, resource_name: str):
    """
    Get tooltip/reference data for a selected resource.

    This endpoint provides rich metadata for display in tooltips or detail panels,
    supporting the reference-based approach instead of auto-filling fields.

    Use case: User selects a tool (cell line, animal model, etc.) and hovers over
    it to see contextual information without cluttering the form with auto-filled fields.

    Example:
        GET /api/v1/tooltip/Cell%20Line/JH-2-002

    Returns:
        Tooltip data with formatted metadata, detail URL, and edit URL
    """
    logger.info(f"Tooltip request: {resource_type} / {resource_name}")

    # Get config for this resource type
    if resource_type not in RESOURCE_CONFIG:
        raise HTTPException(
            status_code=404,
            detail=f"Resource type not supported: {resource_type}. Available: {list(RESOURCE_CONFIG.keys())}"
        )

    config = RESOURCE_CONFIG[resource_type]

    # Query for tool data
    column_name = config['key_field']
    where_clause = f"{column_name} = '{resource_name}' AND toolType = '{config['tool_type']}'"

    try:
        df = query_synapse_table(config['table_id'], where_clause)

        if df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"Resource not found: {resource_name}"
            )

        # Get first row
        row = df.iloc[0]

        # Build metadata dictionary (key-value pairs for tooltip)
        metadata = {}

        # Define display order and labels
        field_labels = {
            'species': 'Species',
            'organism': 'Organism',
            'genotype': 'Genotype',
            'backgroundStrain': 'Background Strain',
            'tissue': 'Tissue',
            'organ': 'Organ',
            'cellType': 'Cell Type',
            'diagnosis': 'Diagnosis',
            'disease': 'Disease',
            'age': 'Age',
            'sex': 'Sex',
            'RRID': 'RRID',
            'modelSystemType': 'Type',
            'geneticModification': 'Genetic Modification',
            'manifestation': 'Manifestation',
            'institution': 'Institution',
            'description': 'Description'
        }

        # Add fields that are present
        for field_name, label in field_labels.items():
            if field_name in row and pd.notna(row[field_name]):
                value = row[field_name]

                # Format value
                if isinstance(value, (pd.Timestamp, datetime)):
                    value = value.isoformat()
                elif not isinstance(value, str):
                    value = str(value)

                # Truncate long descriptions
                if field_name == 'description' and len(value) > 200:
                    value = value[:197] + "..."

                metadata[label] = value

        # Build URLs
        detail_url = f"https://www.synapse.org/#!Synapse:{config['table_id']}/tables/query?queryString=SELECT%20*%20FROM%20{config['table_id']}%20WHERE%20{column_name}=%27{resource_name}%27"
        edit_url = f"https://www.synapse.org/#!Synapse:{config['table_id']}"

        # Get last updated time if available
        last_updated = None
        if 'modifiedOn' in row and pd.notna(row['modifiedOn']):
            last_updated = row['modifiedOn'].isoformat()

        logger.info(f"  → Returning tooltip with {len(metadata)} fields")

        return TooltipResponse(
            display_name=resource_name,
            type=resource_type,
            metadata=metadata,
            detail_url=detail_url,
            edit_url=edit_url,
            last_updated=last_updated
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"  ✗ Tooltip query failed: {e}")
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
