"""Small local CPU embeddings; kept separate from the hash-vector smoke test."""

import math
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


class LocalEncoder:
    def __init__(self, cache_dir: Path):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(
            model_name=MODEL_NAME, cache_dir=str(cache_dir), threads=2,
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = [vector.tolist() for vector in self.model.embed(
            texts, batch_size=8, parallel=None,
        )]
        if len(vectors) != len(texts) or any(
            len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise ValueError("Embedding output has an unexpected size or non-finite value")
        return vectors
