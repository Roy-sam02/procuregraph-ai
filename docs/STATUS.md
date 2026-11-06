# Development status

## Phase 0 — Foundation

- VS Code project folder created on Windows.
- Python 3.12.10 ran `scripts/check_python.py`.
- Git repository created and connected to GitHub.
- `.gitignore` added for local secrets and generated files.
- Application features: not implemented yet.

## Verified commits

- `64c5f64` — README and Python practice script.
- `76a7665` — `.gitignore`.

## Next milestone

Define the first small procurement example and its deterministic price-checking rule.

## First rule — price threshold

- Implemented a same-currency contract price check using Decimal.
- Verified prices below, at, and above the allowed maximum.
- Test command: `py -m unittest discover -s tests/unit -p "test_*.py" -v`
- Result: 1 test passed.
- Limitations: no currency, date, or invalid-input validation yet.

## Backend health endpoint

- Added FastAPI application at `apps/api/app/main.py`.
- `GET /health/live` returned `{"status":"ok"}` locally.
- FastAPI generated `/docs`.
- Unit tests: 2 passed using the project virtual environment.
- Direct backend and test dependency versions recorded.
- Limitation: this is a liveness check; it does not check databases or other services.

## Pricing API prototype

- Added `POST /api/v1/pricing/check` using the existing price rule.
- Manually verified a 106 invoice price returned `true` for a 105 limit.
- Automated tests: 4 passed, including the boundary and invalid input.
- Decision: `docs/ADRs/ADR-001-local-price-check.md`.
- Limitation: caller-supplied values are not checked against stored evidence.

## First synthetic procurement case

- Added `datasets/fixtures/price_case_001.json`.
- Verified matching supplier, product, and currency references.
- Verified allowed unit price 105.00 and total excess 10.00.
- Automated tests: 5 passed.
- Limitation: fixture is a local JSON file, not PostgreSQL data or PDF evidence.
## Structured synthetic price assessment

- Added a structured assessment for the local synthetic price case.
- Supplier, product, and currency mismatches raise errors before calculation.
- The fixture produces an allowed unit price of INR 105.00 and excess of INR 10.00.
- A valid invoice at the limit produces no violation and zero excess.
- Full unit test suite passed.
- Limitation: this uses a local JSON fixture, not stored records or PDF evidence.

## Synthetic purchase order links

- Added invoice, purchase order, and PO line records to the price fixture.
- The assessment checks supplier, product, currency, and ID links before price arithmetic.
- Full unit test suite passed.
- Limitation: these are local JSON records, not PostgreSQL or PDF evidence.

## Public notice exploration

- Added a read-only streaming explorer for the UK Contracts Finder 2025 JSONL download.
- Verified the first three real records, including a notice with no award.
- Full unit test suite: 12 passed.
- The downloaded dataset remains outside Git.
- Limitation: awards and notices do not establish invoice price violations;
  public records are not yet part of the synthetic interview demo.

## Public notice database schema draft

- Drafted separate tables for public notices, awards, and award suppliers.
- Verified one award can link to two suppliers without storing its amount twice.
- Verified foreign keys reject an award without a notice and a supplier link without an award.
- These checks ran in a temporary PostgreSQL 17 practice container.
- Limitation: this is not an Alembic migration or persistent project database;
  document references and ingestion are still to be designed.


### Public award document references

- Sampled the first 1,000 UK Contracts Finder records. All 1,336 award document references had a usable source ID, URL, and award key. No document IDs repeated under the same award. Document type was unavailable for 211 references and format for 136.
- Added a draft `public_award_documents` table for source metadata. A temporary PostgreSQL 17 test accepted a valid award link and rejected a missing award pair. The existing unit suite passed.
- This is an offline public-data design. URL contents were not verified. No public data was imported and the draft is not an Alembic migration.


### Synthetic PostgreSQL persistence and first migration

