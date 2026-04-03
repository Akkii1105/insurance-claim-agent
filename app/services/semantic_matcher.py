"""Semantic Matcher — retrieves relevant policy clauses for each bill line item.

Uses FAISS vector search to find the top-k policy chunks most similar
to a bill line item description. Results are filtered by L2 distance
threshold and returned in ascending distance order (closest first).
"""

import logging

import faiss
import numpy as np

from app.config import settings
from app.models import PolicyChunk
from app.services.embedder import encode_text

logger = logging.getLogger(__name__)


def match_line_item(
    description: str,
    faiss_index: faiss.IndexFlatL2,
    chunks: list[PolicyChunk],
    top_k: int = 5,
    similarity_threshold: float | None = None,
) -> list[PolicyChunk]:
    """Find the most relevant policy chunks for a bill line-item description.

    Args:
        description: Bill line-item description text to match.
        faiss_index: Pre-built FAISS index of policy chunk embeddings.
        chunks: Ordered list of PolicyChunks matching FAISS row indices.
        top_k: Maximum number of results to return.
        similarity_threshold: Maximum L2 distance for a match to be included.
            Defaults to settings.faiss_similarity_threshold if None.

    Returns:
        List of matching PolicyChunk objects in ascending L2 distance order
        (closest first). Each returned chunk has embedding=None.
        Returns empty list if no chunks pass the threshold.
    """
    if similarity_threshold is None:
        similarity_threshold = settings.faiss_similarity_threshold

    # Embed the query
    query_vector = encode_text(description)
    query_array = np.array([query_vector], dtype=np.float32)

    # Search FAISS
    distances, indices = faiss_index.search(query_array, top_k)

    # distances and indices are 2D arrays of shape (1, top_k)
    distances = distances[0]
    indices = indices[0]

    # Filter by threshold and collect results
    results: list[PolicyChunk] = []
    for dist, idx in zip(distances, indices):
        # FAISS returns -1 for empty slots when index has fewer than top_k entries
        if idx == -1:
            continue

        if dist > similarity_threshold:
            continue

        # Create a copy with embedding set to None
        # (don't leak vectors into downstream modules)
        chunk = chunks[idx].model_copy()
        chunk.embedding = None

        results.append(chunk)

    logger.info(
        "Matched '%s' → %d results (top_k=%d, threshold=%.2f)",
        description[:50],
        len(results),
        top_k,
        similarity_threshold,
    )

    return results
