from arvectum_data.api.config import Settings
from arvectum_data.evaluation.private_runtime import evaluate_private_runtime


def _local_settings(**overrides):
    values = {
        "host": "127.0.0.1",
        "database_url": "postgresql+psycopg://user:secret@127.0.0.1:5432/db",
        "embedding_provider": "llama_cpp",
        "embedding_base_url": "http://127.0.0.1:8090/v1",
        "ocr_provider": "tesseract",
        "reasoning_policy": "local-only",
        "reasoning_locality": "local",
        "reasoning_base_url": "http://127.0.0.1:8081/v1",
        "vision_policy": "disabled",
    }
    values.update(overrides)
    return Settings(**values)


def test_local_core_runtime_has_full_private_coverage() -> None:
    report = evaluate_private_runtime(_local_settings())

    assert report.fully_private is True
    assert report.coverage == 1.0
    assert {item.component for item in report.components} == {
        "api",
        "database",
        "embeddings",
        "ocr",
        "reasoning",
        "vision",
    }


def test_remote_reasoning_breaks_private_coverage() -> None:
    report = evaluate_private_runtime(
        _local_settings(
            reasoning_policy="remote-allowlist",
            reasoning_locality="remote",
            reasoning_base_url="https://example.test/v1",
        )
    )

    reasoning = next(item for item in report.components if item.component == "reasoning")
    assert reasoning.private is False
    assert report.fully_private is False
    assert report.coverage < 1.0


def test_remote_database_breaks_private_coverage() -> None:
    report = evaluate_private_runtime(
        _local_settings(
            database_url="postgresql+psycopg://user:secret@db.example.test:5432/db",
        )
    )

    database = next(item for item in report.components if item.component == "database")
    assert database.private is False
