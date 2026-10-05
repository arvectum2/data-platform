from __future__ import annotations


def build_collection_id(namespace: str, *segments: str) -> str:
    parts = [namespace, *segments]
    normalized: list[str] = []
    for value in parts:
        part = str(value).strip()
        if not part:
            raise ValueError("collection id segments must not be blank")
        if ":" in part:
            raise ValueError("collection id segments must not contain colon")
        normalized.append(part)
    return ":".join(normalized)