- Added a local PostgreSQL 17 Compose service backed by a named volume.
- Applied Alembic revision `0001_create_organizations` to a fresh test database and inserted one synthetic organization.
- Verified that a replacement container using the same volume returned both the synthetic row and the stored revision. The unit suite passed and the temporary Compose resources were removed.
- Scope: the revision creates only `organizations`. FastAPI database integration and the remaining synthetic schema are pending. The public notice draft remains a separate offline design.


### Synthetic contract pricing schema

- Added Alembic revision `0002_create_contract_pricing` for suppliers, products, contracts, and contract lines.
- Verified in temporary PostgreSQL 17 that a synthetic INR contract line stored a unit-price cap of 100.00 and a tolerance of 5.00 percent. The contract foreign key rejected a line pointing to a missing contract.
- All 12 unit tests passed. The temporary Compose resources were removed.
- Purchase order and invoice tables, invoice-date price selection, tenant access enforcement, and contract document versioning are pending.


### Synthetic purchase orders and invoices

- Added Alembic revision `0003_create_order_billing` for purchase orders, PO lines, invoices, and invoice lines.
- Verified in temporary PostgreSQL 17 that a synthetic invoice line traces through its PO to the contract price. A foreign key rejected a missing PO line.
- All 12 unit tests passed. The temporary Compose resources were removed.
- Loading the JSON fixture into these tables, selecting contract terms by invoice date, and assessing a database-backed case are pending.


### Synthetic price case database seed

- Added a seed command for `price_case_001.json` using stable UUIDs derived from its readable fixture IDs.
- Verified in a fresh temporary PostgreSQL database that the stored case traces through the invoice, PO, supplier, product, and active contract price term. The existing price assessment returned an allowed unit price of INR 105.00 and total excess of INR 10.00.
- All 12 unit tests passed. The temporary Compose container, volume, and network were removed.
- Scope: one synthetic case with explicitly supplied 2025 dates and product details. The seed rejects a repeat run on the same database. FastAPI still uses its existing prototype price-check contract.


### Read-only database price assessment

- Added a tenant-scoped Python service that reads an invoice line and its linked supplier, product, PO, contract, and applicable price term from PostgreSQL, then calls the existing deterministic assessment.
- Verified the seeded case returned an INR 105.00 unit-price limit and INR 10.00 excess. Changing the stored invoice price to INR 108.00 changed the excess to INR 30.00. A different tenant could not retrieve the case, and overlapping active price terms were rejected.
- All 12 unit tests passed. The temporary Compose resources were removed.
- The service is not yet exposed through an HTTP endpoint. The current schema's tenant and cross-record guarantees still need review before treating this as a production authorization boundary.


### Synthetic database price API

- Added `POST /api/v1/pricing/cases/assess` for a stored synthetic invoice line, enabled locally with `PROCUREGRAPH_ENABLE_DEMO_DB_API=1`.
- Verified the endpoint returns an INR 105.00 allowed unit price and INR 10.00 excess. A different tenant UUID receives 404. The existing Boolean price-check contract still passes its tests.
- The unit suite and temporary PostgreSQL integration check passed. The endpoint has no user authentication; its supplied tenant UUID is a lookup filter, not proof of identity. It is disabled unless explicitly enabled for the local synthetic demo.


### Live synthetic price API smoke test

- Started one temporary PostgreSQL 17 service, applied Alembic migrations, seeded the synthetic price case, and served FastAPI through local Uvicorn.
- A live HTTP request to the stored-case endpoint returned the INR 105 allowed unit price and INR 10 excess. The existing Boolean calculator also returned a violation for its test input.
- This exercised the local synthetic demo with `PROCUREGRAPH_ENABLE_DEMO_DB_API=1`. The supplied tenant UUID is a lookup filter; user authentication and tenant authorization remain pending.


### Reusable local synthetic demo

