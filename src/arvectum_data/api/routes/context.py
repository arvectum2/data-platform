from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException

from ..config import Settings


@dataclass(frozen=True, slots=True)
class RouteContext:
    settings: Settings
    app: FastAPI
    runtime: Callable[[], Any]
    require_consumer_identity: Callable[[str | None, str | None], str]
    map_service_error: Callable[[Exception], HTTPException]
