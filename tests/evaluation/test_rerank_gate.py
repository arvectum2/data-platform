from arvectum_data.evaluation import EvaluationSummary, RerankGate


def _summary(*, mrr: float, top1: float, p95: float) -> EvaluationSummary:
    return EvaluationSummary(
        suite_name="frozen",
        cases=20,
        top1_accuracy=top1,
        mrr=mrr,
        hit_rate_at_3=1.0,
        hit_rate_at_5=1.0,
        mean_recall_at_5=1.0,
        latency_p50_ms=p95 / 2,
        latency_p95_ms=p95,
        latency_max_ms=p95,
        case_results=(),
    )


def test_rerank_gate_requires_quality_gain_with_bounded_latency():
    result = RerankGate().evaluate(
        _summary(mrr=0.80, top1=0.70, p95=100),
        _summary(mrr=0.83, top1=0.72, p95=250),
    )

    assert result["passed"] is True
    assert result["mrr_gain"] == 0.03


def test_rerank_gate_rejects_no_quality_gain():
    result = RerankGate().evaluate(
        _summary(mrr=1.0, top1=1.0, p95=100),
        _summary(mrr=1.0, top1=1.0, p95=150),
    )

    assert result["passed"] is False
