"""Validate the exact synthetic PDF before recording fixture provenance."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

EXPECTED_SHA256 = "4ae87579a28b27d62cf9d92a5f99876bb03b069baa5576bb2dd7d74406d57b0f"
CLAUSES = ("2.1", "2.2", "2.3")


@dataclass(frozen=True)
class VerifiedFixture:
    sha256: str
    version: int = 1
    page: int = 1
    price_clause: str = "2.1"
    tolerance_clause: str = "2.2"
    dates_clause: str = "2.3"


def verify_synthetic_pdf(path: Path, clauses: tuple[str, str, str] = CLAUSES) -> VerifiedFixture:
    """Check identity, page, and clause text; this is not a served citation."""
    if clauses != CLAUSES:
        raise ValueError("Incorrect clause references for the synthetic price term")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"Unexpected PDF SHA-256: {digest}")
    reader = PdfReader(path, strict=True)
    if len(reader.pages) != 1:
        raise ValueError("Synthetic contract must have exactly one page")
    text = " ".join((reader.pages[0].extract_text() or "").split())
    required_header = (
        "SYNTHETIC DEMONSTRATION", "NOT A REAL CONTRACT", "Contract ID: CON-001",
        "Document version: 1", "Supplier ID: SUP-001", "Supplier name: Aster Supplies",
        "Product ID: PROD-001", "Currency: INR",
        "Contract effective period: 1 January 2025 through 31 December 2025, inclusive",
    )
    if any(item not in text for item in required_header):
        raise ValueError("PDF identity or contract dates are missing")
    parts = re.split(r"Clause (2\.[123])\s*[—–-]\s*", text)
    if len(parts) != 7 or tuple(parts[i] for i in (1, 3, 5)) != CLAUSES:
        raise ValueError("Expected clauses 2.1, 2.2, and 2.3 on page 1")
    price, tolerance, dates = parts[2], parts[4], parts[6]
    if "maximum contract unit price for product PROD-001 is INR 100.00 per each" not in price:
        raise ValueError("Clause 2.1 does not support the maximum price")
    if not all(s in tolerance for s in (
        "for PROD-001", "no more than 5.00%", "allowed unit price is INR 105.00 per each",
    )):
        raise ValueError("Clause 2.2 does not support the tolerance and allowed price")
    if "Clauses 2.1 and 2.2 apply from 1 January 2025 through 31 December 2025, inclusive" not in dates:
        raise ValueError("Clause 2.3 does not support the price-term dates")
    return VerifiedFixture(sha256=digest)