- Added PowerShell start and stop scripts for a local FastAPI and PostgreSQL synthetic price demonstration.
- Verified start, stop, start, and stop. Both starts returned the INR 105 allowed price and INR 10 excess through the live API. The second start reused the seeded PostgreSQL volume.
- The stop script retains the named volume. The local `.env`, process ID, port, and logs are ignored by Git. The stored-case endpoint remains a local synthetic demo without user authentication.

### Contract PDF fixture provenance (local checks)

- Inspected the actual one-page, selectable-text synthetic PDF. Its SHA-256 is `4ae87579a28b27d62cf9d92a5f99876bb03b069baa5576bb2dd7d74406d57b0f`.
- Checked identity and clause 2.1 (INR 100.00), 2.2 (5.00%, INR 105.00), and 2.3 (2025 dates). A changed PDF and swapped clause references were rejected.
- The unit suite passed 18 tests with `PROCUREGRAPH_CONTRACT_PDF` set to the actual file; the check-only attachment command also passed.
- Applied revision 0004 and attached the verified PDF fixture to the stored price term. PostgreSQL returned version 1, the expected SHA-256, fixture storage with no object key, page 1, and clauses 2.1/2.2/2.3.
- A repeat attachment changed no rows. PostgreSQL rejected an update to the immutable document record.
- The local demo started successfully on retry after attachment; its existing API returned the INR 105 limit and INR 10 excess. The first startup attempt timed out, with no error captured in its logs.
- `storage_backend=fixture` has no object key or served citation. The PDF is local test input; MinIO upload, content recheck on retrieval, and a source-serving citation are future increments.

### MinIO PDF storage exercise

- Added a separate Compose service for one local MinIO container with a retained volume. The image was resolved to a digest for the live run.
- Enabled bucket versioning, uploaded the checked CON-001 PDF, and read back the specific stored object version. The downloaded bytes matched SHA-256 `4ae87579a28b27d62cf9d92a5f99876bb03b069baa5576bb2dd7d74406d57b0f`.
- A repeat run found the existing object and returned the same MinIO version ID. The 19-test unit suite and the live upload/readback check passed.

### MinIO location linked to document v1

- Added Alembic revision 0005 for an append-only MinIO object location linked to the existing document v1. The original fixture document row was not rewritten.
- A local receipt carried the bucket, object key, MinIO version ID, and SHA-256 after readback. MinIO was stopped before PostgreSQL was started.
- Verified PostgreSQL linked the location to document v1 and its page 1 price clauses. A repeat registration changed no rows, and PostgreSQL rejected an update to the location.
- The 21-test unit suite passed. Both local container checks passed sequentially, and their named volumes were retained.
- The receipt is a local handoff for this synthetic demo. The API does not yet fetch and recheck the object when serving evidence, so it does not yet provide a verified citation. A revised contract PDF will need version-aware price-term evidence links.

### Verified stored PDF readback

- Added a local read path that exports the tenant-scoped document and price-term locator from PostgreSQL, then retrieves the exact registered MinIO object version.
- The retrieved PDF is checked against its SHA-256 and selectable page 1 text: clause 2.1 for INR 100.00, clause 2.2 for 5.00% and INR 105.00, and clause 2.3 for the 2025 effective dates.
- The 24-test unit suite passed against the actual synthetic PDF, including changed-byte, incorrect-clause, and wrong-tenant checks.
- The live check passed with PostgreSQL and MinIO run sequentially. Both containers were stopped afterward and their saved volumes retained.
- This is a local synthetic evidence check. The API does not yet retrieve the PDF or serve a verified citation to callers.

### Verified source reference in the synthetic price API

- Added an opt-in include_verified_evidence field to the stored price assessment API. It reads the tenant-scoped source, retrieves the exact MinIO object version, and checks the PDF hash, page, and clauses before returning a source reference.
- A plain assessment has no citation. An unavailable or inconsistent source returns an error without a citation.
- The 28-test unit suite passed against the synthetic PDF. The live API check passed on the saved PostgreSQL and MinIO volumes: verified reference returned, plain assessment had no citation, and a different tenant received no source. Both containers were stopped afterward.
- The reference identifies the private PDF; it is not a download URL. The demo does not yet authenticate users.

