"""Live read-only invoice graph check on the retained Neo4j volume."""

import json
import os
import time
from pathlib import Path
from uuid import UUID

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from apps.api.app.services.neo4j_invoice_query import read_invoice_chain
from datasets.generator.seed_price_case import database_id


def wait_for_bolt(driver, attempts: int = 240, pause=time.sleep) -> None:
    """Allow a slow low-memory Neo4j restart to finish before querying."""
    for attempt in range(attempts):
        try:
            driver.verify_connectivity()
            return
        except ServiceUnavailable:
            if attempt == attempts - 1:
                raise
            if (attempt + 1) % 30 == 0:
                print(f"Waiting for Neo4j Bolt readiness: {attempt + 1} checks", flush=True)
            pause(1)


def main() -> None:
    manifest = json.loads(Path(".local-fixtures/price_case_graph_manifest_v1.json")
                          .read_text(encoding="utf-8"))
    endpoint = os.environ["PROCUREGRAPH_NEO4J_BOLT"]
    if not endpoint.startswith("bolt://127.0.0.1:") or not endpoint.rsplit(":", 1)[1].isdigit():
        raise ValueError("Neo4j must use a loopback Bolt endpoint")
    tenant = database_id("DEMO-001", "TENANT")
    invoice = database_id("DEMO-001", "INV-001")
    with GraphDatabase.driver(endpoint, auth=("neo4j", os.environ["PROCUREGRAPH_NEO4J_PASSWORD"])) as driver:
        wait_for_bolt(driver)
        chain = read_invoice_chain(driver, manifest, tenant, invoice)
        assert chain is not None and len(chain["nodes"]) == 4 and len(chain["edges"]) == 4
        assert all(edge["source_id"] and edge["source_type"] and edge["created_at"]
                   for edge in chain["edges"])
        other = read_invoice_chain(driver, manifest, UUID(int=0), invoice)
        assert other is None, other
    print("PASS: read-only two-hop invoice graph returned four source-linked edges")
    print("PASS: another tenant received no graph chain")


if __name__ == "__main__":
    main()
