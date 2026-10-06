# Competitive benchmark foundation

DP-BENCH-002 is benchmark-driven: retrieval, OCR, reranking, VLM escalation,
query expansion and answer synthesis are not promoted merely because an
implementation exists.

## Frozen catalog

The file benchmarks/catalog_v1.json is the versioned registry of executable
benchmark suites. Each entry records:

- a stable suite ID and relative file path;
- SHA-256 of the frozen JSON suite;
- expected case count;
- visibility: public or private-derived;
- covered benchmark dimensions;
- minimum acceptance thresholds.

The catalog validator fails closed when a suite is changed without updating its
digest or declared case count. This makes benchmark revisions explicit in code
review instead of silently moving the target.

Raw production documents are not committed by this catalog. Production-derived
suites contain accepted queries and evidence identities only and are labelled
private-derived. Public/shareable suites remain distinguishable at the catalog
layer.

## Metric primitives

The evaluation package now provides reusable metric primitives for later
competitive runners:

- character error rate (CER) and word error rate (WER) for OCR;
- nDCG@k for graded retrieval relevance;
- set precision/recall for citation completeness/correctness and similar
  evidence-set checks.

The existing retrieval evaluator continues to report top-1, MRR, hit rate,
recall and latency. The next DP-BENCH-002 increments should add frozen
multi-format source fixtures, OCR/layout gold data, adversarial isolation and
conflict cases, and reference-product adapters. Those dimensions remain open
until measured rather than being checked off from implementation alone.

## Real multi-format corpus slice

benchmarks/corpora/public_v1/manifest.json adds the first executable source
corpus. It contains compact real public procurement and Arvectum website
artifacts in native PDF, DOCX, XLSX and HTML formats, plus two image-only PDFs
derived from real procurement pages for OCR evaluation: a linear-text baseline
and a table/form layout-stress case.

Every fixture and OCR reference text is SHA-256 pinned. The corpus runner checks
extraction status, minimum text volume and required evidence strings, reports
success by format and extraction latency, and can optionally run local
Tesseract OCR. OCR output is scored with normalized CER/WER against the pinned
reference text.

The scan reference is explicitly labelled silver rather than human-verified
gold: it comes from native extraction of the source PDF before rasterization.
A later corpus revision should add human-reviewed scan gold, malformed/legacy
documents, mixed Russian/English cases and product-research source material.

The first local Tesseract baseline on the Mac mini (rus+eng, 220 DPI) separates
two OCR profiles. The linear technical-specification scan measured CER 3.61%,
WER 5.86% and mean confidence 94.41%. The table/form layout-stress scan
measured CER 35.78%, WER 74.47% and mean confidence 86.89%. Per-artifact
regression gates are intentionally different: the linear baseline is capped at
CER 5% / WER 10%, while the layout-stress case is capped at CER 40% / WER 80%.
These are regression ceilings, not final product-quality targets.

## Table and form structure

The corpus runner now scores structural checks separately from plain-text
presence. Native DOCX/XLSX fixtures use ordered row/cell expectations, while
form-like PDFs use ordered label/value expectations. A per-artifact
min_structure_score can act as a regression gate.

The first native structure baseline requires 100% preservation for selected
rows in the procurement DOCX/XLSX and selected key/value fields in the
procurement control form. The OCR layout-stress scan reports the same form
field score as an observation, while CER/WER continues to expose reading-order
damage that simple field presence alone cannot reveal. This keeps OCR text
accuracy and layout preservation as distinct benchmark signals.

## Adversarial invariants

benchmarks/adversarial_v1.json defines five synthetic invariants that execute
against the real PostgreSQL Data Platform path rather than a mock search
implementation:

- collection isolation: a matching document in an unrequested collection must
  never leak into results;
- tenant isolation: protected collections fail closed for an unauthorized
  consumer and remain available to an authorized consumer;
- duplicate content: one canonical URI present in multiple collections produces
  one federated winner;
- conflicting evidence: contradictory values from distinct source URIs are
  both retained with provenance so downstream contradiction checks can inspect
  them;
- stale source: repeated refresh failures transition a URL resource through
  refresh_error to stale while preserving its prior content hash and searchable
  last-known evidence.

