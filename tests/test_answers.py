from __future__ import annotations

import json

import pytest

from arvectum_data.answers import ReasoningAnswerSynthesizer
from arvectum_data.models import ModelDescriptor, ModelLocality, ModelResponse, ModelRole
from arvectum_data.search import SearchEvidence, SearchHit, SearchScores


class FakeProvider:
    descriptor = ModelDescriptor(
        ModelRole.REASONING, "fake", "answer", "1", ModelLocality.LOCAL, ("text-generation",)
    )

    def __init__(self, payload):
        self.payload = payload

    def generate(self, request):
        return ModelResponse(
            json.dumps(self.payload, ensure_ascii=False),
            "fake", "answer", "1", ModelLocality.LOCAL, 1.0,
        )


def hit(chunk_id: str, text: str) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id="doc",
        resource_id="resource",
        canonical_uri=f"test://{chunk_id}",
        title="Evidence",
        preview=text,
        text=text,
        scores=SearchScores(1.0, 1.0, 1.0),
        evidence=(SearchEvidence("resource", "doc", chunk_id, f"test://{chunk_id}"),),
        metadata={"collection_id": "tests:knowledge"},
    )


def test_answer_requires_claim_level_supplied_chunk_ids():
    synth = ReasoningAnswerSynthesizer(
        FakeProvider(
            {
                "answer": "Цена составляет 1999 рублей.",
                "claims": [{"text": "Цена — 1999 рублей.", "chunk_ids": ["c1"]}],
                "contradictions": [],
                "uncertainty": None,
                "abstained": False,
            }
        )
    )
    result = synth.synthesize("Какая цена?", [hit("c1", "Цена: 1999 рублей.")])
    assert result.answer == "Цена составляет 1999 рублей."
    assert result.claims[0].chunk_ids == ("c1",)
    assert result.abstained is False


def test_answer_rejects_citation_outside_bounded_evidence():
    synth = ReasoningAnswerSynthesizer(
        FakeProvider(
            {
                "answer": "Выдумка.",
                "claims": [{"text": "Выдумка.", "chunk_ids": ["invented"]}],
                "contradictions": [],
                "uncertainty": None,
                "abstained": False,
            }
        )
    )
    with pytest.raises(ValueError, match="outside supplied context"):
        synth.synthesize("Что известно?", [hit("c1", "Только этот факт.")])


def test_answer_abstains_without_evidence_without_calling_model():
    result = ReasoningAnswerSynthesizer(FakeProvider({})).synthesize("Что известно?", [])
    assert result.abstained is True
    assert result.answer is None
    assert result.uncertainty

def test_answer_accepts_single_json_code_fence_without_prose():
    payload = {
        "answer": "Цена составляет 1999 рублей.",
        "claims": [{"text": "Цена — 1999 рублей.", "chunk_ids": ["c1"]}],
        "contradictions": [],
        "uncertainty": None,
        "abstained": False,
    }

    class FencedProvider(FakeProvider):
        def generate(self, request):
            fence = chr(96) * 3
            return ModelResponse(
                fence + "json\n"
                + json.dumps(self.payload, ensure_ascii=False)
                + "\n" + fence,
                "fake",
                "answer",
                "1",
                ModelLocality.LOCAL,
                1.0,
            )

    result = ReasoningAnswerSynthesizer(FencedProvider(payload)).synthesize(
        "Какая цена?",
        [hit("c1", "Цена: 1999 рублей.")],
    )

    assert result.answer == "Цена составляет 1999 рублей."
    assert result.claims[0].chunk_ids == ("c1",)


def test_answer_rejects_fenced_json_with_extra_prose_or_wrong_language():
    fence = chr(96) * 3
    raws = [
        "Вот ответ:\n" + fence + "json\n"
        + '{"answer": null, "claims": [], "contradictions": [], "uncertainty": null, "abstained": true}'
        + "\n" + fence,
        fence + "json\n" + '{"answer": null}' + "\n" + fence + "\nлишний текст",
        fence + "python\n" + '{"answer": null}' + "\n" + fence,
    ]
    for raw in raws:
        with pytest.raises(ValueError, match="invalid JSON"):
            ReasoningAnswerSynthesizer._parse(raw, allowed=set())

def test_answer_prompt_requires_explicit_abstention_contract():
    captured = {}

    class CapturingProvider(FakeProvider):
        def generate(self, request):
            captured["system_prompt"] = request.system_prompt
            return super().generate(request)

    synth = ReasoningAnswerSynthesizer(
        CapturingProvider(
            {
                "answer": None,
                "claims": [],
                "contradictions": [],
                "uncertainty": "Нет данных.",
                "abstained": True,
            }
        )
    )
    synth.synthesize("Какая цена?", [hit("c1", "Только цвет: синий.")])

    prompt = captured["system_prompt"]
    assert "answer=null" in prompt
    assert "abstained=true" in prompt
    assert "every evidence hop" in prompt
