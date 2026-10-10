from types import SimpleNamespace
import pytest
from arvectum_data.api.access_payloads import _consumer_key_payload, _connector_credential_payload, _normalize_credential_metadata
from arvectum_data.api.service_mixins.access import AccessServiceMixin

def test_facade():
    assert AccessServiceMixin._consumer_key_payload is _consumer_key_payload
    assert AccessServiceMixin._connector_credential_payload is _connector_credential_payload
    assert AccessServiceMixin._normalize_credential_metadata is _normalize_credential_metadata

def test_key_projection():
    row = SimpleNamespace(key_id=1, consumer_id=2, tenant_id=3, key_prefix=4, label=5, status=6, created_at=7, expires_at=8, revoked_at=9, key_hash=10)
    result = _consumer_key_payload(row)
    assert result == {"key_id":1,"consumer_id":2,"tenant_id":3,"key_prefix":4,"label":5,"status":6,"created_at":7,"expires_at":8,"revoked_at":9}

def test_connector_projection():
    row = SimpleNamespace(credential_id=1,tenant_id=2,consumer_id=3,connector_name=4,label=5,status=6,metadata_json={"регион":"Москва"},created_at=7,revoked_at=8)
    assert _connector_credential_payload(row)["metadata"] == {"регион":"Москва"}

def test_metadata_limits():
    assert _normalize_credential_metadata({"регион":"Москва"}) == {"регион":"Москва"}
    with pytest.raises(ValueError):
        _normalize_credential_metadata({str(i):i for i in range(33)})
    with pytest.raises(ValueError):
        _normalize_credential_metadata({"api_token":"value"})
    with pytest.raises(ValueError):
        _normalize_credential_metadata({"tags":[1,2]})
