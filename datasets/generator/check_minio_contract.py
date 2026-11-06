"""Upload and read back the exact synthetic PDF from local MinIO."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from apps.api.app.services.contract_evidence import verify_synthetic_pdf

BUCKET = "procuregraph-synthetic"


def object_key(sha256: str) -> str:
    return f"demo-001/contracts/CON-001/v1/{sha256}.pdf"


def check_remote_bytes(body: bytes, expected_sha256: str) -> None:
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"Downloaded object hash mismatch: {actual}")


def ensure_versioned_bucket(s3) -> None:
    try:
        s3.head_bucket(Bucket=BUCKET)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            raise
        s3.create_bucket(Bucket=BUCKET)
    if s3.get_bucket_versioning(Bucket=BUCKET).get("Status") != "Enabled":
        s3.put_bucket_versioning(
            Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
        )
    if s3.get_bucket_versioning(Bucket=BUCKET).get("Status") != "Enabled":
        raise ValueError("Bucket versioning is not enabled")


def receipt_for(key: str, version_id: str, sha256: str) -> dict:
    # MinIO returned a UUID for the specific object version in this local demo.
    UUID(version_id)
    return {
        "bucket": BUCKET,
        "object_key": key,
        "object_version_id": version_id,
        "sha256": sha256,
        "document_version": 1,
    }


def upload_and_verify(pdf: Path, endpoint: str, receipt_path: Path | None = None) -> tuple[str, str]:
    verified = verify_synthetic_pdf(pdf)
    contents = pdf.read_bytes()
    key = object_key(verified.sha256)
    s3 = boto3.client(
        "s3", endpoint_url=endpoint, region_name="us-east-1",
        aws_access_key_id=os.environ["PROCUREGRAPH_MINIO_USER"],
        aws_secret_access_key=os.environ["PROCUREGRAPH_MINIO_PASSWORD"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    ensure_versioned_bucket(s3)
    try:
        uploaded = s3.put_object(
            Bucket=BUCKET, Key=key, Body=contents,
            ContentType="application/pdf", IfNoneMatch="*",
        )
        version_id = uploaded.get("VersionId")
        action = "uploaded"
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("412", "PreconditionFailed"):
            raise
        version_id = s3.head_object(Bucket=BUCKET, Key=key).get("VersionId")
        action = "already exists"
    if not version_id or version_id == "null":
        raise ValueError("Stored object has no usable version ID")
    response = s3.get_object(Bucket=BUCKET, Key=key, VersionId=version_id)
    try:
        downloaded = response["Body"].read()
    finally:
        response["Body"].close()
    check_remote_bytes(downloaded, verified.sha256)
    if response.get("ContentType") != "application/pdf":
        raise ValueError("Downloaded object has an unexpected content type")
    if receipt_path is not None:
        receipt = receipt_for(key, version_id, verified.sha256)
        if receipt_path.exists():
            if json.loads(receipt_path.read_text(encoding="utf-8")) != receipt:
                raise ValueError("Existing MinIO receipt differs; it was not overwritten")
        else:
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {action}; downloaded exact PDF from bucket={BUCKET}, key={key}")
    print(f"PASS: version_id={version_id}; sha256={verified.sha256}")
    return key, version_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--receipt", type=Path, help="Local metadata from a successful readback")
    args = parser.parse_args()
    upload_and_verify(args.pdf, args.endpoint, args.receipt)


if __name__ == "__main__":
    main()
