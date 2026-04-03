"""FAISS index builder — build, save, and load vector indexes for policy chunks.

Handles the persistence layer between the Embedder and the Semantic Matcher.
"""

import json
import logging
from pathlib import Path

import faiss
import numpy as np

from app.models import PolicyChunk

logger = logging.getLogger(__name__)


def build_index(
    chunks: list[PolicyChunk],
) -> tuple[faiss.IndexFlatL2, list[PolicyChunk]]:
    """Build a FAISS IndexFlatL2 from embedded policy chunks.

    Chunks are sorted by chunk_id before indexing so FAISS row order
    is deterministic and reproducible across runs.

    Args:
        chunks: PolicyChunk objects with .embedding populated.

    Returns:
        Tuple of (FAISS index, sorted chunks).
        The sorted chunks order defines the row → chunk mapping.

    Raises:
        ValueError: If any chunk has embedding=None or the list is empty.
    """
    if not chunks:
        raise ValueError("Cannot build index from an empty chunk list.")

    # Validate all embeddings are present
    missing = [c.chunk_id for c in chunks if c.embedding is None]
    if missing:
        raise ValueError(
            f"{len(missing)} chunk(s) have no embedding. "
            f"First few: {missing[:5]}. Run encode_chunks() first."
        )

    # Sort by chunk_id for deterministic ordering
    sorted_chunks = sorted(chunks, key=lambda c: c.chunk_id)

    # Build numpy array (float32 required by FAISS)
    dim = len(sorted_chunks[0].embedding)  # type: ignore[arg-type]
    vectors = np.array(
        [c.embedding for c in sorted_chunks], dtype=np.float32
    )
    assert vectors.shape == (len(sorted_chunks), dim)

    # Build the index
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

    logger.info(
        "Built FAISS index: %d vectors, dimension=%d", index.ntotal, dim
    )
    return index, sorted_chunks


def save_index(
    index: faiss.IndexFlatL2,
    chunks: list[PolicyChunk],
    index_path: str | Path,
    chunks_path: str | Path,
) -> None:
    """Persist a FAISS index and its chunk metadata to disk.

    Chunk metadata is saved as JSON WITHOUT the embedding field
    (FAISS holds the vectors; no need to duplicate them).

    Args:
        index: The FAISS index to save.
        chunks: The ordered chunks corresponding to FAISS rows.
        index_path: File path for the FAISS index (e.g. "policy.index").
        chunks_path: File path for the chunk metadata JSON.
    """
    index_path = Path(index_path)
    chunks_path = Path(chunks_path)

    # Ensure parent directories exist
    index_path.parent.mkdir(parents=True, exist_ok=True)
    chunks_path.parent.mkdir(parents=True, exist_ok=True)

    # Save FAISS index
    faiss.write_index(index, str(index_path))

    # Save chunk metadata (embedding excluded by Pydantic's exclude=True)
    chunks_data = [chunk.model_dump() for chunk in chunks]
    chunks_path.write_text(
        json.dumps(chunks_data, indent=2, default=str),
        encoding="utf-8",
    )

    logger.info(
        "Saved FAISS index (%d vectors) to %s and chunks to %s",
        index.ntotal,
        index_path,
        chunks_path,
    )


def load_index(
    index_path: str | Path,
    chunks_path: str | Path,
) -> tuple[faiss.IndexFlatL2, list[PolicyChunk]]:
    """Load a FAISS index and its chunk metadata from disk.

    Loaded chunks will have embedding=None (vectors live in FAISS).

    Args:
        index_path: Path to the saved FAISS index file.
        chunks_path: Path to the saved chunk metadata JSON.

    Returns:
        Tuple of (FAISS index, list of PolicyChunk).

    Raises:
        FileNotFoundError: If either file doesn't exist.
    """
    index_path = Path(index_path)
    chunks_path = Path(chunks_path)

    if not index_path.exists():
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks metadata not found: {chunks_path}")

    # Load FAISS index
    index = faiss.read_index(str(index_path))

    # Load chunk metadata
    raw = json.loads(chunks_path.read_text(encoding="utf-8"))
    chunks = [PolicyChunk(**item) for item in raw]

    if index.ntotal != len(chunks):
        raise ValueError(
            f"Index/chunks mismatch: FAISS has {index.ntotal} vectors "
            f"but metadata has {len(chunks)} chunks."
        )

    logger.info(
        "Loaded FAISS index (%d vectors) from %s", index.ntotal, index_path
    )
    return index, chunks
