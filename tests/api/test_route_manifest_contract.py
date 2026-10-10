"""Pin all public endpoints when splitting large FastAPI route registrars."""
from __future__ import annotations

import json
from pathlib import Path

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings


def test_openapi_path_method_tag_and_status_contract_is_stable():
    expected = json.loads((
        Path(__file__).parents[1] / "fixtures" / "data_platform_route_manifest.json"
    ).read_text(encoding="utf-8"))
    api = create_app(Settings(_env_file=None, environment="test"), platform_service=object())
    actual = {}
    for path, methods in api.openapi()["paths"].items():
        actual[path] = {}
        for method, operation in methods.items():
            actual[path][method] = {
                "operation_id": operation["operationId"],
                "tags": operation.get("tags", []),
                "parameters": [
                    [p["name"], p["in"], p.get("required", False)]
                    for p in operation.get("parameters", [])
                ],
                "request_content": sorted(operation.get("requestBody", {}).get("content", {})),
                "response_status": sorted(operation.get("responses", {})),
            }
    assert actual == expected
    assert len(actual) == 55
