"""Tenant-scoped PostgreSQL lexical retrieval of active document passages."""

from uuid import UUID

from psycopg import Connection

SEARCH_SQL = """
WITH search_query AS (
    SELECT websearch_to_tsquery('english', %s) AS terms
)
SELECT c.id, c.document_id, c.document_version, c.page, c.clause,
       c.start_offset, c.end_offset, c.source_sha256, c.text_hash,
       c.passage_text, ts_rank_cd(c.search_vector, search_query.terms) AS score
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
JOIN document_object_locations location ON location.document_id = d.id
CROSS JOIN search_query
WHERE c.tenant_id = %s AND d.tenant_id = %s
  AND c.document_version = d.version
  AND c.source_sha256 = d.sha256 AND location.sha256 = d.sha256
  AND d.version = (
      SELECT max(current_document.version) FROM documents current_document
      WHERE current_document.contract_id = d.contract_id
  )
  AND c.search_vector @@ search_query.terms
ORDER BY score DESC, c.id
LIMIT %s
"""


def search_passages(connection: Connection, tenant_id: UUID, query: str, top_k: int = 5) -> list[dict]:
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("Query must contain 1 to 200 characters")
    if type(top_k) is not int or not 1 <= top_k <= 10:
        raise ValueError("top_k must be an integer from 1 to 10")
    with connection.cursor() as cursor:
        cursor.execute(SEARCH_SQL, (query.strip(), tenant_id, tenant_id, top_k))
        rows = cursor.fetchall()
    return [{
        "source_id": str(row[0]), "document_id": str(row[1]),
        "document_version": row[2], "page": row[3], "clause": row[4],
        "start_offset": row[5], "end_offset": row[6],
        "source_sha256": row[7], "text_hash": row[8],
        "snippet": row[9][:240], "retrieval_method": "postgres_fts",
        "score": float(row[10]),
    } for row in rows]
