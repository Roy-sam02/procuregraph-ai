# ADR-001: Local price-check prototype

## Decision

Add `POST /api/v1/pricing/check` as a local learning and integration prototype.
It calls the deterministic price rule using caller-supplied values.

## Reason

This gives the backend and future frontend a small working vertical slice before
PostgreSQL, document evidence, authentication, and investigations are implemented.

## Boundary

The result is a calculation, not a verified procurement finding. Do not expose
this route in a public deployment without an authentication and API contract review.
The investigation API in the master specification remains the target interface.