The runner uses hashing embeddings only for deterministic local test setup; the
adversarial queries themselves use PostgreSQL lexical retrieval. This isolates
the security/data-lifecycle invariants from embedding-model variance.

First isolated PostgreSQL acceptance on the Mac mini (2026-10-06) passed 5/5. The isolation case returned one requested-collection hit and zero forbidden hits; the tenant case denied the unauthorized consumer and returned one hit for the authorized consumer; federated duplicate content collapsed to one canonical URI; both conflicting source URIs and their evidence survived retrieval; and the stale case transitioned refresh_error -> stale while preserving the original content hash and searchable last-known evidence. The temporary benchmark database was dropped after the run.

nDCG treats repeated result identities as one document/evidence item. This is
important when page-level evaluation uses canonical_uri while search returns
multiple chunks from the same page: duplicate chunks must not create relevance
gain or allow nDCG to exceed 1.0.

Live production retrieval baseline after duplicate-identity correction
(2026-10-06): production_acceptance_v3 passed top-1 1.0, MRR 1.0, recall@5
1.0 and mean nDCG@5 0.9953 against a fixed 0.99 nDCG gate. The remaining
ranking gap is explicit rather than hidden: growth-photo-pixels has all accepted
evidence in top-5 but an unrelated result is interleaved before two relevant
URLs.

## Exact fact preservation

benchmarks/fact_preservation_v1.json binds exact facts to real frozen public
PDF/DOCX/XLSX artifacts. Cases currently cover an OKUD identifier, dates, an
OKPD2 code and monetary values.

The benchmark has two independent gates. First, default deterministic chunking
must retain the exact fact and its local context in at least one chunk. Second,
the exact fact is issued as a PostgreSQL lexical query against a collection
containing all benchmark source documents; the expected source must rank first.

This catches two different failure classes: a parser/chunker can damage a fact
before indexing, or retrieval can fail even though the fact survived in the
indexed text.

First isolated PostgreSQL acceptance on the Mac mini (2026-10-06) passed all six cases. Chunk preservation = 1.0, same-chunk context preservation = 1.0 and exact PostgreSQL lexical top-1 retrieval = 1.0. The accepted cases cover PDF/DOCX/XLSX facts across identifiers, dates, classification numbers and monetary values. The temporary benchmark database was dropped after the run.

## Russian retrieval slice

benchmarks/russian_retrieval_v1.json freezes the 19 accepted
production_acceptance_v3 cases whose queries contain Cyrillic text. The only
excluded production case is the English App Store research query. Keeping this
as a separate suite makes Russian retrieval quality independently gateable
instead of inferring it from a mixed-language aggregate.

Acceptance gates are top-1 1.0, MRR 1.0, recall@5 1.0 and mean nDCG@5 at least
0.99.

Live production acceptance on 2026-10-06 passed all 19 cases: top-1=1.0, MRR=1.0, recall@5=1.0 and mean nDCG@5=0.9951. Observed latency was about 114 ms p50, 142 ms p95 and 200 ms max.

## Answer faithfulness suite

benchmarks/faithfulness_v1.json separates answer-synthesis safety dimensions
from retrieval relevance. The first frozen local-model cases cover a supported
exact price fact, insufficient evidence that should trigger abstention,
contradictory deadlines that must be surfaced, and a multi-source contract to
supplier inference that requires complete citations across both evidence
chunks.

The evaluator reports citation precision, citation recall, exact frozen-fact
support in cited evidence, abstention accuracy, contradiction-term recall and
synthesis latency. All safety-quality thresholds start at 1.0; a local model
must pass rather than lowering the gate to its observed behavior.

First local Gemma 4 12B acceptance on 2026-10-06 passed all four cases at the original 1.0 safety thresholds: pass rate 1.0, citation precision 1.0, citation recall 1.0, exact claim-support rate 1.0, abstention accuracy 1.0, contradiction recall 1.0 and required-answer-term recall 1.0. Mean synthesis latency was about 7.4 s and max about 9.8 s. The suite is deliberately small and synthetic; real-source faithfulness expansion remains benchmark backlog.

## Incremental sync efficiency

