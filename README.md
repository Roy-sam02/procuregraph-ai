# ProcureGraph AI

A synthetic procurement intelligence project built as an engineering learning and interview demonstration.

## Status

See `docs/STATUS.md` for implemented slices and their verification state.

## Verified synthetic price evidence

The local demo's `POST /api/v1/pricing/cases/assess` accepts `tenant_id`,
`invoice_line_id`, and optional `include_verified_evidence` (default `false`).
When requested, the API looks up the source for the assessed contract price term
within the requested tenant, retrieves the exact version from MinIO, verifies its
bytes, page, and clauses, and then includes `evidence_reference` with the document
ID, document version, SHA-256, page, and three clause numbers. If verification
fails, it returns an error without a source reference. A normal assessment has
no source reference.

This endpoint is enabled only with `PROCUREGRAPH_ENABLE_DEMO_DB_API=1`. For a
verified request, PostgreSQL and MinIO must both be running, with the existing
`PROCUREGRAPH_DB_PORT`, `PROCUREGRAPH_DB_PASSWORD`,
`PROCUREGRAPH_MINIO_USER`, `PROCUREGRAPH_MINIO_PASSWORD`, and
`PROCUREGRAPH_MINIO_ENDPOINT=http://127.0.0.1:<mapped-port>` set in the API
process. The tenant UUID in the request is only a lookup filter, not proof of
authorization.

For the local synthetic demo, the evidence reference includes a `download_path`.
`GET` on that path requires `Authorization: Bearer <token>`, where the API
process reads `PROCUREGRAPH_DEMO_EVIDENCE_TOKEN` (at least 32 characters)
from its environment. Keep the token out of Git and URLs. Each download checks
the tenant-scoped case, retrieves the registered MinIO object version, and
verifies the PDF again before returning its bytes. A failed check returns no
PDF. Responses use `Cache-Control: no-store`. This shared demo token does not
identify individual users or implement the planned sessions, roles, and
tenant authorization; do not expose the demo API publicly.

On the Windows machine with the retained demo volumes, run
`powershell -ExecutionPolicy Bypass -File scripts/check_verified_api.ps1` to
exercise the real API route and token-gated PDF download with both containers
briefly running. The script generates a temporary token in its Python process,
then stops the containers and retains their volumes. To use the download route
from a separately started API, configure a token in that API process.

## Clause passages for retrieval

The same local check now exports the tenant-scoped PostgreSQL source locator,
reads the exact MinIO PDF version, and writes
`.local-fixtures/contract_passages_v1.json`. It contains one deterministic
passage for each of clauses 2.1, 2.2, and 2.3, with tenant, document/version,
page, clause, SHA-256 values, and offsets into normalized page text. A repeat
run checks that the manifest is identical and does not rewrite it. This is an
offline fixture used by the next retrieval step.

Alembic revision `0006_document_chunks` creates append-only source-linked
passages and a PostgreSQL full-text index. The local check re-verifies the
MinIO PDF, compares the regenerated passages with the manifest, registers the
three rows in one database transaction, repeats registration to check
idempotence, and searches within the demo tenant. Search is bounded to 1–10
results and uses the latest document version for a contract. This is a
PostgreSQL lexical baseline; Qdrant, retrieval benchmarks, and a public
search API remain future work.

## Local Qdrant wiring exercise

Run `powershell -ExecutionPolicy Bypass -File scripts/check_qdrant_hash_demo.ps1`
after the passage storage check. It first exports the three checked PostgreSQL
chunks and three labeled query rankings, stops PostgreSQL, then starts a
loopback-only Qdrant container with a retained named volume. The script
indexes the same stable source IDs, checks a repeat run, queries with a tenant
filter, writes a small local comparison report, and stops Qdrant.

This uses `token-hash-128-v1`, a deterministic lexical hashing vectorizer with
no model download or GPU. It is **not semantic embeddings**. Three hand-labeled
synthetic queries test wiring and provenance only; they do not measure ANN
recall, speed, or real retrieval quality. PostgreSQL remains the authoritative
source for document versions and passage text. Qdrant is not exposed through
the application API yet.

## Local semantic retrieval diagnostic

Install the optional pinned dependency with
`\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-retrieval.txt`.
Then run `powershell -ExecutionPolicy Bypass -File scripts/check_semantic_benchmark.ps1`.
The first use downloads the small `BAAI/bge-small-en-v1.5` ONNX model into
`.local-fixtures/fastembed_cache`; no GPU or API key is needed. PostgreSQL
ranks a locked fixture of 16 synthetic procurement passages and 32 labeled
queries, then stops before Qdrant starts. Qdrant stores 384-dimensional model
vectors in a separate benchmark collection. The report is saved to
`.local-fixtures/semantic_benchmark_report_v1.json` with Recall@1/5, MRR@10,
nDCG@10, timing summaries, and failed queries for both methods.

