"""Query Qdrant and validate each returned source against current PostgreSQL rows."""

from uuid import UUID

from psycopg import Connection

from apps.api.app.services.qdrant_hash_demo import request_json
from apps.api.app.services.qdrant_semantic_sources import COLLECTION, source_payload, unit_vector

SOURCES_SQL = """
SELECT c.id, c.document_id, c.document_version, c.page, c.clause,
       c.start_offset, c.end_offset, c.source_sha256, c.text_hash, c.passage_text
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
JOIN document_object_locations location ON location.document_id = d.id
WHERE c.tenant_id = %s AND d.tenant_id = %s
  AND c.id = ANY(%s::uuid[])
  AND c.document_version = d.version
  AND c.source_sha256 = d.sha256 AND location.sha256 = d.sha256
  AND d.version = (
      SELECT max(current_document.version) FROM documents current_document
      WHERE current_document.contract_id = d.contract_id
  )
"""


def search_semantic_passages(connection: Connection, tenant_id: UUID, query: str,
                             top_k: int, endpoint: str, encoder) -> list[dict]:
    vector = unit_vector(encoder.encode([query])[0])
    response = request_json(endpoint, "POST", f"/collections/{COLLECTION}/points/query", {
        "query": vector,
        "filter": {"must": [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]},
        "limit": top_k, "with_payload": True,
    })
    if response is None:
        raise OSError("Semantic collection is unavailable")
    points = response["result"]["points"]
    if not points:
        return []
    ids = [UUID(point["id"]) for point in points]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate semantic source IDs")
    with connection.cursor() as cursor:
        cursor.execute(SOURCES_SQL, (tenant_id, tenant_id, ids))
        rows = cursor.fetchall()
    sources = {row[0]: row for row in rows}
    if len(sources) != len(points):
        raise ValueError("Qdrant source is missing or no longer current in PostgreSQL")
    hits = []
    for point, source_id in zip(points, ids):
        row = sources[source_id]
        passage = {"tenant_id": str(tenant_id), "document_id": str(row[1]),
                   "document_version": row[2], "page": row[3], "clause": row[4],
                   "start_offset": row[5], "end_offset": row[6],
                   "source_sha256": row[7], "text_hash": row[8]}
        if point["payload"] != source_payload(passage):
            raise ValueError("Qdrant source payload conflicts with PostgreSQL")
        hits.append({"source_id": str(source_id), "document_id": str(row[1]),
                     "document_version": row[2], "page": row[3], "clause": row[4],
                     "start_offset": row[5], "end_offset": row[6],
                     "source_sha256": row[7], "text_hash": row[8],
                     "snippet": row[9][:240], "retrieval_method": "qdrant_bge_small",
                     "score": float(point["score"])})
    return hits
