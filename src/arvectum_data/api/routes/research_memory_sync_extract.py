from __future__ import annotations

from fastapi import APIRouter

from .context import RouteContext
from .research_answer_routes import register_research_answer_routes
from .memory_routes import register_memory_routes
from .refresh_routes import register_refresh_routes
from .extract_routes import register_extract_routes


def register_research_memory_sync_extract_routes(router: APIRouter, context: RouteContext) -> None:
    """Register grouped v1 endpoints without altering their route order."""
    register_research_answer_routes(router, context)
    register_memory_routes(router, context)
    register_refresh_routes(router, context)
    register_extract_routes(router, context)