### Token-protected verified PDF download

- Added a local demo PDF route linked from the verified price evidence reference. It requires a configured bearer token and rechecks the tenant-scoped database link and exact MinIO object version before returning PDF bytes.
- Missing or wrong tokens are rejected before database or storage access. Changed PDF bytes return no PDF. The response prevents caching.
- All 31 unit tests passed against the synthetic PDF. The live check passed on the saved PostgreSQL and MinIO volumes: verified bytes returned with a token, missing and wrong tokens were denied, and a different tenant received no source. Both containers were stopped afterward.
- The shared demo token is not user authentication or role-based tenant authorization. This route is for the local synthetic demo only.

### Verified contract clause passages

- Added deterministic extraction of clauses 2.1, 2.2, and 2.3 from the verified synthetic contract PDF. Each passage records a stable ID, tenant, document version, page, clause, source and text hashes, and offsets into normalized page text.
- The local check exports the PostgreSQL source locator, reads and verifies the exact MinIO object version, then writes an idempotent passage manifest in .local-fixtures.
- All 34 local unit tests passed with the project PDF parser. The live Windows check wrote three page-1 passages from the saved database and MinIO volumes; both containers stopped afterward.
- The passages are not yet stored in PostgreSQL or indexed in Qdrant.

### PostgreSQL passage storage and lexical search

- Added Alembic revision 0006 for append-only, source-linked document chunks and a PostgreSQL full-text index.
- Registration re-reads the database-linked MinIO PDF, verifies its bytes, regenerates the three passages, and compares them with the manifest before writing rows in one transaction.
- Added bounded, tenant-scoped lexical search over the latest contract document version.
- All 37 local unit tests passed. The live Windows check registered three chunks; repeat registration changed no rows. Search returned clauses 2.2 and 2.3, a different tenant received no results, and PostgreSQL rejected an update. Both containers stopped afterward.
- This is the PostgreSQL lexical baseline. Qdrant indexing, retrieval benchmarks, and an HTTP search endpoint remain pending.

### Local Qdrant vector wiring

- Added a separate loopback-only Qdrant container with a retained volume. PostgreSQL and Qdrant run sequentially for the local low-memory check.
- Exported three source-checked PostgreSQL chunks and labeled lexical rankings. Qdrant stores the same stable source IDs with tenant and document filters.
- Used deterministic token-hash-128-v1 vectors for a wiring exercise. These are not semantic embeddings, and three synthetic queries do not establish ANN quality or speed.
- All 42 local unit tests passed. The live Windows check indexed three points; repeat indexing changed no points. Three labeled queries found the expected clauses in PostgreSQL and Qdrant, and a different tenant received no Qdrant hits. Qdrant was stopped and its volume retained.
- Semantic embeddings, a larger locked retrieval benchmark, and application API integration remain pending.

### Local semantic retrieval benchmark

- Added CPU-based BGE small embeddings and a separate Qdrant benchmark collection.
- Compared PostgreSQL full-text search and semantic Qdrant search on 16 synthetic procurement passages and 32 labeled queries.
- The live Windows check passed: PostgreSQL Recall@5 was 0.375 (12/32); semantic Qdrant Recall@5 was 0.969 (31/32). The other-tenant Qdrant query returned no points.
- The initial model download recovered from connection errors. PostgreSQL and Qdrant were stopped after their sequential checks.
- All 45 local unit tests passed. This locked synthetic diagnostic does not establish performance on real contracts; the benchmark passages are separate from verified PDF citations.

### Private passage search API

