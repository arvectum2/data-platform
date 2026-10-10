from __future__ import annotations

def operation_name(method: str, path: str) -> str | None:
    if method == "POST" and path == "/v1/process/document":
        return "process"
    if method == "POST" and path in {"/v1/ingest/document", "/v1/ingest/url"}:
        return "ingest"
    if method == "POST" and path == "/v1/search":
        return "search"
    if method == "POST" and path == "/v1/answer":
        return "answer"
    if method == "POST" and path == "/v1/research":
        return "research"
    if method == "POST" and path == "/v1/discover":
        return "discover"
    if method == "POST" and path == "/v1/extract":
        return "extract"
    if method == "POST" and path == "/v1/index/rebuild":
        return "reindex"
    return None


def usage_operation_name(method: str, path: str) -> str | None:
    if method == "POST" and path == "/v1/search":
        return "search"
    if method == "POST" and path == "/v1/answer":
        return "answer"
    if method == "POST" and path == "/v1/research":
        return "research"
    if method == "POST" and path == "/v1/memory":
        return "memory_write"
    if method == "DELETE" and path.startswith("/v1/memory/"):
        return "memory_delete"
    return None
