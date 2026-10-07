from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class OcrGoldReviewValidationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OcrGoldReviewValidationError(message)


def _validate_optional_pinned_file(
    packet: Mapping[str, Any],
    *,
    root: Path,
    path_key: str,
    sha_key: str,
    label: str,
) -> None:
    relative = str(packet.get(path_key) or "").strip()
    expected_sha = str(packet.get(sha_key) or "").strip()
    if not relative and not expected_sha:
        return
    _require(relative and expected_sha, f"{label} path and SHA-256 must be provided together")
    _require(
        len(expected_sha) == 64 and all(ch in "0123456789abcdef" for ch in expected_sha),
        f"{label} SHA-256 is invalid",
    )
    path = (root / relative).resolve()
    _require(path.is_relative_to(root.resolve()), f"{label} path escapes benchmarks root")
    _require(path.is_file(), f"{label} file is missing")
    _require(_sha256(path) == expected_sha, f"{label} hash mismatch")


def validate_ocr_gold_review_packet(
    packet_path: Path,
    *,
    benchmarks_root: Path | None = None,
) -> dict[str, Any]:
    root = benchmarks_root or packet_path.resolve().parents[1]
    packet = json.loads(packet_path.read_text(encoding="utf-8"))

    _require(packet.get("version") == 1, "review packet version must be 1")
    _require(
        packet.get("status") in {"pending_human_review", "accepted"},
        "review packet status is invalid",
    )
    truth_policy = packet.get("truth_policy") or {}
    _require(
        truth_policy.get("sut_output_may_define_truth") is False,
        "SUT output must not define OCR gold truth",
    )
    _require(
        truth_policy.get("reviewer_kind_required_for_acceptance") == "human",
        "accepted OCR gold requires a human reviewer",
    )
    _require(
        truth_policy.get("new_corpus_revision_required_for_promotion") is True,
        "human-reviewed gold promotion must create a new corpus revision",
    )
    _require(
        truth_policy.get("mutate_public_v1") is False,
        "public_v1 must remain immutable",
    )

    _validate_optional_pinned_file(
        packet,
        root=root,
        path_key="source_review_request",
        sha_key="source_review_request_sha256",
        label="source review request",
    )
    _validate_optional_pinned_file(
        packet,
        root=root,
        path_key="supporting_ai_audit",
        sha_key="supporting_ai_audit_sha256",
        label="supporting AI audit",
    )

    source_manifest = root / str(packet["source_corpus"])
    _require(source_manifest.is_file(), "source corpus manifest is missing")
    _require(
        _sha256(source_manifest) == packet.get("source_manifest_sha256"),
        "source corpus manifest hash does not match the review packet",
    )
    corpus = json.loads(source_manifest.read_text(encoding="utf-8"))
    artifacts = {item["id"]: item for item in corpus["artifacts"]}

    items = packet.get("items")
    _require(isinstance(items, list) and items, "review packet must contain items")
    seen: set[str] = set()
    accepted = 0

    for item in items:
        artifact_id = str(item.get("artifact_id") or "")
        _require(artifact_id and artifact_id not in seen, "artifact IDs must be unique")
        seen.add(artifact_id)
        artifact = artifacts.get(artifact_id)
        _require(artifact is not None, f"unknown corpus artifact: {artifact_id}")
        _require(bool(artifact.get("ocr_required")), f"{artifact_id} is not an OCR artifact")
        source_kind = (artifact.get("metadata") or {}).get("gold_kind")
        _require(
            source_kind == "native-extraction-silver",
            f"{artifact_id} is not a silver OCR reference",
        )
        _require(
            item.get("source_gold_kind") == source_kind,
            f"{artifact_id} source gold kind mismatch",
        )

        corpus_dir = source_manifest.parent
        expected_scan = corpus_dir / str(artifact["file"])
        expected_gold = corpus_dir / str(artifact["gold_text_file"])
        scan = root / str(item["scan_file"])
        gold = root / str(item["candidate_gold_file"])
        _require(scan.resolve() == expected_scan.resolve(), f"{artifact_id} scan path mismatch")
        _require(gold.resolve() == expected_gold.resolve(), f"{artifact_id} gold path mismatch")
        _require(scan.is_file(), f"{artifact_id} scan file is missing")
        _require(gold.is_file(), f"{artifact_id} candidate gold file is missing")

        scan_hash = _sha256(scan)
        gold_hash = _sha256(gold)
        _require(scan_hash == item.get("scan_sha256"), f"{artifact_id} scan hash mismatch")
        _require(gold_hash == item.get("candidate_gold_sha256"), f"{artifact_id} gold hash mismatch")
        _require(scan_hash == artifact.get("sha256"), f"{artifact_id} corpus scan hash mismatch")
        _require(gold_hash == artifact.get("gold_sha256"), f"{artifact_id} corpus gold hash mismatch")

        review: Mapping[str, Any] = item.get("review") or {}
        review_status = review.get("status")
        _require(review_status in {"pending", "accepted"}, f"{artifact_id} review status is invalid")
        if review_status == "accepted":
            _require(
                review.get("reviewer_kind") == "human",
                f"{artifact_id} acceptance requires reviewer_kind=human",
            )
            _require(bool(str(review.get("reviewer") or "").strip()), f"{artifact_id} reviewer is required")
            _require(bool(str(review.get("reviewed_at") or "").strip()), f"{artifact_id} reviewed_at is required")
            decision = review.get("decision")
            _require(
                decision in {"accepted_as_is", "accepted_with_corrections"},
                f"{artifact_id} accepted review decision is invalid",
            )
            accepted_gold_file = str(item.get("accepted_gold_file") or "").strip()
            accepted_gold_sha256 = str(item.get("accepted_gold_sha256") or "").strip()
            _require(accepted_gold_file, f"{artifact_id} accepted_gold_file is required")
            _require(
                len(accepted_gold_sha256) == 64
                and all(ch in "0123456789abcdef" for ch in accepted_gold_sha256),
                f"{artifact_id} accepted_gold_sha256 is invalid",
            )
            accepted_gold = (root / accepted_gold_file).resolve()
            _require(
                accepted_gold.is_relative_to(root.resolve()),
                f"{artifact_id} accepted gold path escapes benchmarks root",
            )
            _require(accepted_gold.is_file(), f"{artifact_id} accepted gold file is missing")
            accepted_hash = _sha256(accepted_gold)
            _require(
                accepted_hash == accepted_gold_sha256,
                f"{artifact_id} accepted gold hash mismatch",
            )
            if decision == "accepted_as_is":
                _require(
                    accepted_gold == gold.resolve() and accepted_hash == gold_hash,
                    f"{artifact_id} accepted_as_is must preserve the pinned candidate",
                )
            else:
                _require(
                    accepted_gold != gold.resolve(),
                    f"{artifact_id} corrected gold must be a separate file",
                )
                _require(
                    accepted_hash != gold_hash,
                    f"{artifact_id} corrected gold must differ from the silver candidate",
                )
                _require(
                    bool(str(review.get("notes") or "").strip()),
                    f"{artifact_id} corrected acceptance requires notes",
                )
            accepted += 1

    if packet["status"] == "accepted":
        _require(accepted == len(items), "accepted packet requires every item to be human-accepted")
    else:
        _require(accepted < len(items), "pending packet cannot have every item accepted")

    return {
        "review_id": packet["review_id"],
        "status": packet["status"],
        "items": len(items),
        "accepted_items": accepted,
        "pending_items": len(items) - accepted,
        "source_manifest_sha256": packet["source_manifest_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a hash-pinned OCR human-gold review packet."
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument("--benchmarks-root", type=Path)
    args = parser.parse_args(argv)
    result = validate_ocr_gold_review_packet(
        args.packet,
        benchmarks_root=args.benchmarks_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