- Added a token-protected API route for tenant-scoped PostgreSQL search over stored, source-linked contract passages.
- The live Windows check returned clause 2.2 with its document source. Missing and wrong tokens were denied, another tenant received no hits, and an invalid result limit was rejected.
- All 48 local unit tests passed. Search uses stored verified chunks; it does not recheck MinIO on each request or serve the separate semantic benchmark passages as contract evidence.

### Verified contract semantic index

- Embedded the three PostgreSQL-verified contract passages with the local BGE small model and indexed their stable source IDs in a separate Qdrant collection.
- The live Windows check found the existing PostgreSQL export unchanged. Repeat Qdrant indexing changed no points; tenant, document version, and PDF hash filters were checked, and another tenant received no hits.
- All three labeled diagnostic queries ranked the expected clause first. This three-clause result is not a broad retrieval-quality benchmark.
- All 50 local unit tests passed. PostgreSQL and Qdrant stopped after their sequential checks; the semantic index is not yet exposed through the API.

### Semantic passage search API

- Added `qdrant_bge_small` as a private passage-search option; PostgreSQL lexical search remains the default.
- Before returning a semantic snippet, the API checks its current tenant-scoped PostgreSQL source, document version, and exact source payload.
- The live Windows check passed: Qdrant clause 2.2 matched the current PostgreSQL source and lexical result; a missing token was denied; another tenant received no semantic hits.
- PostgreSQL and Qdrant stopped after the check, with their volumes retained. The three-query diagnostic is small, and the separate synthetic benchmark passages are not verified contract citations.

### Verified passage rank fusion

- Added bounded `rrf_60` passage search, combining PostgreSQL lexical and verified Qdrant semantic ranks by source ID. Existing lexical search remains the default.
- The Windows unit suite passed: 56 tests run, 18 skipped.
- The live Windows check returned one PostgreSQL-backed clause 2.2 source from fusion. The missing token was denied, and another tenant received no semantic or fused hits.
- PostgreSQL and Qdrant stopped after the check; their volumes were retained. This three-clause live check does not establish broad retrieval quality. The separate synthetic benchmark passages are not verified contract citations.

### Locked synthetic rank-fusion comparison

- Evaluated PostgreSQL lexical, BGE-small Qdrant, and `rrf_60` rankings on the same locked set of 16 synthetic passages and 32 labeled queries.
- Live Windows results (R@1 / R@5 / MRR@10 / nDCG@10): PostgreSQL 0.375 / 0.375 / 0.375 / 0.375; Qdrant 0.938 / 0.969 / 0.958 / 0.968; fusion 0.938 / 0.969 / 0.958 / 0.968.
- Fusion matched semantic retrieval on this fixture; it did not improve these measured scores. These synthetic passages are not verified contract citations, and this diagnostic does not establish real-world retrieval quality.
- The benchmark ran PostgreSQL and Qdrant sequentially and stopped both afterward, retaining their volumes.

### Price-case graph source manifest

- Added a read-only, tenant-scoped PostgreSQL export of four canonical price-case nodes and four checked foreign-key relationships. Each proposed edge records its source table and record ID.
- The Windows unit suite passed: 60 tests run, 18 skipped.
- The live Windows check found the existing graph manifest unchanged on both runs; another tenant could not retrieve the invoice-line graph source.
- PostgreSQL stopped afterward and its volume was retained. This is a source manifest for a later Neo4j import; Neo4j has not been populated by this step.

### Local Neo4j price-case graph

- Added a separate, retained Neo4j container and a validated import of the tenant-scoped PostgreSQL price-case graph manifest.
- The live Windows check reverified the PostgreSQL manifest, imported 4 nodes and 4 source-linked edges into Neo4j, and found no changes on a repeat import (0 nodes, 0 edges).
- A different tenant found no graph nodes. PostgreSQL stopped before Neo4j started; Neo4j stopped after verification, with both volumes retained.
- This graph covers one synthetic price case. It is not yet a graph query API or a general procurement graph.

### Read-only invoice graph query

