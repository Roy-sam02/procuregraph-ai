"""Deterministic clause passages from the verified synthetic contract v1."""

import hashlib
import re
from io import BytesIO
from uuid import NAMESPACE_URL, uuid5

from pypdf import PdfReader

from apps.api.app.services.contract_evidence import CLAUSES, verify_synthetic_pdf_bytes
from datasets.generator.verify_evidence_locator import validate_locator

FOOTER = " Created solely as synthetic evidence for software testing and demonstration."
HEADING = re.compile(r"Clause (2\.[123])\s*[—–-]\s*")


def normalized_page_text(data: bytes) -> str:
    """Offsets in the manifest refer to this exact normalized page string."""
    reader = PdfReader(BytesIO(data), strict=True)
    if len(reader.pages) != 1:
        raise ValueError("Expected one page in the synthetic source")
    return " ".join((reader.pages[0].extract_text() or "").split())


def extract_contract_passages(data: bytes, locator: dict) -> dict:
    """Fail closed before assigning source IDs or persisting passage text."""
    validate_locator(locator)
    verify_synthetic_pdf_bytes(
        data, (locator["price_clause"], locator["tolerance_clause"], locator["dates_clause"])
    )
    page_text = normalized_page_text(data)
    if page_text.count(FOOTER) != 1 or not page_text.endswith(FOOTER.strip()):
        raise ValueError("Unexpected synthetic PDF footer")
    content_end = page_text.index(FOOTER)
    headings = list(HEADING.finditer(page_text[:content_end]))
    if tuple(match.group(1) for match in headings) != CLAUSES:
        raise ValueError("Expected exactly the three price clauses")

    page_text_hash = hashlib.sha256(page_text.encode("utf-8")).hexdigest()
    passages = []
    for position, heading in enumerate(headings):
        start = heading.start()
        end = headings[position + 1].start() if position + 1 < len(headings) else content_end
        while end > start and page_text[end - 1].isspace():
            end -= 1
        passage_text = page_text[start:end]
        text_hash = hashlib.sha256(passage_text.encode("utf-8")).hexdigest()
        clause = heading.group(1)
        identity = (f"{locator['tenant_id']}/{locator['document_id']}/"
                    f"{locator['document_version']}/{locator['sha256']}/"
                    f"{locator['page']}/{clause}/{start}/{end}/{text_hash}")
        passages.append({
            "id": str(uuid5(NAMESPACE_URL, f"procuregraph/chunk/{identity}")),
            "tenant_id": locator["tenant_id"], "contract_id": locator["contract_id"],
            "document_id": locator["document_id"],
            "document_version": locator["document_version"],
            "source_sha256": locator["sha256"], "page": locator["page"],
            "clause": clause, "start_offset": start, "end_offset": end,
            "page_text_hash": page_text_hash, "text_hash": text_hash,
            "text": passage_text,
        })
    return {"schema_version": 1, "document_id": locator["document_id"],
            "document_version": locator["document_version"],
            "source_sha256": locator["sha256"], "passages": passages}
