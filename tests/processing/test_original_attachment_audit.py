"""Raw file SHA-256 and deterministic DP IDs are not the same as EIS authenticity."""

from __future__ import annotations

import copy

from arvectum_data.documents.ingest import ingest_file
from arvectum_data.processing.original_attachment_audit import audit_original_attachment


COLLECTION = "tender-source-test"
CANONICAL_URI = "https://zakupki.gov.ru/example/notice/012345"
SOURCE_TYPE = "file"


def _stored_resource(tmp_path):
    original = b"Original binary fixture: Russian procurement source v3."
    path = tmp_path / "source.txt"
    path.write_bytes(original)
    actual = ingest_file(
        path,
        collection_id=COLLECTION,
        canonical_uri=CANONICAL_URI,
        source_type=SOURCE_TYPE,
    )
    resource = {
        "resource_id": actual.resource.resource_id,
        "source_type": SOURCE_TYPE,
        "canonical_uri": CANONICAL_URI,
        "content_hash": actual.resource.content_hash,
        "metadata": {"notice_revision": "3"},
        "documents": [
            {
                "document_id": actual.document.document_id,
                "content_hash": actual.document.content_hash,
            }
        ],
    }
    return original, resource


def _check(original, resource, *, revision="3", uri=CANONICAL_URI, collection=COLLECTION):
    return audit_original_attachment(
        original,
        resource,
        expected_collection_id=collection,
        expected_source_type=SOURCE_TYPE,
        expected_canonical_uri=uri,
        expected_notice_revision=revision,
    )


def test_true_bytes_match_actual_ingestion_hashes_ids_and_metadata(tmp_path):
    original, resource = _stored_resource(tmp_path)
    audit = _check(original, resource)
    assert audit.binary_matches_store
    assert audit.notice_revision_metadata_matches
    assert audit.ready_for_authoritative_source_review
    assert audit.checked_documents == 1
    assert audit.error_codes == ()


def test_missing_independent_notice_revision_does_not_claim_full_provenance(tmp_path):
    original, resource = _stored_resource(tmp_path)
    audit = _check(original, resource, revision=None)
    assert audit.binary_matches_store
    assert not audit.notice_revision_metadata_matches
    assert not audit.ready_for_authoritative_source_review
    assert audit.error_codes == ("NOTICE_REVISION_NOT_INDEPENDENTLY_MATCHED",)


def test_forged_original_bytes_do_not_match_store(tmp_path):
    original, resource = _stored_resource(tmp_path)
    audit = _check(original + b" altered", resource)
    assert not audit.binary_matches_store
    assert "RESOURCE_BINARY_HASH_MISMATCH" in audit.error_codes
    assert "ORIGINAL_DOCUMENT_HASH_OR_ID_MISMATCH" in audit.error_codes


def test_resource_id_or_expected_collection_mismatch_fails(tmp_path):
    original, resource = _stored_resource(tmp_path)
    bad = copy.deepcopy(resource)
    bad["resource_id"] = "forged"
    assert "RESOURCE_ID_MISMATCH" in _check(original, bad).error_codes
    assert "RESOURCE_ID_MISMATCH" in _check(
        original, resource, collection="other-collection"
    ).error_codes


def test_authoritatively_supplied_uri_cannot_be_replaced_by_exported_uri(tmp_path):
    original, resource = _stored_resource(tmp_path)
    audit = _check(original, resource, uri="https://zakupki.gov.ru/different/notice")
    assert not audit.binary_matches_store
    assert "CANONICAL_URI_MISMATCH" in audit.error_codes
    assert "RESOURCE_ID_MISMATCH" in audit.error_codes


def test_document_hash_or_id_mismatch_fails_closed(tmp_path):
    original, resource = _stored_resource(tmp_path)
    bad = copy.deepcopy(resource)
    bad["documents"][0]["document_id"] = "altered"
    assert "ORIGINAL_DOCUMENT_HASH_OR_ID_MISMATCH" in _check(original, bad).error_codes
    bad = copy.deepcopy(resource)
    bad["documents"][0]["content_hash"] = "0" * 64
    assert "ORIGINAL_DOCUMENT_HASH_OR_ID_MISMATCH" in _check(original, bad).error_codes


def test_notice_revision_metadata_is_separate_from_file_binary_integrity(tmp_path):
    original, resource = _stored_resource(tmp_path)
    audit = _check(original, resource, revision="4")
    assert audit.binary_matches_store
    assert not audit.notice_revision_metadata_matches
    assert not audit.ready_for_authoritative_source_review


def test_ambiguous_or_missing_document_fails(tmp_path):
    original, resource = _stored_resource(tmp_path)
    resource["documents"] = []
    audit = _check(original, resource)
    assert not audit.binary_matches_store
    assert "NO_DOCUMENTS" in audit.error_codes


def test_missing_original_bytes_or_authoritative_identifier_fails(tmp_path):
    original, resource = _stored_resource(tmp_path)
    assert not _check(b"", resource).binary_matches_store
    assert not _check(original, resource, collection="").binary_matches_store


def test_error_codes_never_contain_original_binary_or_source_identifier(tmp_path):
    original, resource = _stored_resource(tmp_path)
    audit = _check(original + b" altered", resource, revision="4")
    diagnostic = repr(audit.error_codes)
    assert "Russian procurement" not in diagnostic
    assert "zakupki.gov.ru" not in diagnostic
    assert resource["resource_id"] not in diagnostic
