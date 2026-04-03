"""Embedding service — wraps sentence-transformers for chunk and query encoding.

Loads the model ONCE at module level as a singleton. All downstream modules
should import encode_chunks / encode_text rather than loading their own model.
"""

import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.models import PolicyChunk

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ── Module-level singleton ───────────────────────────────────────────
# Lazy-loaded on first call to avoid import-time GPU/model overhead
# when running tests that don't need embeddings.
_model: "SentenceTransformer | None" = None


def _get_model() -> "SentenceTransformer":
    """Return the singleton SentenceTransformer model, loading it on first use."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", settings.embedding_model)
        _model = SentenceTransformer(settings.embedding_model)
        logger.info("Embedding model loaded (dim=%d)", _model.get_sentence_embedding_dimension())
    return _model


# ── Public API ──────────────────────────────────────────────────────


def encode_text(text: str) -> list[float]:
    """Embed a single string and return as a list of floats.

    Used at query time to encode a bill line-item description before
    searching the FAISS index.

    Args:
        text: The string to encode.

    Returns:
        Embedding vector as list[float].
    """
    model = _get_model()
    vector = model.encode(text, convert_to_numpy=True)
    return vector.tolist()


def encode_chunks(chunks: list[PolicyChunk]) -> list[PolicyChunk]:
    """Batch-embed all chunk texts and populate their .embedding field.

    Encodes all texts in a single model call for efficiency.

    Args:
        chunks: List of PolicyChunk objects with text populated.

    Returns:
        The same list of PolicyChunks, now with .embedding populated.
    """
    if not chunks:
        logger.info("No chunks to embed — returning empty list.")
        return chunks

    model = _get_model()
    texts = [chunk.text for chunk in chunks]

    logger.info("Embedding %d chunks...", len(texts))
    vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    for chunk, vector in zip(chunks, vectors):
        chunk.embedding = vector.tolist()

    logger.info("Successfully embedded %d chunks.", len(chunks))
    return chunks
