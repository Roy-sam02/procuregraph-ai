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
