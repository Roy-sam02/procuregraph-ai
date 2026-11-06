"""Import and reconcile the checked local price-case graph manifest."""

import json
import os
import time
from pathlib import Path
from uuid import UUID

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from apps.api.app.services.neo4j_price_graph import import_manifest


def main() -> None:
    manifest = json.loads(Path(".local-fixtures/price_case_graph_manifest_v1.json")
                          .read_text(encoding="utf-8"))
    endpoint = os.environ["PROCUREGRAPH_NEO4J_BOLT"]
    password = os.environ["PROCUREGRAPH_NEO4J_PASSWORD"]
    if not endpoint.startswith("bolt://127.0.0.1:") or not endpoint.rsplit(":", 1)[1].isdigit():
        raise ValueError("Neo4j must use a loopback Bolt endpoint")
    with GraphDatabase.driver(endpoint, auth=("neo4j", password)) as driver:
        for attempt in range(90):
            try:
                driver.verify_connectivity()
                break
            except ServiceUnavailable:
                if attempt == 89:
                    raise
                time.sleep(1)
        first = import_manifest(driver, manifest)
        second = import_manifest(driver, manifest)
        if second != {"new_nodes": 0, "new_edges": 0}:
            raise ValueError("Repeat graph import changed existing records")
        ids = [node["id"] for node in manifest["nodes"]]
        records, _, _ = driver.execute_query(
            "MATCH (n) WHERE n.tenant_id = $tenant AND n.id IN $ids RETURN count(n) AS count",
            tenant=str(UUID(int=0)), ids=ids, database_="neo4j",
        )
        if records[0]["count"] != 0:
            raise ValueError("Other tenant could read graph nodes")
    print(f"PASS: Neo4j reconciled 4 nodes and 4 provenance edges; new {first['new_nodes']}/"
          f"{first['new_edges']}; repeat changed 0/0")
    print("PASS: other tenant found no graph nodes")


if __name__ == "__main__":
    main()
