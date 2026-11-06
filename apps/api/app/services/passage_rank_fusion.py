"""Combine verified lexical and semantic passage rankings by reciprocal rank."""

RRF_K = 60
CANDIDATE_LIMIT = 10
SOURCE_FIELDS = (
    "source_id", "document_id", "document_version", "page", "clause",
    "start_offset", "end_offset", "source_sha256", "text_hash", "snippet",
)


def fuse_passage_rankings(lexical: list[dict], semantic: list[dict], top_k: int) -> list[dict]:
    """Return source-linked hits, with a single entry for each verified source ID."""
    if type(top_k) is not int or not 1 <= top_k <= CANDIDATE_LIMIT:
        raise ValueError("top_k must be an integer from 1 to 10")
    scores: dict[str, float] = {}
    sources: dict[str, dict] = {}
    for ranking in (lexical, semantic):
        if len(ranking) > CANDIDATE_LIMIT:
            raise ValueError("Unbounded retrieval candidate list")
        seen: set[str] = set()
        for rank, hit in enumerate(ranking, start=1):
            source_id = hit["source_id"]
            if source_id in seen:
                raise ValueError("Duplicate source in retrieval ranking")
            seen.add(source_id)
            if source_id in sources:
                if any(sources[source_id][field] != hit[field] for field in SOURCE_FIELDS):
                    raise ValueError("Conflicting source metadata across retrieval rankings")
            else:
                sources[source_id] = hit
            scores[source_id] = scores.get(source_id, 0.0) + 1.0 / (RRF_K + rank)
    ordered = sorted(scores, key=lambda source_id: (-scores[source_id], source_id))[:top_k]
    return [{**{field: sources[source_id][field] for field in SOURCE_FIELDS},
             "retrieval_method": "rrf_60", "score": scores[source_id]}
            for source_id in ordered]
