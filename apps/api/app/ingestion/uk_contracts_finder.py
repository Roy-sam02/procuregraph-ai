import argparse
import gzip
import json
from pathlib import Path


def summarize_notice(record: dict) -> dict:
    tender = record.get("tender") or {}
    awards = []

    for award in record.get("awards") or []:
        value = award.get("value") or {}
        awards.append({
            "id": award.get("id"),
            "amount": (
                str(value["amount"])
                if value.get("amount") is not None else None
            ),
            "currency": value.get("currency"),
            "suppliers": [
                {"id": supplier.get("id"), "name": supplier.get("name")}
                for supplier in award.get("suppliers") or []
            ],
            "document_urls": [
                document["url"]
                for document in award.get("documents") or []
                if document.get("url")
            ],
        })

    return {
        "ocid": record.get("ocid"),
        "tender_id": tender.get("id"),
        "tender_title": tender.get("title"),
        "tender_item_count": len(tender.get("items") or []),
        "awards": awards,
    }


def read_summaries(path: Path, limit: int):
    if limit < 1:
        raise ValueError("limit must be at least 1")

    with gzip.open(path, "rt", encoding="utf-8") as source:
        for number, line in enumerate(source):
            if number >= limit:
                break
            record = json.loads(line)
            yield summarize_notice(record)


def main():
    parser = argparse.ArgumentParser(
        description="Inspect UK Contracts Finder notices without loading the full file"
    )
    parser.add_argument("path", type=Path, help="Path to the .jsonl.gz download")
    parser.add_argument("--limit", type=int, default=3)
    arguments = parser.parse_args()

    for summary in read_summaries(arguments.path, arguments.limit):
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()