#!/usr/bin/env python3
"""FastAPI Backend for Thelawala Search Engine.

Endpoints:
    GET /                     -> Serve the web interface
    GET /api/search?q=...     -> Search products and return ranked SKU IDs
    GET /health               -> Service health check
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.search import get_search_engine, search_query

# Configure logger
logger = logging.getLogger("thelawala-api")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Project directories (cross-platform, relative to this file)
_BASE_DIR = Path(__file__).resolve().parent.parent
_STATIC_DIR = _BASE_DIR / "static"
_TEMPLATES_DIR = _BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: preload search engine index at startup."""
    logger.info("Initializing Thelawala Search Engine...")
    try:
        engine = get_search_engine()
        logger.info(
            "Search engine ready with %d catalog items and %d approved synonym mappings.",
            len(engine.products),
            len(engine.approved_synonyms_map),
        )
    except Exception as e:
        logger.error("Failed to initialize search engine at startup: %s", e, exc_info=True)
    yield


app = FastAPI(
    title="Thelawala Search Engine API",
    description="Probabilistic BM25 product retrieval engine with approved synonym expansion and sponsored priority.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for open, robust frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Mount static assets if directory exists
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Sanitize unexpected exceptions without leaking internal stack traces."""
    logger.error("Unhandled internal error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred while processing the request."},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Health status endpoint."""
    return {"status": "ok"}


@app.get("/")
async def serve_index() -> FileResponse:
    """Serve the single-page search web interface."""
    index_file = _TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Index template not found")
    return FileResponse(index_file)


@app.get("/api/search")
async def api_search(
    q: str = Query(..., description="Product query string"),
    limit: int = Query(10, description="Maximum number of results to return (1-50)"),
) -> dict[str, Any]:
    """Search for catalog products matching query, returning ranked SKU IDs."""
    # 1. Validate query
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty")

    # 2. Validate limit
    if limit < 1 or limit > 50:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 50")

    query_str = q.strip()

    try:
        engine = get_search_engine()
        results = search_query(query_str, top_n=limit, engine=engine)
        return {
            "query": query_str,
            "results": results,
        }
    except Exception as e:
        logger.error("Error executing query '%s': %s", query_str, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Search retrieval failure")
