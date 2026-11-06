"""Export and repeat-check the read-only PostgreSQL graph source manifest."""

import json
import os
from pathlib import Path
from uuid import UUID

import psycopg

from apps.api.app.services.graph_manifest import build_graph_manifest
from datasets.generator.seed_price_case import database_id


def save_manifest(manifest: dict, path: Path) -> bool:
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise ValueError("Existing graph manifest differs; no file overwritten")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def main() -> None:
    tenant = database_id("DEMO-001", "TENANT")
    invoice_line = database_id("DEMO-001", "IL-001")
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres",
        password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        manifest = build_graph_manifest(connection, tenant, invoice_line)
        try:
            build_graph_manifest(connection, UUID(int=0), invoice_line)
        except LookupError:
            pass
        else:
            raise AssertionError("Another tenant could read the graph source")
    path = Path(".local-fixtures/price_case_graph_manifest_v1.json")
    created = save_manifest(manifest, path)
    assert len(manifest["nodes"]) == 4 and len(manifest["edges"]) == 4
    print("PASS: four tenant-scoped PostgreSQL nodes and four FK-provenance edges exported"
          if created else "PASS: existing PostgreSQL graph manifest matches; no file changed")
    print("PASS: another tenant cannot retrieve this invoice line graph source")


if __name__ == "__main__":
    main()
