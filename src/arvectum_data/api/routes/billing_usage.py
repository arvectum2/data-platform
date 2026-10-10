from __future__ import annotations
from fastapi import APIRouter
from .context import RouteContext
from .billing_routes import register_billing_routes
from .usage_routes import register_usage_routes

def register_billing_usage_routes(router: APIRouter, context: RouteContext) -> None:
    register_billing_routes(router, context)
    register_usage_routes(router, context)
