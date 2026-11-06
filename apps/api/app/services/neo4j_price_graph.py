"""Validated, idempotent Neo4j projection of one checked PostgreSQL manifest."""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

LABELS = ("Supplier", "Contract", "PurchaseOrder", "Invoice")
EDGES = {
    "HAS_CONTRACT": ("Supplier", "Contract", "contracts", "to_id"),
    "HAS_INVOICE": ("Supplier", "Invoice", "invoices", "to_id"),
    "REFERENCES_PO": ("Invoice", "PurchaseOrder", "invoices", "from_id"),
    "GOVERNED_BY": ("PurchaseOrder", "Contract", "purchase_orders", "from_id"),
}


def validate_manifest(manifest: dict) -> None:
    """Whitelist labels and edge types before they appear in static Cypher templates."""
    if set(manifest) != {"schema_version", "tenant_id", "invoice_line_id", "nodes", "edges"}:
        raise ValueError("Unexpected graph manifest fields")
    if manifest["schema_version"] != 1 or type(manifest["schema_version"]) is not int:
        raise ValueError("Unexpected graph manifest version")
    tenant = manifest["tenant_id"]
    if str(UUID(tenant)) != tenant or str(UUID(manifest["invoice_line_id"])) != manifest["invoice_line_id"]:
        raise ValueError("Invalid graph manifest IDs")
    nodes, edges = manifest["nodes"], manifest["edges"]
    if (not isinstance(nodes, list) or not isinstance(edges, list)
            or len(nodes) != 4 or len(edges) != 4
            or any(not isinstance(node, dict) for node in nodes)
            or any(not isinstance(edge, dict) for edge in edges)
            or {node.get("label") for node in nodes} != set(LABELS)
            or {edge.get("type") for edge in edges} != set(EDGES)):
        raise ValueError("Unexpected graph manifest shape")
    by_label = {}
    for node in nodes:
        required = {"label", "id", "tenant_id"}
        if node["label"] == "Supplier":
            required.add("legal_name")
            if not isinstance(node.get("legal_name"), str) or not node["legal_name"].strip():
                raise ValueError("Invalid supplier name")
        if set(node) != required or node["tenant_id"] != tenant or str(UUID(node["id"])) != node["id"]:
            raise ValueError("Invalid graph node")
        by_label[node["label"]] = node
    for edge in edges:
        if set(edge) != {"id", "type", "from_id", "to_id", "tenant_id",
                         "source_type", "source_id", "extraction_method"}:
            raise ValueError("Invalid graph edge")
        start, end, source_table, source_field = EDGES[edge["type"]]
        if (edge["tenant_id"] != tenant
                or edge["from_id"] != by_label[start]["id"]
                or edge["to_id"] != by_label[end]["id"]
                or edge["source_type"] != source_table
                or edge["source_id"] != edge[source_field]
                or edge["extraction_method"] != "checked_relational_fk"
                or edge["id"] != str(uuid5(
                    NAMESPACE_URL,
                    f"procuregraph/graph/{tenant}/{edge['type']}/{edge['from_id']}/{edge['to_id']}",
                ))):
            raise ValueError("Invalid graph edge provenance")


def _existing(tx, tenant: str, node_ids: list[str], edge_ids: list[str]) -> tuple[dict, dict]:
    nodes = {}
    for row in tx.run(
        "MATCH (n) WHERE n.tenant_id = $tenant AND n.id IN $ids "
        "RETURN labels(n) AS labels, properties(n) AS props",
        tenant=tenant, ids=node_ids,
    ):
        props = row["props"]
        if props["id"] in nodes:
            raise ValueError("Duplicate graph node ID")
        nodes[props["id"]] = (row["labels"], props)
    edges = {}
    for row in tx.run(
        "MATCH (a)-[r]->(b) WHERE r.tenant_id = $tenant AND r.id IN $ids "
        "RETURN type(r) AS type, properties(r) AS props, "
        "a.id AS from_id, b.id AS to_id, a.tenant_id AS from_tenant, b.tenant_id AS to_tenant",
        tenant=tenant, ids=edge_ids,
    ):
        props = row["props"]
        if props["id"] in edges:
            raise ValueError("Duplicate graph edge ID")
        edges[props["id"]] = row
    return nodes, edges


