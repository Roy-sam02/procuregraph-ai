"""Local graph API bridge: validate Bolt endpoint and read a checked manifest."""

import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from apps.api.app.services.neo4j_invoice_query import read_invoice_chain


def local_bolt_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "bolt" or parsed.hostname != "127.0.0.1"
                or parsed.port is None or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Invalid local Bolt endpoint")
    except ValueError as exc:
        raise OSError("Graph Bolt endpoint must be loopback") from exc
    return endpoint


def read_checked_graph(tenant_id: UUID, invoice_id: UUID,
                       endpoint: str, password: str) -> dict | None:
    try:
        from neo4j import GraphDatabase
        from neo4j.exceptions import Neo4jError, ServiceUnavailable
    except ImportError as exc:
        raise OSError("Neo4j driver is not installed") from exc
    manifest = json.loads(Path(".local-fixtures/price_case_graph_manifest_v1.json")
                          .read_text(encoding="utf-8"))
    try:
        with GraphDatabase.driver(local_bolt_endpoint(endpoint),
                                  auth=("neo4j", password)) as driver:
            return read_invoice_chain(driver, manifest, tenant_id, invoice_id)
    except (Neo4jError, ServiceUnavailable) as exc:
        raise OSError("Local Neo4j is unavailable") from exc
