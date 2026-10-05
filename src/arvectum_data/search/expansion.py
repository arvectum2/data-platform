from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence, runtime_checkable

from ..models import GenerationRequest, TextGenerationProvider


@dataclass(frozen=True, slots=True)
class QueryExpansion:
    text: str
    source: str
    weight: float = 0.5


@runtime_checkable
class QueryExpander(Protocol):
    name: str

    def expand(self, query: str, *, limit: int) -> tuple[QueryExpansion, ...]: ...


class DictionaryQueryExpander:
    name = "dictionary"

    def __init__(self, dictionary: Mapping[str, Sequence[str]]) -> None:
        self.dictionary = {
            key.casefold().strip(): tuple(value.strip() for value in values if value.strip())
            for key, values in dictionary.items()
            if key.strip()
        }

    def expand(self, query: str, *, limit: int) -> tuple[QueryExpansion, ...]:
        if limit < 1:
            return ()
        normalized = query.casefold()
        variants: list[QueryExpansion] = []
        seen = {query.casefold().strip()}
        for term, replacements in self.dictionary.items():
            if not re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized):
                continue
            for replacement in replacements:
                expanded = re.sub(
                    rf"(?<!\w){re.escape(term)}(?!\w)",
                    replacement,
                    query,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip()
                key = expanded.casefold()
                if not expanded or key in seen:
                    continue
                seen.add(key)
                variants.append(QueryExpansion(expanded, f"dictionary:{term}"))
                if len(variants) >= limit:
                    return tuple(variants)
        return tuple(variants)


class ReasoningQueryExpander:
    name = "reasoning"

    def __init__(self, provider: TextGenerationProvider) -> None:
        self.provider = provider

    def expand(self, query: str, *, limit: int) -> tuple[QueryExpansion, ...]:
        if limit < 1:
            return ()
        response = self.provider.generate(
            GenerationRequest(
                system_prompt=(
                    "Generate conservative search-query variants. Preserve the user's intent. "
                    "Do not add facts, entities or constraints not present in the query. "
                    "Return strict JSON only."
                ),
                prompt=(
                    f"Query: {query}\nReturn a JSON array with at most {limit} strings. "
                    "Use synonyms, abbreviations or domain-equivalent wording only."
                ),
                max_tokens=min(768, 96 + limit * 64),
                temperature=0.0,
                metadata={"operation": "query-expansion", "variant_limit": limit},
            )
        )
        return self._parse(response.text, query=query, limit=limit)

    @staticmethod
    def _parse(text: str, *, query: str, limit: int) -> tuple[QueryExpansion, ...]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("query expander returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("query expander response must be a JSON array")
        seen = {query.casefold().strip()}
        result: list[QueryExpansion] = []
        for item in payload:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            key = cleaned.casefold()
            if not cleaned or key in seen or len(cleaned) > 4096:
                continue
            seen.add(key)
            result.append(QueryExpansion(cleaned, "reasoning"))
            if len(result) >= limit:
                break
        return tuple(result)
