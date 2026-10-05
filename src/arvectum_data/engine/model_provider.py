from __future__ import annotations

import json
from collections.abc import Sequence

from ..models import GenerationRequest, TextGenerationProvider
from .models import Candidate, Evidence, FieldSpec, RawAsset


class ReasoningCandidateProvider:
    """Optional evidence-constrained structured extraction provider."""

    name = "reasoning"

    def __init__(self, provider: TextGenerationProvider, *, max_source_chars: int = 24_000) -> None:
        self.provider = provider
        self.max_source_chars = max_source_chars

    def candidates(
        self,
        asset: RawAsset,
        fields: Sequence[FieldSpec],
    ) -> Sequence[Candidate]:
        source = (asset.text or "").strip()
        if not source:
            return ()
        source = source[: self.max_source_chars]
        schema = [
            {
                "key": field.key,
                "required": field.required,
                "aliases": list(field.aliases),
            }
            for field in fields
        ]
        response = self.provider.generate(
            GenerationRequest(
                system_prompt=(
                    "Extract only values explicitly supported by SOURCE. Never infer missing facts. "
                    "For every value return an exact evidence excerpt copied from SOURCE. "
                    "Return strict JSON only."
                ),
                prompt=(
                    "SCHEMA:\n"
                    + json.dumps(schema, ensure_ascii=False)
                    + "\nSOURCE:\n"
                    + source
                    + "\nReturn a JSON array of objects: "
                    '[{"field_key":"...","value":...,"confidence":0.0,"excerpt":"exact source text"}]. '
                    "Omit unsupported fields."
                ),
                max_tokens=2048,
                temperature=0.0,
                metadata={"operation": "structured-extraction", "field_count": len(fields)},
            )
        )
        return self._parse(response.text, source=source, allowed={field.key for field in fields})

    @classmethod
    def _parse(
        cls,
        text: str,
        *,
        source: str,
        allowed: set[str],
    ) -> tuple[Candidate, ...]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("structured extractor returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("structured extractor response must be a JSON array")

        result: list[Candidate] = []
        seen: set[tuple[str, str]] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            field_key = item.get("field_key")
            excerpt = item.get("excerpt")
            confidence = item.get("confidence")
            if field_key not in allowed or not isinstance(excerpt, str) or excerpt not in source:
                continue
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                continue
            confidence = float(confidence)
            if not 0.0 <= confidence <= 1.0:
                continue
            value = item.get("value")
            if value is None:
                continue
            identity = (field_key, json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
            if identity in seen:
                continue
            seen.add(identity)
            result.append(
                Candidate(
                    field_key=field_key,
                    value=value,
                    confidence=confidence,
                    provider=cls.name,
                    evidence=(
                        Evidence(
                            kind="model_extraction",
                            source_ref="document:text",
                            excerpt=excerpt[:500],
                            metadata={"evidence_verified": True},
                        ),
                    ),
                )
            )
        return tuple(result)
