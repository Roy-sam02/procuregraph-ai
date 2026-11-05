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