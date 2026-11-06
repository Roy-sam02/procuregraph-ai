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
