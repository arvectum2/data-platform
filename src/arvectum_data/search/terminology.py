"""Provider-free, domain-neutral terminology matching and synonym expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .expansion import DictionaryQueryExpander, QueryExpansion


@dataclass(frozen=True, slots=True)
class TerminologyGroup:
    id: str
    aliases: tuple[str, ...]
    contexts: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    ambiguous_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}", self.id):
            raise ValueError("terminology id must be a safe 2..64 character slug")
        if not 1 <= len(self.aliases) <= 20:
            raise ValueError("terminology group needs 1..20 aliases")
        if len(self.contexts) > 16 or len(self.exclusions) > 16 or len(self.ambiguous_aliases) > 16:
            raise ValueError("terminology context, exclusions or ambiguity list too long")
        aliases = _unique(self.aliases)
        if not aliases or any(not 2 <= len(x) <= 120 for x in aliases):
            raise ValueError("terminology aliases must have 2..120 characters")
        object.__setattr__(self, "aliases", aliases)
        for field in ("contexts", "exclusions", "ambiguous_aliases"):
            terms = _unique(getattr(self, field))
            if any(not 2 <= len(x) <= 120 for x in terms):
                raise ValueError(f"invalid terminology {field} term length")
            object.__setattr__(self, field, terms)
        if any(x.casefold() not in {a.casefold() for a in aliases} for x in self.ambiguous_aliases):
            raise ValueError("ambiguous_aliases must be present in aliases")


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen = set()
    for v in values:
        if not isinstance(v, str):
            raise ValueError("terms must be strings")
        term = v.strip()
        if term.casefold() not in seen and term:
            seen.add(term.casefold())
            result.append(term)
    return tuple(result)


def _has_term(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE))


CONTEXT_NEARBY_CHARS = 240


def _near_contexts(text: str, term: str, contexts: tuple[str, ...]) -> list[str]:
    """Require a technical context near its actual alias, not elsewhere in a long hit."""
    if not contexts:
        return []
    accepted = []
    pattern = r"(?<!\\w)" + re.escape(term) + r"(?!\\w)"
    for match in re.finditer(pattern, text, re.IGNORECASE):
        fragment = text[
            max(0, match.start() - CONTEXT_NEARBY_CHARS):
            min(len(text), match.end() + CONTEXT_NEARBY_CHARS)
        ]
        for ctx in contexts:
            if ctx not in accepted and _has_term(fragment, ctx):
                accepted.append(ctx)
        if len(accepted) == len(contexts):
            break
    return accepted


def match_terminology(
    text: str, groups: tuple[TerminologyGroup, ...],
) -> tuple[dict[str, object], ...]:
    """Find explicit terms; ambiguous aliases need *nearby* technical context.

    Exclusions disqualify the group in the chunk. A matching term is only a
    search candidate, never evidence of procurement award or equipment supply.
    """
    text = text[:60_000]
    hits = []
    for group in groups:
        if any(_has_term(text, term) for term in group.exclusions):
            continue
        possible = [term for term in group.aliases if _has_term(text, term)]
        if not possible:
            continue
        ambiguous = {a.casefold() for a in group.ambiguous_aliases}
        terms = []
        contexts = []
        for term in possible:
            nearby = _near_contexts(text, term, group.contexts)
            if term.casefold() in ambiguous and not nearby:
                continue
            terms.append(term)
            for ctx in nearby:
                if ctx not in contexts:
                    contexts.append(ctx)
        if not terms:
            continue
        hits.append({
            "id": group.id,
            "terms": terms,
            "contexts": contexts,
            "classification": "explicit_technical_candidate",
        })
    return tuple(hits)


def expand_terminology(
    query: str, groups: tuple[TerminologyGroup, ...], *, limit: int = 5,
) -> tuple[QueryExpansion, ...]:
    """Use existing dictionary expansion, preserving non-terminology query text."""
    dictionary: dict[str, list[str]] = {}
    for group in groups:
        for term in group.aliases:
            dictionary.setdefault(term, [])
            for other in group.aliases:
                if other.casefold() != term.casefold() and other not in dictionary[term]:
                    dictionary[term].append(other)
    return DictionaryQueryExpander(dictionary).expand(query, limit=limit)
