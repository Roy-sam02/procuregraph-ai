"""Tiny deterministic lexical vectorizer for local Qdrant wiring only."""

import hashlib
import math
import re
from collections import Counter

DIMENSIONS = 128
MODEL_ID = "token-hash-128-v1"
TOKENS = re.compile(r"[a-z]+|\d+(?:\.\d+)?")


def embed(text: str) -> list[float]:
    tokens = Counter(TOKENS.findall(text.lower()))
    if not tokens:
        raise ValueError("No searchable words in text")
    values = [0.0] * DIMENSIONS
    for token, frequency in tokens.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        direction = 1.0 if digest[4] & 1 else -1.0
        values[index] += direction * (1.0 + math.log(frequency))
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ValueError("Token hash collision produced an empty vector")
    return [value / norm for value in values]
