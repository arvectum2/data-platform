from __future__ import annotations
from fastapi import APIRouter
from .context import RouteContext
from .entity_routes import register_entity_routes
from .graph_relation_routes import register_graph_relation_routes

def register_graph_routes(router: APIRouter, context: RouteContext) -> None:
    register_entity_routes(router, context)
    register_graph_relation_routes(router, context)
