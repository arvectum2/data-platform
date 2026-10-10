from __future__ import annotations
from fastapi import APIRouter
from .context import RouteContext
from .research_routes import register_research_routes
from .answer_routes import register_answer_routes

def register_research_answer_routes(router: APIRouter, context: RouteContext) -> None:
    register_research_routes(router, context)
    register_answer_routes(router, context)
