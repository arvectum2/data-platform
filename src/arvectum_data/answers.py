from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from .models import GenerationRequest, TextGenerationProvider
from .search import SearchHit


@dataclass(frozen=True, slots=True)
class AnswerClaim:
    text: str
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str | None
    claims: tuple[AnswerClaim, ...]
    contradictions: tuple[str, ...]
    uncertainty: str | None
    abstained: bool


class ReasoningAnswerSynthesizer:
    """Synthesize only from a bounded caller-supplied evidence set."""

    def __init__(
        self,
        provider: TextGenerationProvider,
        *,
        max_hits: int = 12,
        max_hit_chars: int = 2400,
    ) -> None:
        if max_hits < 1 or max_hits > 50:
            raise ValueError("max_hits must be between 1 and 50")
        self.provider = provider
        self.max_hits = max_hits
        self.max_hit_chars = max_hit_chars

    def synthesize(self, query: str, hits: Sequence[SearchHit]) -> GroundedAnswer:
        if not query.strip():
            raise ValueError("query must not be blank")
        bounded = tuple(hits[: self.max_hits])
        if not bounded:
            return GroundedAnswer(
                answer=None,
                claims=(),
                contradictions=(),
                uncertainty="No evidence was supplied.",
                abstained=True,
            )
        evidence = [
            {
                "chunk_id": hit.chunk_id,
                "collection_id": hit.metadata.get("collection_id"),
                "canonical_uri": hit.canonical_uri,
                "title": hit.title,
                "text": hit.text[: self.max_hit_chars],
                "scores": {
                    "fusion": hit.scores.fusion,
                    "rerank": hit.scores.rerank,
                },
            }
            for hit in bounded
        ]
        response = self.provider.generate(
            GenerationRequest(
                system_prompt=(
                    "Answer using ONLY the supplied EVIDENCE. Every material factual claim "
                    "must cite one or more supplied chunk_id values. Surface contradictions. "
                    "If evidence is insufficient, abstain. Return strict JSON only."
                ),
                prompt=(
                    f"QUESTION: {query}\nEVIDENCE:\n"
                    + json.dumps(evidence, ensure_ascii=False)
                    + "\nReturn {answer, claims:[{text,chunk_ids}], contradictions:[string], "
                    "uncertainty:string|null, abstained:boolean}."
                ),
                max_tokens=2048,
                temperature=0.0,
                metadata={"operation": "answer-synthesis", "evidence_count": len(bounded)},
            )
        )
        return self._parse(
            response.text,
            allowed={hit.chunk_id for hit in bounded},
        )

    @staticmethod
    def _parse(text: str, *, allowed: set[str]) -> GroundedAnswer:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("answer synthesizer returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("answer synthesizer response must be an object")
        raw_claims = payload.get("claims", [])
        if not isinstance(raw_claims, list):
            raise ValueError("claims must be an array")
        claims: list[AnswerClaim] = []
        for item in raw_claims:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError("every claim must contain text")
            chunk_ids = item.get("chunk_ids")
            if not isinstance(chunk_ids, list) or not chunk_ids:
                raise ValueError("every claim must cite evidence")
            normalized = tuple(dict.fromkeys(str(value) for value in chunk_ids))
            if any(chunk_id not in allowed for chunk_id in normalized):
                raise ValueError("claim cites evidence outside supplied context")
            claims.append(AnswerClaim(item["text"].strip(), normalized))

        abstained = bool(payload.get("abstained", False))
        answer = payload.get("answer")
        if answer is not None and not isinstance(answer, str):
            raise ValueError("answer must be string or null")
        if answer and not claims and not abstained:
            raise ValueError("non-abstained answer must contain grounded claims")
        contradictions = payload.get("contradictions", [])
        if not isinstance(contradictions, list) or not all(
            isinstance(item, str) for item in contradictions
        ):
            raise ValueError("contradictions must be an array of strings")
        uncertainty = payload.get("uncertainty")
        if uncertainty is not None and not isinstance(uncertainty, str):
            raise ValueError("uncertainty must be string or null")
        return GroundedAnswer(
            answer=answer.strip() if answer else None,
            claims=tuple(claims),
            contradictions=tuple(item.strip() for item in contradictions if item.strip()),
            uncertainty=uncertainty.strip() if uncertainty else None,
            abstained=abstained,
        )
