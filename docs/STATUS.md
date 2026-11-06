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