def _check_existing(manifest: dict, nodes: dict, edges: dict) -> None:
    tenant = manifest["tenant_id"]
    for node in manifest["nodes"]:
        stored = nodes.get(node["id"])
        if stored is not None:
            label, props = stored
            if label != [node["label"]] or props != {key: value for key, value in node.items()
                                                       if key != "label"}:
                raise ValueError("Existing Neo4j node differs from PostgreSQL manifest")
    for edge in manifest["edges"]:
        stored = edges.get(edge["id"])
        if stored is not None:
            props = stored["props"]
            created_at = props.get("created_at")
            try:
                timestamp = datetime.fromisoformat(created_at)
            except (TypeError, ValueError):
                timestamp = None
            if (stored["type"] != edge["type"]
                    or stored["from_id"] != edge["from_id"]
                    or stored["to_id"] != edge["to_id"]
                    or stored["from_tenant"] != tenant or stored["to_tenant"] != tenant
                    or timestamp is None or timestamp.tzinfo is None
                    or {key: value for key, value in props.items() if key != "created_at"} != edge):
                raise ValueError("Existing Neo4j edge differs from PostgreSQL manifest")


def _write(tx, manifest: dict) -> dict:
    tenant = manifest["tenant_id"]
    node_ids = [node["id"] for node in manifest["nodes"]]
    edge_ids = [edge["id"] for edge in manifest["edges"]]
    nodes, edges = _existing(tx, tenant, node_ids, edge_ids)
    _check_existing(manifest, nodes, edges)
    new_nodes, new_edges = 0, 0
    for node in manifest["nodes"]:
        if node["id"] not in nodes:
            label = node["label"]  # validated against LABELS
            props = {key: value for key, value in node.items() if key != "label"}
            tx.run(f"MERGE (n:{label} {{tenant_id:$tenant, id:$id}}) "
                   "ON CREATE SET n += $props", tenant=tenant, id=node["id"], props=props).consume()
            new_nodes += 1
    for edge in manifest["edges"]:
        if edge["id"] not in edges:
            start, end, _, _ = EDGES[edge["type"]]
            kind = edge["type"]  # validated against EDGES
            props = {**edge, "created_at": datetime.now(timezone.utc).isoformat()}
            tx.run(
                f"MATCH (a:{start} {{tenant_id:$tenant, id:$from_id}}) "
                f"MATCH (b:{end} {{tenant_id:$tenant, id:$to_id}}) "
                f"MERGE (a)-[r:{kind} {{tenant_id:$tenant, id:$edge_id}}]->(b) "
                "ON CREATE SET r += $props",
                tenant=tenant, from_id=edge["from_id"], to_id=edge["to_id"],
                edge_id=edge["id"], props=props,
            ).consume()
            new_edges += 1
    final_nodes, final_edges = _existing(tx, tenant, node_ids, edge_ids)
    _check_existing(manifest, final_nodes, final_edges)
    if len(final_nodes) != 4 or len(final_edges) != 4:
        raise ValueError("Neo4j graph reconciliation did not find four nodes and edges")
    return {"new_nodes": new_nodes, "new_edges": new_edges}


def import_manifest(driver, manifest: dict) -> dict:
    validate_manifest(manifest)
    with driver.session(database="neo4j") as session:
        for label in LABELS:
            session.run(
                f"CREATE CONSTRAINT graph_{label.lower()}_identity IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE (n.tenant_id, n.id) IS UNIQUE"
            ).consume()
        for kind in EDGES:
            session.run(
                f"CREATE CONSTRAINT graph_{kind.lower()}_identity IF NOT EXISTS "
                f"FOR ()-[r:{kind}]-() REQUIRE (r.tenant_id, r.id) IS UNIQUE"
            ).consume()
        return session.execute_write(_write, manifest)
