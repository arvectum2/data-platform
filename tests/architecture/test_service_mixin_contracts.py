"""Guard DataPlatformService composition and bounded service ownership."""

import ast
from pathlib import Path

from arvectum_data.api.service import DataPlatformService
from arvectum_data.api.service_mixins import (
    AccessServiceMixin,
    BillingServiceMixin,
    CollectionServiceMixin,
    ConnectorCredentialServiceMixin,
    ConnectorDiscoveryServiceMixin,
    ConsumerKeyServiceMixin,
    ExtractionServiceMixin,
    GraphServiceMixin,
    MemorySyncServiceMixin,
    ModelReadinessServiceMixin,
    RetrievalServiceMixin,
    UsageServiceMixin,
)

MIXIN_ROOT = Path(__file__).resolve().parents[2] / "src/arvectum_data/api/service_mixins"
EXPECTED_MIXINS = (
    AccessServiceMixin,
    ConsumerKeyServiceMixin,
    ConnectorCredentialServiceMixin,
    ConnectorDiscoveryServiceMixin,
    ModelReadinessServiceMixin,
    BillingServiceMixin,
    UsageServiceMixin,
    CollectionServiceMixin,
    MemorySyncServiceMixin,
    RetrievalServiceMixin,
    GraphServiceMixin,
    ExtractionServiceMixin,
)


def test_public_facade_composes_each_bounded_service_once():
    assert DataPlatformService.__bases__ == EXPECTED_MIXINS


def test_domain_operations_have_one_implementing_owner():
    operation_owners = {
        "create_consumer_key": ConsumerKeyServiceMixin,
        "authenticate_consumer_key": ConsumerKeyServiceMixin,
        "rotate_consumer_key": ConsumerKeyServiceMixin,
        "create_connector_credential": ConnectorCredentialServiceMixin,
        "resolve_connector_credential": ConnectorCredentialServiceMixin,
        "rotate_connector_credential": ConnectorCredentialServiceMixin,
        "discover": ConnectorDiscoveryServiceMixin,
        "ingest_discovered_resource": ConnectorDiscoveryServiceMixin,
        "model_status": ModelReadinessServiceMixin,
        "record_usage_event": UsageServiceMixin,
        "usage_summary": UsageServiceMixin,
    }
    for operation, owner in operation_owners.items():
        assert getattr(DataPlatformService, operation) is owner.__dict__[operation]
        assert sum(operation in cls.__dict__ for cls in EXPECTED_MIXINS) == 1


def test_bounded_mixins_do_not_directly_import_sibling_mixins():
    siblings = {path.stem for path in MIXIN_ROOT.glob("*.py")} - {"__init__"}
    for path in MIXIN_ROOT.glob("*.py"):
        if path.stem == "__init__":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                assert node.module not in siblings, (path.name, node.module)
