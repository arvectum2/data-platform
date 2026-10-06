from arvectum_data.evaluation.pipeline_latency import build_pipeline_latency_report


def test_pipeline_latency_report_splits_native_ocr_retrieval_and_synthesis() -> None:
    report = build_pipeline_latency_report(
        corpus={
            "results": [
                {"format": "pdf", "latency_ms": 10, "skipped": False},
                {"format": "docx", "latency_ms": 20, "skipped": False},
                {"format": "scanned-pdf", "latency_ms": 100, "skipped": False},
                {"format": "scanned-pdf", "latency_ms": 200, "skipped": False},
            ]
        },
        retrieval={
            "case_results": [
                {"latency_ms": 30},
                {"latency_ms": 50},
            ]
        },
        faithfulness={
            "results": [
                {"latency_ms": 1000},
                {"latency_ms": 2000},
            ]
        },
    )

    stages = {item.stage: item for item in report.stages}
    assert stages["native_ingestion"].p50_ms == 15
    assert stages["ocr_ingestion"].p50_ms == 150
    assert stages["retrieval"].p50_ms == 40
    assert stages["synthesis"].p50_ms == 1500
    assert all(item.p95_ms <= item.max_ms for item in report.stages)

def test_pipeline_latency_accepts_frozen_retrieval_summary() -> None:
    report = build_pipeline_latency_report(
        corpus={
            "results": [
                {"format": "pdf", "latency_ms": 10, "skipped": False},
                {"format": "scanned-pdf", "latency_ms": 100, "skipped": False},
            ]
        },
        retrieval={
            "cases": 20,
            "latency_p50_ms": 100,
            "latency_p95_ms": 150,
            "latency_max_ms": 200,
        },
        faithfulness={
            "results": [{"latency_ms": 1000}],
        },
    )
    retrieval = next(item for item in report.stages if item.stage == "retrieval")
    assert retrieval.samples == 20
    assert retrieval.p50_ms == 100
    assert retrieval.p95_ms == 150
    assert retrieval.max_ms == 200

