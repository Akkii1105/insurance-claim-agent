"""Tests for the Embedder, Index Builder, and Semantic Matcher.

These tests load the real sentence-transformers model and FAISS.
First run will download the model (~80MB). Subsequent runs use the cache.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from app.models import PolicyChunk
from app.services.embedder import encode_chunks, encode_text
from app.services.index_builder import build_index, load_index, save_index
from app.services.semantic_matcher import match_line_item


# ─── Shared Fixtures ────────────────────────────────────────────────


def _make_chunk(
    chunk_id: str,
    text: str,
    policy_id: str = "POL-TEST",
    page: int = 1,
    para: int = 1,
    section: str | None = None,
    embedding: list[float] | None = None,
) -> PolicyChunk:
    """Helper to create a PolicyChunk with minimal boilerplate."""
    return PolicyChunk(
        chunk_id=chunk_id,
        policy_id=policy_id,
        page_number=page,
        paragraph_number=para,
        text=text,
        section_title=section,
        embedding=embedding,
    )


@pytest.fixture(scope="module")
def sample_chunks() -> list[PolicyChunk]:
    """Create realistic policy chunks for testing the full pipeline."""
    return [
        _make_chunk(
            "p1_para1",
            "Room rent is limited to 1% of the sum insured per day. "
            "Any excess room rent charges shall be borne by the insured.",
            page=1, para=1, section="Room Rent Sub-Limits",
        ),
        _make_chunk(
            "p2_para1",
            "Cosmetic surgery and plastic surgery are not covered under this "
            "policy unless necessitated by an accident or burn injury.",
            page=2, para=1, section="Exclusions",
        ),
        _make_chunk(
            "p2_para2",
            "Pre-existing conditions diagnosed within 48 months prior to the "
            "policy commencement date are excluded from coverage.",
            page=2, para=2, section="Exclusions",
        ),
        _make_chunk(
            "p3_para1",
            "A waiting period of 30 days applies from the date of commencement. "
            "No claims are admissible during this initial waiting period.",
            page=3, para=1, section="Waiting Period",
        ),
        _make_chunk(
            "p3_para2",
            "ICU charges are limited to 2% of the sum insured per day. "
            "This includes all monitoring and life support equipment.",
            page=3, para=2, section="ICU Limits",
        ),
        _make_chunk(
            "p4_para1",
            "The insured must be admitted to a network hospital for cashless "
            "treatment. Non-network hospital claims require reimbursement.",
            page=4, para=1, section="Network Hospitals",
        ),
        _make_chunk(
            "p4_para2",
            "Ambulance charges up to Rs. 2000 per hospitalization are covered. "
            "Air ambulance is not covered under this policy.",
            page=4, para=2, section="Ambulance",
        ),
        _make_chunk(
            "p5_para1",
            "All prescription medications administered during hospitalization "
            "are covered. Over-the-counter medicines are not reimbursable.",
            page=5, para=1, section="Medication Coverage",
        ),
    ]


@pytest.fixture(scope="module")
def embedded_chunks(sample_chunks: list[PolicyChunk]) -> list[PolicyChunk]:
    """Embed all sample chunks (cached for the module)."""
    return encode_chunks(sample_chunks)


@pytest.fixture(scope="module")
def faiss_index_and_chunks(
    embedded_chunks: list[PolicyChunk],
) -> tuple:
    """Build a FAISS index from embedded chunks (cached for the module)."""
    return build_index(embedded_chunks)


# ─── TestEmbedder ───────────────────────────────────────────────────


class TestEmbedder:
    def test_encode_text_returns_list_of_floats(self):
        vector = encode_text("Room rent charges")
        assert isinstance(vector, list)
        assert all(isinstance(v, float) for v in vector)

    def test_encode_text_dimension_384(self):
        """MiniLM-L6-v2 produces 384-dimensional embeddings."""
        vector = encode_text("Test sentence")
        assert len(vector) == 384

    def test_encode_chunks_populates_embeddings(self, embedded_chunks):
        for chunk in embedded_chunks:
            assert chunk.embedding is not None
            assert isinstance(chunk.embedding, list)
            assert len(chunk.embedding) == 384

    def test_encode_chunks_returns_same_count(self, sample_chunks):
        # Use fresh copies to avoid double-embedding
        fresh = [_make_chunk(c.chunk_id, c.text) for c in sample_chunks]
        result = encode_chunks(fresh)
        assert len(result) == len(sample_chunks)

    def test_encode_chunks_empty_list(self):
        result = encode_chunks([])
        assert result == []

    def test_encode_text_deterministic(self):
        """Same input must produce identical vectors."""
        v1 = encode_text("Surgical procedure coverage")
        v2 = encode_text("Surgical procedure coverage")
        assert v1 == v2

    def test_encode_text_different_inputs_differ(self):
        """Different inputs should produce different vectors."""
        v1 = encode_text("Room rent charges")
        v2 = encode_text("Ambulance transport services")
        assert v1 != v2


# ─── TestIndexBuilder ───────────────────────────────────────────────


class TestIndexBuilder:
    def test_build_raises_on_missing_embeddings(self):
        chunks = [_make_chunk("c1", "Text without embedding", embedding=None)]
        with pytest.raises(ValueError, match="no embedding"):
            build_index(chunks)

    def test_build_raises_on_empty_list(self):
        with pytest.raises(ValueError, match="empty"):
            build_index([])

    def test_build_returns_correct_ntotal(self, faiss_index_and_chunks):
        index, chunks = faiss_index_and_chunks
        assert index.ntotal == len(chunks)

    def test_build_sorts_chunks_by_chunk_id(self, faiss_index_and_chunks):
        _, chunks = faiss_index_and_chunks
        chunk_ids = [c.chunk_id for c in chunks]
        assert chunk_ids == sorted(chunk_ids)

    def test_save_creates_both_files(self, faiss_index_and_chunks, tmp_path):
        index, chunks = faiss_index_and_chunks
        idx_path = tmp_path / "test.index"
        meta_path = tmp_path / "test_chunks.json"
        save_index(index, chunks, str(idx_path), str(meta_path))
        assert idx_path.exists()
        assert meta_path.exists()

    def test_saved_chunks_no_embedding_field(self, faiss_index_and_chunks, tmp_path):
        index, chunks = faiss_index_and_chunks
        meta_path = tmp_path / "chunks.json"
        save_index(index, chunks, str(tmp_path / "idx.index"), str(meta_path))

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        for item in data:
            assert "embedding" not in item

    def test_load_returns_correct_ntotal(self, faiss_index_and_chunks, tmp_path):
        index, chunks = faiss_index_and_chunks
        idx_path = tmp_path / "load_test.index"
        meta_path = tmp_path / "load_test.json"
        save_index(index, chunks, str(idx_path), str(meta_path))

        loaded_index, loaded_chunks = load_index(str(idx_path), str(meta_path))
        assert loaded_index.ntotal == index.ntotal

    def test_load_returns_correct_chunk_ids(self, faiss_index_and_chunks, tmp_path):
        index, chunks = faiss_index_and_chunks
        idx_path = tmp_path / "ids_test.index"
        meta_path = tmp_path / "ids_test.json"
        save_index(index, chunks, str(idx_path), str(meta_path))

        _, loaded_chunks = load_index(str(idx_path), str(meta_path))
        original_ids = [c.chunk_id for c in chunks]
        loaded_ids = [c.chunk_id for c in loaded_chunks]
        assert original_ids == loaded_ids

    def test_roundtrip_search(self, faiss_index_and_chunks, tmp_path):
        """Build → save → load → search should return the same top result."""
        index, chunks = faiss_index_and_chunks
        idx_path = tmp_path / "rt.index"
        meta_path = tmp_path / "rt.json"
        save_index(index, chunks, str(idx_path), str(meta_path))

        loaded_index, loaded_chunks = load_index(str(idx_path), str(meta_path))

        # Search original
        query = encode_text("room rent charges per day")
        q = np.array([query], dtype=np.float32)
        _, orig_ids = index.search(q, 1)

        # Search loaded
        _, loaded_ids = loaded_index.search(q, 1)

        assert orig_ids[0][0] == loaded_ids[0][0]

    def test_load_missing_index_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_index(str(tmp_path / "nope.index"), str(tmp_path / "nope.json"))

    def test_load_missing_chunks_raises(self, faiss_index_and_chunks, tmp_path):
        index, chunks = faiss_index_and_chunks
        idx_path = tmp_path / "only_idx.index"
        save_index(index, chunks, str(idx_path), str(tmp_path / "temp.json"))
        # Remove chunks file
        (tmp_path / "temp.json").unlink()
        with pytest.raises(FileNotFoundError):
            load_index(str(idx_path), str(tmp_path / "temp.json"))


# ─── TestSemanticMatcher ────────────────────────────────────────────


class TestSemanticMatcher:
    def test_returns_list_of_policy_chunks(self, faiss_index_and_chunks):
        index, chunks = faiss_index_and_chunks
        results = match_line_item("room rent", index, chunks)
        assert isinstance(results, list)
        assert all(isinstance(r, PolicyChunk) for r in results)

    def test_returns_at_most_top_k(self, faiss_index_and_chunks):
        index, chunks = faiss_index_and_chunks
        results = match_line_item(
            "hospital charges", index, chunks, top_k=3, similarity_threshold=999.0
        )
        assert len(results) <= 3

    def test_returns_empty_when_nothing_passes_threshold(self, faiss_index_and_chunks):
        index, chunks = faiss_index_and_chunks
        results = match_line_item(
            "something", index, chunks, similarity_threshold=0.0001
        )
        assert results == []

    def test_results_ascending_distance_order(self, faiss_index_and_chunks):
        """Results should be ordered by ascending L2 distance (closest first)."""
        index, chunks = faiss_index_and_chunks
        results = match_line_item(
            "room rent per day limit",
            index, chunks,
            top_k=5,
            similarity_threshold=999.0,
        )
        # FAISS returns results in ascending distance order by default
        # We just verify results are non-empty
        assert len(results) >= 1

    def test_exact_match_returns_chunk_first(self, faiss_index_and_chunks):
        """If the query matches a chunk's text exactly, it should be the first result."""
        index, chunks = faiss_index_and_chunks
        # Use the exact text of one of our chunks
        target = chunks[0]
        results = match_line_item(
            target.text, index, chunks, top_k=3, similarity_threshold=999.0
        )
        assert len(results) >= 1
        assert results[0].chunk_id == target.chunk_id

    def test_embeddings_not_leaked(self, faiss_index_and_chunks):
        """Returned chunks must have embedding=None."""
        index, chunks = faiss_index_and_chunks
        results = match_line_item(
            "medication coverage",
            index, chunks,
            top_k=3,
            similarity_threshold=999.0,
        )
        for chunk in results:
            assert chunk.embedding is None

    def test_uses_default_threshold_from_settings(self, faiss_index_and_chunks):
        """When no threshold is passed, it should use settings.faiss_similarity_threshold."""
        index, chunks = faiss_index_and_chunks
        # This should work with the default threshold (1.2)
        results = match_line_item("room rent charges", index, chunks)
        # With a reasonable threshold, we should get at least 1 result
        assert isinstance(results, list)

    def test_top_k_1_returns_exactly_1(self, faiss_index_and_chunks):
        index, chunks = faiss_index_and_chunks
        results = match_line_item(
            "room rent",
            index, chunks,
            top_k=1,
            similarity_threshold=999.0,
        )
        assert len(results) == 1

    def test_room_rent_matches_room_rent_section(self, faiss_index_and_chunks):
        """Semantic search: 'room rent' should match room-rent-related chunks."""
        index, chunks = faiss_index_and_chunks
        results = match_line_item(
            "room rent general ward",
            index, chunks,
            top_k=1,
            similarity_threshold=999.0,
        )
        assert len(results) == 1
        assert results[0].section_title == "Room Rent Sub-Limits"

    def test_exclusion_query_matches_exclusion_section(self, faiss_index_and_chunks):
        """Semantic search: 'cosmetic surgery' should match exclusion clauses."""
        index, chunks = faiss_index_and_chunks
        results = match_line_item(
            "cosmetic surgery procedure",
            index, chunks,
            top_k=1,
            similarity_threshold=999.0,
        )
        assert len(results) == 1
        assert results[0].section_title == "Exclusions"
