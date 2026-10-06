from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from ..models import GenerationRequest, TextGenerationProvider
from .models import SearchHit, SearchQuery


@dataclass(frozen=True, slots=True)
class RerankScore:
    chunk_id: str
    score: float
    rank: int


@runtime_checkable
class Reranker(Protocol):
    name: str

    def rerank(
        self,
        request: SearchQuery,
        hits: Sequence[SearchHit],
    ) -> tuple[RerankScore, ...]: ...


@runtime_checkable
class CrossEncoderScorer(Protocol):
    provider_name: str
    model_name: str

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]: ...


class CrossEncoderReranker:
    name = "cross-encoder"

    def __init__(
        self,
        scorer: CrossEncoderScorer,
        *,
        max_candidates: int = 20,
        max_candidate_chars: int = 1800,
    ) -> None:
        if max_candidates < 1 or max_candidates > 100:
            raise ValueError("max_candidates must be between 1 and 100")
        self.scorer = scorer
        self.max_candidates = max_candidates
        self.max_candidate_chars = max_candidate_chars

    @property
    def provider(self) -> CrossEncoderScorer:
        return self.scorer

    def rerank(
        self,
        request: SearchQuery,
        hits: Sequence[SearchHit],
    ) -> tuple[RerankScore, ...]:
        bounded = list(hits[: self.max_candidates])
        if not bounded:
            return ()
        pairs = [
            (
                request.query,
                ((hit.title or "") + "\n" + hit.text[: self.max_candidate_chars]).strip(),
            )
            for hit in bounded
        ]
        scores = list(self.scorer.score_pairs(pairs))
        if len(scores) != len(bounded):
            raise ValueError("cross-encoder scorer returned an unexpected score count")
        ranked = sorted(
            zip(bounded, scores),
            key=lambda item: (-float(item[1]), item[0].chunk_id),
        )
        return tuple(
            RerankScore(hit.chunk_id, float(score), rank)
            for rank, (hit, score) in enumerate(ranked, start=1)
        )


class ReasoningReranker:
    name = "reasoning"

    def __init__(
        self,
        provider: TextGenerationProvider,
        *,
        max_candidates: int = 20,
        max_candidate_chars: int = 1800,
    ) -> None:
        if max_candidates < 1 or max_candidates > 100:
            raise ValueError("max_candidates must be between 1 and 100")
        self.provider = provider
        self.max_candidates = max_candidates
        self.max_candidate_chars = max_candidate_chars

    def rerank(
        self,
        request: SearchQuery,
        hits: Sequence[SearchHit],
    ) -> tuple[RerankScore, ...]:
        bounded = list(hits[: self.max_candidates])
        if not bounded:
            return ()
        candidates = [
            {
                "chunk_id": hit.chunk_id,
                "title": hit.title,
                "text": hit.text[: self.max_candidate_chars],
            }
            for hit in bounded
        ]
        response = self.provider.generate(
            GenerationRequest(
                system_prompt=(
                    "You are a retrieval reranker. Rank only the supplied candidates by "
                    "relevance to the query. Do not add candidates. Return strict JSON only."
                ),
                prompt=(
                    f"Query: {request.query}\n"
                    "Return a JSON array of objects with chunk_id and score (0..1), "
                    "best first. Candidates:\n"
                    + json.dumps(candidates, ensure_ascii=False)
                ),
                max_tokens=min(2048, 128 + len(bounded) * 64),
                temperature=0.0,
                metadata={"operation": "rerank", "candidate_count": len(bounded)},
            )
        )
        return self._parse(response.text, allowed={hit.chunk_id for hit in bounded})

    @staticmethod
    def _parse(text: str, *, allowed: set[str]) -> tuple[RerankScore, ...]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("reranker returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("reranker response must be a JSON array")
        scores: list[RerankScore] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id") or "")
            if chunk_id not in allowed or chunk_id in seen:
                continue
            try:
                score = float(item["score"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0.0 <= score <= 1.0:
                continue
            seen.add(chunk_id)
            scores.append(RerankScore(chunk_id, score, len(scores) + 1))
        return tuple(scores)
