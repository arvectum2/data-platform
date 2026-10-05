from __future__ import annotations

import json

from arvectum_data.engine import FieldSpec, RawAsset, ReasoningCandidateProvider
from arvectum_data.models import ModelDescriptor, ModelLocality, ModelResponse, ModelRole


class FakeProvider:
    descriptor = ModelDescriptor(
        ModelRole.REASONING,
        "fake",
        "extractor",
        "1",
        ModelLocality.LOCAL,
        ("text-generation",),
    )

    def __init__(self, payload):
        self.payload = payload

    def generate(self, request):
        return ModelResponse(
            json.dumps(self.payload, ensure_ascii=False),
            "fake",
            "extractor",
            "1",
            ModelLocality.LOCAL,
            1.0,
        )


def test_reasoning_extractor_requires_verbatim_source_evidence():
    provider = ReasoningCandidateProvider(
        FakeProvider(
            [
                {
                    "field_key": "price",
                    "value": 1999,
                    "confidence": 0.91,
                    "excerpt": "Цена: 1999 руб.",
                },
                {
                    "field_key": "customer",
                    "value": "invented",
                    "confidence": 0.99,
                    "excerpt": "not in source",
                },
            ]
        )
    )
    result = provider.candidates(
        RawAsset(asset_id="one", text="Закупка\nЦена: 1999 руб.\n"),
        (FieldSpec("price"), FieldSpec("customer")),
    )

    assert len(result) == 1
    assert result[0].field_key == "price"
    assert result[0].value == 1999
    assert result[0].evidence[0].excerpt == "Цена: 1999 руб."
    assert result[0].evidence[0].metadata["evidence_verified"] is True


def test_reasoning_extractor_rejects_invalid_json():
    provider = ReasoningCandidateProvider(FakeProvider([]))
    try:
        provider._parse("not-json", source="x", allowed={"x"})
    except ValueError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("invalid JSON must fail")



def test_extraction_engine_coerces_schema_types_and_rejects_invalid_values():
    from arvectum_data.engine import AutoDiscoveryProvider, ExtractionEngine

    result = ExtractionEngine((AutoDiscoveryProvider(),)).extract(
        RawAsset(asset_id="typed", text="Count: 42\nEnabled: да\nBroken: many"),
        (
            FieldSpec("count", value_type="integer", aliases=("Count",), min_confidence=0.5),
            FieldSpec("enabled", value_type="boolean", aliases=("Enabled",), min_confidence=0.5),
            FieldSpec("broken", value_type="integer", aliases=("Broken",), required=True, min_confidence=0.5),
        ),
    )

    assert result.values()["count"] == 42
    assert result.values()["enabled"] is True
    assert "broken" in result.unresolved_required_fields
