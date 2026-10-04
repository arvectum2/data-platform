# Retrieval evaluation

Data Platform ships a consumer-neutral relevance benchmark runner.

The benchmark is JSON and contains one or more search cases. Each case defines:

- query text;
- collection scope;
- expected result identities;
- identity field (`canonical_uri`, `chunk_id`, `document_id`, or `resource_id`);
- search mode and optional RRF weights;
- result limit.

Example:

~~~json
{
  "name": "sample",
  "defaults": {
    "collections": ["growth:site:revision"],
    "id_field": "canonical_uri",
    "limit": 5
  },
  "cases": [
    {
      "id": "procurement-agent",
      "query": "агент для тендерного отдела",
      "expected_ids": [
        "https://arvectum.com/solutions/tender-department-ai-agent.html"
      ]
    }
  ]
}
~~~

Run against a service:

~~~bash
arvectum-data-eval benchmarks/production_acceptance_v1.json \
  --base-url http://127.0.0.1:8094
~~~

Write runtime evidence and enforce minimum quality:

~~~bash
arvectum-data-eval benchmarks/production_acceptance_v1.json \
  --output /path/outside/git/result.json \
  --fail-top1-below 0.85 \
  --fail-mrr-below 0.90
~~~

The runner reports:

- top-1 accuracy;
- mean reciprocal rank;
- hit rate at 3 and 5;
- mean recall at 5;
- latency p50, p95 and max;
- per-case ranks, latency and returned identifiers.

Benchmarks are snapshots, not timeless truth. Versioned collection IDs deliberately freeze the indexed corpus used for an acceptance baseline. When a consumer intentionally changes its corpus, create or review a new benchmark revision rather than silently editing old expected identities.

The first production snapshot is `benchmarks/production_acceptance_v1.json`. It combines accepted Tender Agent and Growth/SEO cases. The first run on 2026-10-04 produced 9/9 top-1 accuracy, MRR 1.0, hit-rate@5 1.0 and mean recall@5 1.0; p50 latency was about 103 ms and p95 about 214 ms.

This harness evaluates retrieval quality. It does not yet collect user relevance feedback; that feedback capture loop remains a separate backlog item.
