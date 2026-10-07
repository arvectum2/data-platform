from __future__ import annotations

import json
from pathlib import Path

import pytest

from arvectum_data.evaluation.ocr_gold_review import (
    OcrGoldReviewValidationError,
    validate_ocr_gold_review_packet,
)


ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "benchmarks" / "reviews" / "ocr_gold_public_v1_review_request.json"


def test_repository_ocr_gold_review_packet_is_valid_and_pending() -> None:
    result = validate_ocr_gold_review_packet(PACKET)

    assert result["review_id"] == "public-v1-ocr-human-gold"
    assert result["status"] == "pending_human_review"
    assert result["items"] == 2
    assert result["accepted_items"] == 0
    assert result["pending_items"] == 2


def test_accepted_item_requires_explicit_human_identity(tmp_path: Path) -> None:
    payload = json.loads(PACKET.read_text(encoding="utf-8"))
    payload["items"][0]["review"] = {
        "status": "accepted",
        "reviewer_kind": "model",
        "reviewer": "automated evaluator",
        "reviewed_at": "2026-10-07",
        "notes": None,
    }
    candidate = tmp_path / "review.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        OcrGoldReviewValidationError,
        match="reviewer_kind=human",
    ):
        validate_ocr_gold_review_packet(candidate, benchmarks_root=ROOT / "benchmarks")


def test_packet_cannot_claim_acceptance_while_items_are_pending(tmp_path: Path) -> None:
    payload = json.loads(PACKET.read_text(encoding="utf-8"))
    payload["status"] = "accepted"
    candidate = tmp_path / "review.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        OcrGoldReviewValidationError,
        match="every item",
    ):
        validate_ocr_gold_review_packet(candidate, benchmarks_root=ROOT / "benchmarks")
