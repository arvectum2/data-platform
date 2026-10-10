"""Stable codec contract for untrusted and Cyrillic record identities."""

import pytest

from arvectum_data.results import record_sets
from arvectum_data.results.record_identities import (
    parse_record_storage_item_id, record_set_storage_item_id, record_storage_item_id,
)
from arvectum_data.results.models import ResultIntegrityError


def test_public_facade_is_identical_to_extracted_codec():
    assert record_sets.parse_record_storage_item_id is parse_record_storage_item_id
    assert record_sets.record_storage_item_id is record_storage_item_id
    assert record_sets.record_set_storage_item_id is record_set_storage_item_id


def test_round_trip_unicode_and_reserved_characters():
    item = "закупка/44-ФЗ:сервис"
    record = "лот:№1/документ"
    identity = record_storage_item_id(item, record)
    assert identity.startswith("__dp_record_v1__:")
    assert parse_record_storage_item_id(identity) == (item, record)
    assert record_set_storage_item_id(item).startswith("__dp_record_set_v1__:")


@pytest.mark.parametrize("value", ["", "__dp_record_v1__:", "__dp_record_v1__:bad"])
def test_malformed_id_rejected(value):
    if value == "":
        assert parse_record_storage_item_id(value) is None
    else:
        with pytest.raises(ResultIntegrityError):
            parse_record_storage_item_id(value)


def test_empty_identifiers_never_persist():
    with pytest.raises(ValueError):
        record_storage_item_id("", "record")
    with pytest.raises(ValueError):
        record_set_storage_item_id("  ")
