"""Verify the exact MinIO object version from a PostgreSQL source locator."""

import argparse
import json
import os
from pathlib import Path

import boto3
from botocore.config import Config

from apps.api.app.services.contract_evidence import (
    EXPECTED_SHA256, VerifiedFixture, verify_synthetic_pdf_bytes,
)
from datasets.generator.register_minio_location import validate_receipt
from datasets.generator.seed_price_case import database_id


def validate_locator(locator: dict) -> tuple[str, str, str]:
    required = {
        "tenant_id", "contract_id", "contract_line_id", "document_id",
        "document_version", "sha256", "bucket", "object_key", "object_version_id",
        "page", "price_clause", "tolerance_clause", "dates_clause",
        "max_unit_price", "tolerance_pct", "currency",
    }
    if not isinstance(locator, dict) or set(locator) != required:
        raise ValueError("Unexpected evidence locator fields")
    def identifier(label):
        return str(database_id("DEMO-001", label))
    expected = {
        "tenant_id": identifier("TENANT"), "contract_id": identifier("CON-001"),
        "contract_line_id": identifier("CL-001"),
        "document_id": identifier("CON-001/document/v1"),
        "document_version": 1, "sha256": EXPECTED_SHA256,
        "page": 1, "price_clause": "2.1", "tolerance_clause": "2.2",
        "dates_clause": "2.3", "max_unit_price": "100.00",
        "tolerance_pct": "5.00", "currency": "INR",
    }
    if any(locator[name] != value for name, value in expected.items()):
        raise ValueError("Evidence locator disagrees with synthetic document v1")
    return validate_receipt({
        "bucket": locator["bucket"], "object_key": locator["object_key"],
        "object_version_id": locator["object_version_id"],
        "sha256": locator["sha256"], "document_version": locator["document_version"],
    })[:3]


def read_verified_pdf(locator: dict, endpoint: str) -> tuple[bytes, VerifiedFixture]:
    """Return bytes only after the exact stored version and its clauses verify."""
    bucket, key, version_id = validate_locator(locator)
    s3 = boto3.client(
        "s3", endpoint_url=endpoint, region_name="us-east-1",
        aws_access_key_id=os.environ["PROCUREGRAPH_MINIO_USER"],
        aws_secret_access_key=os.environ["PROCUREGRAPH_MINIO_PASSWORD"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
    )
    response = s3.get_object(Bucket=bucket, Key=key, VersionId=version_id)
    try:
        data = response["Body"].read(2_000_001)
    finally:
        response["Body"].close()
    if len(data) > 2_000_000 or response.get("ContentType") != "application/pdf":
        raise ValueError("Stored object is too large or is not a PDF")
    if response.get("VersionId") != version_id:
        raise ValueError("Stored object version does not match the locator")
    checked = verify_synthetic_pdf_bytes(
        data, (locator["price_clause"], locator["tolerance_clause"], locator["dates_clause"])
    )
    if checked.sha256 != locator["sha256"] or checked.page != locator["page"]:
        raise ValueError("Stored PDF does not support the locator")
    return data, checked


def verify_stored_evidence(locator: dict, endpoint: str) -> VerifiedFixture:
    """Keep the existing check-only interface for the CLI and price API."""
    _, checked = read_verified_pdf(locator, endpoint)
    return checked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locator", type=Path)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    locator = json.loads(args.locator.read_text(encoding="utf-8"))
    verify_stored_evidence(locator, args.endpoint)
    print(f"PASS: downloaded document {locator['document_id']} version 1 from MinIO version {locator['object_version_id']}")
    print("PASS: SHA-256, page 1, price clause 2.1, tolerance clause 2.2, and dates clause 2.3 match")


if __name__ == "__main__":
    main()
