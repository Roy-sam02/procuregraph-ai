"""Combine verified lexical and semantic passage rankings by reciprocal rank."""

RRF_K = 60
CANDIDATE_LIMIT = 10
SOURCE_FIELDS = (
    "source_id", "document_id", "document_version", "page", "clause",
    "start_offset", "end_offset", "source_sha256", "text_hash", "snippet",
)


def fuse_ranked_ids(lexical_ids: list[str], semantic_ids: list[str],
                    top_k: int) -> list[tuple[str, float]]:
    """Fuse two bounded rankings; also used by the isolated synthetic benchmark."""
    if type(top_k) is not int or not 1 <= top_k <= CANDIDATE_LIMIT:
        raise ValueError("top_k must be an integer from 1 to 10")
    scores: dict[str, float] = {}
    for ranking in (lexical_ids, semantic_ids):
        if len(ranking) > CANDIDATE_LIMIT or len(ranking) != len(set(ranking)):
            raise ValueError("Unbounded or duplicate retrieval candidates")
        for rank, source_id in enumerate(ranking, start=1):
            scores[source_id] = scores.get(source_id, 0.0) + 1.0 / (RRF_K + rank)
    ordered = sorted(scores, key=lambda source_id: (-scores[source_id], source_id))[:top_k]
    return [(source_id, scores[source_id]) for source_id in ordered]


def fuse_passage_rankings(lexical: list[dict], semantic: list[dict], top_k: int) -> list[dict]:
    """Return source-linked hits, with a single entry for each verified source ID."""
    sources: dict[str, dict] = {}
    for ranking in (lexical, semantic):
        for hit in ranking:
            source_id = hit["source_id"]
            if source_id in sources:
                if any(sources[source_id][field] != hit[field] for field in SOURCE_FIELDS):
                    raise ValueError("Conflicting source metadata across retrieval rankings")
            else:
                sources[source_id] = hit
    ordered = fuse_ranked_ids(
        [hit["source_id"] for hit in lexical],
        [hit["source_id"] for hit in semantic], top_k,
    )
    return [{**{field: sources[source_id][field] for field in SOURCE_FIELDS},
             "retrieval_method": "rrf_60", "score": score}
            for source_id, score in ordered]