The fixture has 16 keyword queries and 16 paraphrases. It is a reproducible
synthetic regression diagnostic, not evidence of performance on real contracts
or a measurement of HNSW approximation at scale. The benchmark points are
separate from verified contract sources and must not be presented as citations.

## Private local passage search API

Run `powershell -ExecutionPolicy Bypass -File scripts/check_passage_search_api.ps1`
against the saved synthetic PostgreSQL volume after registering the three
verified contract passages. The script starts and stops PostgreSQL and checks
`POST /api/v1/evidence/passages/search` with a temporary demo bearer token.
The request accepts `tenant_id`, a nonblank `query` of at most 200 characters,
and `top_k` from 1 to 10. Results contain PostgreSQL source IDs, document
version, page, clause, text and PDF hashes, a snippet, and lexical rank.
The route requires `PROCUREGRAPH_ENABLE_DEMO_DB_API=1` and
`PROCUREGRAPH_DEMO_EVIDENCE_TOKEN` (at least 32 characters). It searches the
stored source-linked chunks; it does not re-read MinIO on every search or
expose the separate synthetic semantic benchmark as a citation. The shared
demo token is not production user authentication.

## Verified contract semantic index

Run `powershell -ExecutionPolicy Bypass -File scripts/check_verified_semantic_index.ps1`
after the verified passage registration and optional FastEmbed dependency are
in place. The script checks the manifest against PostgreSQL, stops PostgreSQL,
then starts Qdrant and embeds the same three PDF-derived clauses with the
cached local BGE small model. A separate collection keeps their stable source
IDs, tenant, document version, PDF hash, text hash, page and clause. The index
refuses changed points on repeat runs. Its diagnostic report is written to
`.local-fixtures/verified_semantic_report_v1.json` and includes three labeled
top-1 comparisons and a wrong-tenant query. Three synthetic clauses are too
few to establish retrieval quality. The private API below now exposes it.

## Semantic passage search API

Run `powershell -ExecutionPolicy Bypass -File scripts/check_semantic_passage_api.ps1`
after indexing the three verified chunks. This check briefly starts the saved
PostgreSQL and Qdrant containers together (256 MB and 512 MB container limits)
and stops both afterward. The private `POST /api/v1/evidence/passages/search`
request now accepts `retrieval_method: "qdrant_bge_small"`; omission keeps the
existing PostgreSQL lexical search. Semantic search requires the same demo
bearer token and `PROCUREGRAPH_QDRANT_ENDPOINT` on loopback. It embeds the query
locally, filters Qdrant by tenant, then looks up every returned source ID in
PostgreSQL and checks its current document version and exact source payload
before returning a PostgreSQL snippet. A stale or mismatched source fails the
whole request. This is a local synthetic demo, not production authentication;
the MinIO PDF is not reread on each search.

## Verified passage rank fusion

Set `retrieval_method: "rrf_60"` on the private passage search route to combine
the PostgreSQL lexical and verified Qdrant semantic rankings. The API takes at
most ten candidates from each, deduplicates by PostgreSQL source ID, and adds
`1/(60+rank)` for each ranking containing that source. It returns at most
`top_k` results with the fused score. Conflicting metadata for the same source
fails the request; a stale or mismatched Qdrant source also fails the request.
The existing token, tenant, and document-version checks still apply. Run
`powershell -ExecutionPolicy Bypass -File scripts/check_semantic_passage_api.ps1`
to check the fused mode against the saved synthetic demo, then stop both
containers. This three-clause check is not a broad retrieval evaluation.

## Locked synthetic rank-fusion comparison

Run `powershell -ExecutionPolicy Bypass -File scripts/check_semantic_benchmark.ps1`
to compare PostgreSQL full-text ranking, BGE-small Qdrant ranking, and the same
`rrf_60` ID-ranking formula used by the private API on the locked 16-passage,
32-query synthetic fixture. The report in
`.local-fixtures/semantic_benchmark_report_v1.json` includes Recall@1/5,
MRR@10 and nDCG@10 for lexical, semantic, and fused rankings. Its fusion
latency is an estimate from sequential lexical and Qdrant query times plus
local fusion time, excluding query embedding; it is not end-to-end API latency.
The benchmark passages are isolated synthetic labels, not verified PDF citations.

## Price-case graph source manifest

Run `powershell -ExecutionPolicy Bypass -File scripts/check_graph_manifest.ps1`
to export four canonical nodes (supplier, contract, purchase order, invoice)
and four checked foreign-key edges from the saved tenant-scoped PostgreSQL
price case. Each edge records the owning database table and source record ID.
The read-only export refuses inconsistent links, another tenant, and changed
content on a repeat run. It stores the local manifest in
`.local-fixtures/price_case_graph_manifest_v1.json` and stops PostgreSQL while
retaining its volume. This is an input for a later Neo4j import; no graph
database has been populated yet. The import will assign edge creation times.
