"""Locked synthetic retrieval fixture, PostgreSQL ranking, and exact-label metrics."""

import hashlib
import json
import math
import statistics
import time
from pathlib import Path

from psycopg import Connection

PG_QUERY = """
WITH input AS (
  SELECT websearch_to_tsquery('english', %s) AS terms
), passages AS (
  SELECT id, text FROM jsonb_to_recordset(%s::jsonb) AS p(id text, text text)
)
SELECT p.id, ts_rank_cd(to_tsvector('english', p.text), input.terms) AS score
FROM passages p CROSS JOIN input
WHERE to_tsvector('english', p.text) @@ input.terms
ORDER BY score DESC, p.id
LIMIT 10
"""


def load_fixture(path: Path) -> dict:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    passages, queries = fixture.get("passages"), fixture.get("queries")
    if (fixture.get("dataset_id") != "procurement-synthetic-retrieval-v1"
            or fixture.get("tenant_id") != "BENCH-TENANT-001"
            or not isinstance(passages, list) or len(passages) != 16
            or not isinstance(queries, list) or len(queries) != 32):
        raise ValueError("Unexpected benchmark fixture shape")
    ids = [p.get("id") for p in passages]
    if len(set(ids)) != 16 or any(
        not isinstance(p.get("text"), str) or not 30 <= len(p["text"]) <= 500
        for p in passages
    ):
        raise ValueError("Invalid benchmark passages")
    kinds = [q.get("kind") for q in queries]
    if (kinds.count("lexical") != 16 or kinds.count("paraphrase") != 16
            or any(q.get("gold") not in ids or not isinstance(q.get("text"), str)
                   or not 10 <= len(q["text"]) <= 160 for q in queries)):
        raise ValueError("Invalid benchmark relevance labels")
    return fixture


def fixture_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def postgres_ranking(connection: Connection, passages: list[dict], query: str) -> tuple[list[str], float]:
    started = time.perf_counter()
    with connection.cursor() as cursor:
        cursor.execute(PG_QUERY, (query, json.dumps(passages)))
        ids = [row[0] for row in cursor.fetchall()]
    return ids, (time.perf_counter() - started) * 1000


def score_queries(queries: list[dict], backend: str) -> dict:
    scores = {}
    for kind in ("all", "lexical", "paraphrase"):
        subset = [q for q in queries if kind == "all" or q["kind"] == kind]
        ranks = []
        for item in subset:
            ranked = item[backend]
            ranks.append(ranked.index(item["gold"]) + 1 if item["gold"] in ranked else None)
        scores[kind] = {
            "count": len(subset),
            "recall_at_1": sum(rank == 1 for rank in ranks) / len(ranks),
            "recall_at_5": sum(rank is not None and rank <= 5 for rank in ranks) / len(ranks),
            "mrr_at_10": sum(1 / rank for rank in ranks if rank is not None and rank <= 10) / len(ranks),
            "ndcg_at_10": sum(1 / math.log2(rank + 1)
                              for rank in ranks if rank is not None and rank <= 10) / len(ranks),
        }
    return scores


def latency_summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"p50_ms": statistics.median(ordered),
            "p95_ms": ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]}
