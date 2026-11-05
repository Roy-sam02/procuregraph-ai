# ADR-002: Explore public procurement notices separately

## Decision

Add a read-only, streaming explorer for the UK Contracts Finder 2025
OCDS download. Keep the downloaded file outside Git.

## Data boundary

These are real public tenders and awards. An award amount is not a
supplier invoice price or a contract-line unit price. Document URLs
are source references, not verified contract PDFs.

The master specification currently requires synthetic demo records.
This explorer is for offline development and evaluation. Using public
records in the interview demo requires an explicit demo-data decision
and checks of source terms, document access, and data quality.

## Source

UK Contracts Finder via the Open Contracting Data Registry:
https://data.open-contracting.org/en/publication/128
License listed by the registry: Open Government Licence v3.0.