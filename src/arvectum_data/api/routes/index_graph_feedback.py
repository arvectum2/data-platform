from __future__ import annotations
from fastapi import APIRouter
from .context import RouteContext
from .index_routes import register_index_routes
from .graph_routes import register_graph_routes
from .feedback_routes import register_feedback_routes

def register_index_graph_feedback_routes(router: APIRouter, context: RouteContext) -> None:
    register_index_routes(router, context)
    register_graph_routes(router, context)
    register_feedback_routes(router, context)
