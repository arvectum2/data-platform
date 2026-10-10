from __future__ import annotations
from fastapi import APIRouter
from .context import RouteContext
from .search_routes import register_search_routes
from .connector_routes import register_connector_routes

def register_search_connector_routes(router: APIRouter, context: RouteContext) -> None:
    register_search_routes(router, context)
    register_connector_routes(router, context)
