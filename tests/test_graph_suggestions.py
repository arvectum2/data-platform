from __future__ import annotations

import json

from arvectum_data.graph import EvidenceGraphSuggester
from arvectum_data.models import ModelDescriptor, ModelLocality, ModelResponse, ModelRole
from arvectum_data.search import SearchEvidence, SearchHit, SearchScores


class FakeProvider:
    descriptor = ModelDescriptor(
        ModelRole.REASONING, "fake", "graph", "1", ModelLocality.LOCAL, ("text-generation",)
    )

    def __init__(self, payload):
        self.payload = payload

    def generate(self, request):
        return ModelResponse(
            json.dumps(self.payload),
            "fake",
            "graph",
            "1",
            ModelLocality.LOCAL,
            1.0,
        )


def hit(chunk_id="c1"):
    return SearchHit(
        chunk_id=chunk_id,
        document_id="d1",
        resource_id="r1",
        canonical_uri="test://evidence",
        title="Evidence",
        preview="Acme supplies Widget.",
        text="Acme supplies Widget.",
        scores=SearchScores(1.0, 1.0, 1.0),
        evidence=(SearchEvidence("r1", "d1", chunk_id, "test://evidence"),),
        metadata={"collection_id": "test"},
    )


def test_graph_suggestions_are_constrained_to_supplied_entities_and_chunks():
    suggester = EvidenceGraphSuggester(
        FakeProvider(
            {
                "aliases": [
                    {"entity_id": "e1", "alias": "ACME", "chunk_id": "c1"},
                    {"entity_id": "invented", "alias": "Bad", "chunk_id": "c1"},
                ],
                "relations": [
                    {
                        "source_entity_id": "e1",
                        "target_entity_id": "e2",
                        "relation_type": "supplies",
                        "chunk_id": "c1",
                        "valid_from": None,
                        "valid_to": None,
                    },
                    {
                        "source_entity_id": "e1",
                        "target_entity_id": "e2",
                        "relation_type": "invented",
                        "chunk_id": "missing",
                    },
                ],
            }
        )
    )
    result = suggester.suggest(
        entities=[
            {"entity_id": "e1", "entity_type": "supplier", "canonical_name": "Acme"},
            {"entity_id": "e2", "entity_type": "product", "canonical_name": "Widget"},
        ],
        hits=[hit()],
    )
    assert [(item.entity_id, item.alias) for item in result.aliases] == [("e1", "ACME")]
    assert len(result.relations) == 1
    assert result.relations[0].relation_type == "supplies"
    assert result.relations[0].chunk_id == "c1"