benchmarks/sync_efficiency_v1.json measures durable URL refresh behavior on an
isolated PostgreSQL database with three resources. It runs sequential
no-change, single-change and all-change scenarios and tracks changed resources,
actual indexing calls, embedding writes and unnecessary indexing.

The hard gate is indexing amplification <= 1.0 with zero indexing of unchanged
resources. An unchanged refresh may fetch/extract to detect change, but it must
not create new index/embedding work.

First isolated PostgreSQL acceptance on 2026-10-06 passed all three scenarios. No-change produced 0 index calls and 0 embedding writes; the single-change scenario produced exactly 1 index call and 1 embedding write; all-change produced exactly 3 and 3. Across the suite, 4 resources changed and exactly 4 were indexed, with zero unnecessary indexing and amplification 1.0.

## Reranking comparison

arvectum-data-rerank-eval now executes the same frozen retrieval suite twice:
base hybrid and bounded reranking. Execution failures and timeouts are reported
as a structured failed gate rather than aborting with an unclassified
traceback.

On growth_search_console_v1, base hybrid measured top-1 0.50, MRR 0.5833,
mean nDCG@5 0.6468 and about 251 ms p95. Local Gemma reranking with only five
candidates exceeded a 5-second request timeout, while the accepted 3x latency
ceiling was about 752 ms. The current LLM reranker therefore fails competitive
acceptance and remains opt-in. The recorded result is
benchmarks/results/rerank_growth_search_console_2026-10-06.json.

## Multi-hop evidence retrieval

benchmarks/multi_hop_v1.json exercises the existing provenance-aware entity
graph on an isolated PostgreSQL database. The benchmark separates retrieval
from synthesis: the platform must traverse two- and three-hop paths and every
required edge must retain its collection/resource/document/chunk evidence.

The first acceptance run on 2026-10-06 passed 3/3 scenarios: contract ->
supplier -> INN at depth 2, supplier -> product -> manufacturer at depth 2,
and supplier -> product -> manufacturer -> country at depth 3. Target recall
was 1.0 and provenance completeness was 1.0. The faithfulness suite separately
checks that the reasoning model can synthesize across multiple supplied
sources; this benchmark proves that evidence can actually be retrieved through
multiple graph hops first.

## Pipeline stage latency

arvectum-data-latency-report aggregates raw benchmark latency into comparable
p50/p95/max stages. The 2026-10-06 Mac mini snapshot combines the real public
corpus, production_acceptance_v3 and faithfulness_v1:

- native ingestion/extraction (5 samples): p50 48.7 ms, p95 83.2 ms, max 89.6 ms;
- local OCR ingestion (2 scans): p50 2.13 s, p95 2.70 s, max 2.76 s;
- production retrieval (20 cases): p50 107.4 ms, p95 128.5 ms, max 133.3 ms;
- local Gemma answer synthesis (4 cases): p50 10.62 s, p95 15.13 s, max 15.80 s.

The result is frozen in benchmarks/results/pipeline_latency_2026-10-06.json.
This makes the optimization target explicit: deterministic retrieval is already
sub-second, while OCR and especially local generative synthesis dominate latency.

## Fully local/private core coverage

arvectum-data-private-eval audits the configured core execution path without
printing credentials or endpoint secrets. The scope is ingestion/OCR, local
indexing/database access, retrieval and optional reasoning/vision roles.
External web discovery/acquisition is deliberately excluded because fetching a
public URL is inherently networked and should not be mislabeled as offline.

The 2026-10-06 production Mac mini audit passed 6/6 components (coverage 1.0):
API binds to loopback, PostgreSQL is reached through loopback, the embedding
server is loopback-local, OCR uses local Tesseract, reasoning is local-only on
a loopback endpoint, and vision is disabled. The sanitized result is frozen in
benchmarks/results/private_runtime_2026-10-06.json.

## Runtime footprint and throughput

arvectum-data-resource-eval measures macOS physical footprint for the API,
embedding server and reasoning server, then runs the frozen production-v3
retrieval suite directly through DataPlatformService at configurable worker
counts. Search quality is checked at the same time so throughput cannot be
improved by returning empty or incorrectly ranked results.

