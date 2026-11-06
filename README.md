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
process. The evidence reference identifies a private source; it is not a PDF
download URL or an authenticated production citation service. The tenant UUID
in the request is only a lookup filter, not proof of authorization.

On the Windows machine with the retained demo volumes, run
`powershell -ExecutionPolicy Bypass -File scripts/check_verified_api.ps1` to
exercise the real API route with both containers briefly running. The script
stops the containers afterward and retains their volumes.
