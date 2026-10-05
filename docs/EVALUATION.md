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

This harness evaluates retrieval quality against frozen accepted cases. Online relevance judgments are captured separately through the Data Platform feedback API.

## Relevance feedback capture

Consumers can record a judgment for a concrete search hit:

~~~http
POST /v1/feedback/relevance
~~~

Payload fields are collection/resource/document/chunk identity, the originating query, one of `relevant`, `partially_relevant`, or `not_relevant`, optional rank, optional actor, and bounded structured context.

The durable feedback table does **not** store raw query text. The service hashes the normalized request query with SHA-256 and stores only `query_hash` together with the hit identity and label. This preserves a stable join key for repeated judgments without turning the Data Platform database into a query-log archive.

Consumers can inspect recent judgments or aggregate counts with:

~~~http
GET /v1/feedback/relevance?collection_id=<collection>
GET /v1/feedback/relevance/summary?collection_id=<collection>
~~~

The service validates the full collection -> resource -> document -> chunk relationship before accepting a judgment, so feedback cannot be attached to a hit outside the declared collection. These judgments are input evidence for future relevance tuning; they do not automatically retrain, rerank, or mutate search behavior.

## Exact-match lexical benchmark

`benchmarks/lexical_exact_v1.json` freezes five exact-name/token intents across the Growth site, product metadata and external research collections.

Production comparison on 2026-10-04:

| Mode | Top-1 | MRR | Hit@5 | p50 |
| --- | ---: | ---: | ---: | ---: |
| Hybrid | 1.00 | 1.00 | 1.00 | ~103 ms |
| Vector only | 0.60 | 0.80 | 1.00 | ~95 ms |
| Lexical only | 0.80 | 0.90 | 1.00 | ~12 ms |

Vector-only ranked the exact `500 КБ` landing page and exact `Image Size` App Store page second. Lexical retrieval supplied enough exact-token signal for hybrid search to promote both expected results to rank 1.

This benchmark does **not** justify a BM25 migration today. PostgreSQL FTS already provides a useful complementary exact-match signal and the current hybrid strategy outperforms both single retrievers on the accepted exact-match suite. Reconsider BM25 only when a broader benchmark demonstrates a repeatable lexical relevance gap that cannot be solved by query formulation or fusion.

## Authorized federation benchmark

The HTTP evaluation runner can authenticate consumer-scoped federation without putting consumer secrets into benchmark JSON.

Set the consumer key in an environment variable and pass the consumer identity separately:

    export ARVECTUM_DATA_EVAL_CONSUMER_KEY=<consumer-scoped-secret>
    arvectum-data-eval benchmarks/production_acceptance_v2.json       --base-url http://127.0.0.1:8094       --consumer growth-agent       --consumer-key-env ARVECTUM_DATA_EVAL_CONSUMER_KEY

The runner requires consumer and consumer key together and fails closed on partial configuration.

production_acceptance_v2 extends the first production snapshot with an authorized cross-collection Growth case over the active site and product collections. Its first production run on 2026-10-04 passed all 10 cases with top-1 accuracy 1.0, MRR 1.0, hit-rate@5 1.0 and mean recall@5 1.0; p50 latency was about 126 ms and p95 about 154 ms.

The first v2 run exposed a federation presentation issue: the same canonical product URL appeared from both the site and product collections. Federation now collapses cross-collection duplicates by canonical URI while preserving same-collection chunks. Re-running v2 after the fix kept top-1 accuracy and MRR at 1.0 and returned five unique canonical URIs for the federated Photo Size case.



## Production acceptance v3

`benchmarks/production_acceptance_v3.json` expands the accepted production suite
from 10 to 20 real consumer cases without weakening the acceptance target. It
retains all v2 cases and adds:

- six Google Search Console / Yandex Webmaster intents whose consumer-defined
  landing pages are stable top-1 results on the current Growth corpus;
- four document-routing intents from live procurement
  `0137200001226007700`, covering the object description, application
  requirements, NMCK justification and contract terms.

The procurement cases use `collapse_by_canonical_uri=true` because the
acceptance unit is the canonical source document, while each source can contain
many independently retrieved chunks. This avoids treating multiple chunks from
the same document as distinct document-level answers.

The first production run on 2026-10-05 passed all 20 cases:

| Metric | v3 |
| --- | ---: |
| Top-1 accuracy | 1.00 |
| MRR | 1.00 |
| Hit@3 | 1.00 |
| Hit@5 | 1.00 |
| Mean recall@5 | 1.00 |
| p50 latency | ~95.8 ms |
| p95 latency | ~127.4 ms |
| max latency | ~184.0 ms |

The remaining Search Console/Webmaster intents that are not stable top-1 results
remain in `growth_search_console_v1.json` as diagnostic evidence. They are not
silently promoted into the accepted suite by changing expected URLs. This keeps
the frozen acceptance benchmark separate from known retrieval/formulation gaps.

The larger accepted suite still does not justify enabling BM25, learned
reranking, LLM reranking or platform-generated query expansion by default.
Those features remain benchmark-gated: a candidate must show a repeatable gain
on accepted and diagnostic suites without weakening provenance, isolation or
deterministic fallback behavior.

## Search Console intent benchmark

`benchmarks/growth_search_console_v1.json` freezes twelve real Google Search Console / Yandex Webmaster intent formulations observed during the 2026-10-04 SEO review against the active Arvectum site collection.

The first production run, before query variants, produced:

| Metric | Baseline |
| --- | ---: |
| Top-1 accuracy | 0.50 |
| MRR | 0.583 |
| Hit@3 | 0.75 |
| Hit@5 | 0.75 |
| Mean recall@5 | 0.75 |
| p50 latency | ~119 ms |
| p95 latency | ~169 ms |

Changing global lexical/vector fusion weights to 1:2 or 1:4 did not improve top-1 accuracy. This is evidence that the remaining failures are query-formulation/domain-language gaps rather than a single global fusion-weight problem.

The benchmark therefore justifies bounded consumer-controlled query variants. Data Platform accepts up to eight deterministic variants per search request. The original query always keeps full weight; variants use a separate `query_variant_weight` in the 0..1 range. Data Platform does not invent domain synonyms internally.
