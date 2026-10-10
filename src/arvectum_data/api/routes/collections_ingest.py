from __future__ import annotations
from fastapi import APIRouter
from .context import RouteContext
from .collection_routes import register_collection_routes
from .ingest_routes import register_ingest_routes

def register_collections_ingest_routes(router: APIRouter, context: RouteContext) -> None:
    register_collection_routes(router, context)
    register_ingest_routes(router, context)