- Added a fixed, parameterized, two-hop Neo4j query for the synthetic invoice's supplier, purchase order, and contract relationships. Returned nodes and edge provenance are checked against the saved graph manifest.
- The Windows unit suite passed: 68 tests run, 18 skipped.
- The live Windows check returned four source-linked edges; another tenant received no graph chain. Neo4j needed more than 150 readiness checks on this laptop, so the check now allows up to 240 and prints progress.
- Neo4j stopped afterward with its volume retained. This is a local read tool, not yet an HTTP endpoint; PostgreSQL is not reread during each graph query.

### Private invoice graph API

- The Windows check passed: the token-protected route returned four checked
  graph edges; a missing token was denied and another tenant saw no chain.
- Pushed as `c56c650`. The route compares against its saved PostgreSQL manifest,
  not a fresh database read on each request.

### Investigation price evidence gate

- Added a pure read-only verifier that cross-checks the stored price assessment,
  exact document version and clauses, and the checked four-edge invoice chain.
- It independently recalculates price arithmetic and refuses a finding if a
  tenant, source identity, PDF hash, graph edge, or amount disagrees.
- Local unit suite: 76 tests run, 18 skipped. Live Windows integration remains
  to be checked; this step adds no LangGraph runtime or investigation API.

### Bounded investigation workflow

- Added a LangGraph state machine with four fixed read/verify nodes, injected
  read-only source functions, and early stop on source errors.
- A consistent violation yields `needs_review`, a consistent non-violation
  `complete`, and missing/conflicting sources `abstained` without a finding.
- Local unit suite: 81 tests run, 18 skipped. No live multi-service check,
  authentication, checkpointer, approval record, or investigation endpoint yet.

### Sequential investigation integration diagnostic

- Added a staged check that reads current PostgreSQL price and graph sources,
  verifies the exact MinIO PDF, then runs the bounded investigation with a
  live Neo4j chain. Each container stops before the next starts.
- Local unit suite: 86 tests run, 18 skipped. The live Windows Docker result is
  pending. Stage files are generated in a fresh ignored directory and removed
  afterward. This diagnostic is not an atomic multi-store snapshot or API.

### Staged live investigation result

- Windows check passed: current PostgreSQL source, exact MinIO PDF and Neo4j
  chain produced a verified INR 10.00 price violation held for review.
- Another tenant received no finding. The staged check stops each container
  before starting the next. Pushed as `76eec42`.

### Investigation record storage

- Alembic revision 0007 adds tenant-scoped investigation rows and at most one
  finding with source evidence JSON. A tenant/idempotency key refuses changed
  content and returns the same ID for an identical retry.
- Local unit suite: 91 tests run, 18 skipped. Live Windows PostgreSQL migration
  and repeat check remain pending. No investigation HTTP route or approval event.

### Investigation storage live check

- Windows PostgreSQL check passed: an abstained run persisted with one stable ID
  on retry; another tenant saw no run, and changed content could not reuse its
  key. Pushed as `572bd86`.

### Verified live finding persistence

- The staged diagnostic now reopens PostgreSQL after Neo4j stops, rechecks its
  current price and graph sources against the captured PDF/graph evidence, and
  records the verified INR 10.00 finding once. It tests repeat and tenant reads.
- Local unit suite: 93 tests run, 18 skipped. The live Windows sequential check
  is pending. No investigation endpoint or human approval has been added.

### Verified finding persistence live result

- Windows sequential check passed: a verified INR 10.00 finding with PDF and
  graph source IDs was saved once; retry reused its ID, another tenant could
  not read it, and all containers stopped. Pushed as `c8653ae`.

### Private investigation result API

- Added a token-gated read of tenant-filtered persisted investigation and
  finding records. A missing token is denied before DB access; absent tenant
  records return 404; an inconsistent stored shape returns 409.
- Local unit suite: 97 tests run, 18 skipped. Live Windows PostgreSQL API
  check pending. The demo token is shared, not a tenant-bound user identity.
