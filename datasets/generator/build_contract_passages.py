"""Build an idempotent local clause manifest from a verified MinIO object version."""

import argparse
import json
from pathlib import Path

from apps.api.app.ingestion.contract_passages import extract_contract_passages
from datasets.generator.verify_evidence_locator import read_verified_pdf


def build(locator_path: Path, output: Path, endpoint: str) -> dict:
    locator = json.loads(locator_path.read_text(encoding="utf-8"))
    pdf, _ = read_verified_pdf(locator, endpoint)
    manifest = extract_contract_passages(pdf, locator)
    if output.exists():
        if json.loads(output.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Existing passage manifest differs; it was not overwritten")
        print("PASS: existing three-clause manifest matches; no file changed")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("PASS: wrote three deterministic page-1 clause passages from verified MinIO bytes")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locator", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    build(args.locator, args.output, args.endpoint)


if __name__ == "__main__":
    main()