The 2026-10-06 Mac mini snapshot (24 GiB unified memory) measured about 11.94 GB
of current combined physical footprint: Data Platform API 83.5 MB, Qwen3
Embedding server 1.81 GB, and local Gemma reasoning server 10.05 GB. The sum of
per-process historical peaks is about 22.58 GB; that is not a simultaneous peak
measurement and must not be interpreted as one. Apple Silicon has unified
memory, so there is no honest separate VRAM byte count; the report leaves the
dedicated GPU-memory byte field empty instead of inventing one.

Production-v3 retrieval retained top-1 accuracy 1.0 at every measured worker
count. Sequential throughput was 9.23 queries/s, 4 workers reached 12.99
queries/s, and 8 workers reached 13.37 queries/s, showing that scaling is
already close to saturation after four concurrent queries with the current
single-parallel embedding server. A post-throughput powermetrics sample showed
CPU power about 6.51 W, GPU power about 0.66 W and GPU active residency about
85.6%. The sanitized snapshot is frozen in
benchmarks/results/runtime_resources_2026-10-06.json.

## Query-expansion comparison

A base-vs-expansion runner now evaluates identical frozen suites and fails
closed on execution errors. On growth_search_console_v1, automatic local-model
expansion (maximum three variants) changed no quality metric: top-1 remained
0.50, MRR 0.5833, recall@5 0.75 and mean nDCG@5 0.6468. p95 latency increased
from about 263 ms to 2.74 s (10.42x), so the existing <=2x activation gate
fails. No default promotion is claimed.

## Private-derived real corpus

benchmarks/corpora/private_v1 extends the frozen source corpus without mixing
private-derived material into the public/shareable slice. It adds:

- a real legacy BIFF/OLE2 procurement XLS workbook;
- Arvectum-owned competitive product-research material with mixed Russian and
  English terminology;
- an Arvectum business market-validation document, predominantly English with
  Russian organization/context terms;
- a deliberately truncated derivative of a real DOCX, whose accepted behavior
  is fail-safe empty extraction rather than partial garbage.

Legacy XLS extraction is cross-platform through xlrd and preserves sheet,
row/cell order and date/number values deterministically. The first private-v1
acceptance passes 4/4 artifacts, including 100% selected row-structure
preservation on the legacy workbook and expected empty handling for malformed
OOXML.

## OCR-to-VLM routing

vlm_routing_v1 freezes the two real local-Tesseract scan profiles already in
public_v1. The layout-stress form (confidence 86.89%, CER 35.78%, WER 74.47%)
must escalate when vision is available; the linear scan (confidence 94.41%,
CER 3.61%, WER 5.86%) must not. The routing gate is fixed at 1.0.

## Private OCR scale

private_runtime_ocr_scale_v1 extends OCR validation beyond the two shareable
public scan profiles using nine real production-derived PDFs identified only by
SHA-256. It stores no source path or document/OCR text. The accepted run
measured median CER 9.81%, median WER 11.03% and p95 2.46 s. Three poor OCR
cases were all selected by the existing confidence<90 VLM routing rule, with
routing precision and recall both 1.0.

## External retrieval reference — Qdrant

A first external reference run is now reproducible with scripts/benchmark_qdrant_reference.py. The runner exports the already-indexed production chunk vectors for one frozen collection into a temporary Qdrant collection and reuses the same embedding model and benchmark queries, so no document parsing or embedding-model differences are mixed into the comparison.

On growth_search_console_v1 with 159 points and Qwen3-Embedding-4B/2560, Qdrant 1.19.2 and Data Platform vector-only produced identical quality: top-1 0.4167, MRR 0.625, Recall@5 0.8333 and nDCG@5 0.6796. Qdrant search-only p95 was about 5.4 ms. Including the shared query-embedding call, its end-to-end p95 was about 95.9 ms versus 126.6 ms through the Data Platform vector-only API.

This does not justify replacing pgvector. The existing direct exact-pgvector benchmark measures about 3.3 ms p95 at 100% sampled recall on a larger 697-vector workload, so the observed end-to-end gap is primarily orchestration/API overhead rather than vector-engine weakness. Decision: keep exact pgvector and optimize the request path only if vector-only end-to-end latency becomes material.
