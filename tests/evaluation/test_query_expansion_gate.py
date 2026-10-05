from arvectum_data.evaluation import EvaluationSummary, QueryExpansionGate


def _summary(*, mrr: float, recall: float, top1: float, p95: float) -> EvaluationSummary:
    return EvaluationSummary(
        suite_name="frozen",
        cases=20,
        top1_accuracy=top1,
        mrr=mrr,
        hit_rate_at_3=recall,
        hit_rate_at_5=recall,
        mean_recall_at_5=recall,
        latency_p50_ms=p95 / 2,
        latency_p95_ms=p95,
        latency_max_ms=p95,
        case_results=(),
    )


def test_query_expansion_gate_accepts_recall_gain_without_top1_regression():
    result = QueryExpansionGate().evaluate(
        _summary(mrr=0.8, recall=0.8, top1=0.7, p95=100),
        _summary(mrr=0.8, recall=0.85, top1=0.7, p95=150),
    )
    assert result["passed"] is True


def test_query_expansion_gate_rejects_no_gain():
    result = QueryExpansionGate().evaluate(
        _summary(mrr=1.0, recall=1.0, top1=1.0, p95=100),
        _summary(mrr=1.0, recall=1.0, top1=1.0, p95=120),
    )
    assert result["passed"] is False
