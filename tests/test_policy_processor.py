"""Tests for the Policy Processor pipeline.

Uses fpdf2 to generate synthetic policy PDFs at test time. Tests cover:
    - Heading detection heuristics
    - Paragraph splitting
    - Short paragraph filtering
    - Section title assignment and propagation
    - Chunk ID format
    - Metadata loading and validation
    - Full pipeline (process_policy)
    - Schema validation of output

At least 20 tests as required.
"""

import json
from pathlib import Path

import pytest

from app.models import PolicyChunk, PolicyMeta
from app.services.policy_processor import (
    extract_chunks_from_page,
    is_heading,
    load_policy_metadata,
    process_policy,
    split_into_paragraphs,
)


# ─── Fixtures ───────────────────────────────────────────────────────


def _create_policy_pdf(path: str, pages: list[list[str]]) -> None:
    """Create a synthetic text-based policy PDF with multiple pages.

    Args:
        path: Output file path.
        pages: List of pages, where each page is a list of lines.
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_font("Helvetica", "", 10)

    for page_lines in pages:
        pdf.add_page()
        for line in page_lines:
            pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")

    pdf.output(path)


def _create_metadata_json(path: str, data: dict) -> None:
    """Write a policy metadata JSON file."""
    Path(path).write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def sample_policy_pdf(tmp_path: Path) -> Path:
    """Create a multi-page synthetic policy PDF."""
    pages = [
        # Page 1: Introduction
        [
            "STAR HEALTH INSURANCE POLICY",
            "",
            "Policy Number: SH-2025-001",
            "Insured: Rajesh Kumar",
            "",
            "GENERAL PROVISIONS",
            "",
            "This policy covers hospitalization expenses incurred by the insured",
            "person for medically necessary treatment in a hospital or nursing home.",
            "The coverage is subject to the terms, conditions, and exclusions",
            "stated in this document. All claims must be filed within 30 days of",
            "discharge from the hospital.",
            "",
            "The sum insured for this policy is Rs. 5,00,000 per policy year.",
            "Coverage begins from the date of commencement and continues for",
            "twelve consecutive months unless cancelled or terminated earlier.",
        ],
        # Page 2: Room Rent and Exclusions
        [
            "ROOM RENT SUB-LIMITS",
            "",
            "The maximum room rent payable per day is limited to 1% of the sum",
            "insured amount. Any excess room rent charges shall be borne by the",
            "insured. ICU charges are limited to 2% of the sum insured per day.",
            "This sub-limit applies to all categories of rooms including deluxe",
            "and suite rooms in network hospitals.",
            "",
            "EXCLUSIONS",
            "",
            "The following treatments and conditions are not covered under this",
            "policy and any claims arising from them shall be rejected:",
            "",
            "1. Cosmetic surgery or plastic surgery unless necessitated by an",
            "accident or burn injury requiring reconstruction.",
            "",
            "2. Dental treatment unless requiring hospitalization for more than",
            "24 hours due to emergency conditions.",
            "",
            "3. Pre-existing conditions diagnosed within 48 months prior to the",
            "policy commencement date are excluded from coverage.",
        ],
        # Page 3: Waiting Period
        [
            "WAITING PERIOD:",
            "",
            "A waiting period of 30 days applies from the date of commencement of",
            "this policy. No claims shall be admissible during this initial waiting",
            "period except for claims arising out of accidental injuries.",
            "",
            "Certain specific diseases and treatments are subject to a waiting",
            "period of 2 years from the date of first policy issuance. These",
            "include but are not limited to: hernia, cataract, joint replacement,",
            "and kidney stones. Claims for these conditions during the waiting",
            "period shall be rejected with reference to this clause.",
        ],
    ]

    pdf_path = tmp_path / "policy.pdf"
    _create_policy_pdf(str(pdf_path), pages)
    return pdf_path


@pytest.fixture
def sample_metadata_json(tmp_path: Path) -> Path:
    """Create a sample policy metadata JSON file."""
    meta_path = tmp_path / "policy_metadata.json"
    _create_metadata_json(str(meta_path), {
        "policy_id": "POL-001",
        "policy_name": "Star Health Gold",
        "insurer": "Star Health Insurance",
    })
    return meta_path


# ─── Heading Detection ──────────────────────────────────────────────


class TestIsHeading:
    def test_all_caps_is_heading(self):
        assert is_heading("EXCLUSIONS") is True

    def test_all_caps_with_spaces_is_heading(self):
        assert is_heading("ROOM RENT SUB-LIMITS") is True

    def test_mixed_case_not_heading(self):
        assert is_heading("This is a normal paragraph.") is False

    def test_colon_ending_is_heading(self):
        assert is_heading("Waiting Period:") is True

    def test_short_line_followed_by_blank_is_heading(self):
        assert is_heading("General Provisions", next_line="") is True

    def test_short_line_followed_by_text_not_heading(self):
        assert is_heading("General Provisions", next_line="Some content here") is False

    def test_very_short_line_not_heading(self):
        """Lines shorter than 4 chars should not be headings (avoids 'OR', 'IV')."""
        assert is_heading("OR") is False
        assert is_heading("IV") is False

    def test_empty_line_not_heading(self):
        assert is_heading("") is False
        assert is_heading("   ") is False

    def test_all_caps_with_numbers(self):
        """ALL CAPS with digits should still count."""
        assert is_heading("SECTION 4.2 EXCLUSIONS") is True

    def test_long_all_caps_is_heading(self):
        assert is_heading("PRE-EXISTING CONDITIONS AND WAITING PERIOD CLAUSE") is True


# ─── Paragraph Splitting ───────────────────────────────────────────


class TestSplitIntoParagraphs:
    def test_splits_on_double_newline(self):
        text = "First paragraph.\n\nSecond paragraph."
        paras = split_into_paragraphs(text)
        assert len(paras) == 2
        assert paras[0] == "First paragraph."
        assert paras[1] == "Second paragraph."

    def test_collapses_internal_newlines(self):
        text = "Line one\nline two\nline three."
        paras = split_into_paragraphs(text)
        assert len(paras) == 1
        assert paras[0] == "Line one line two line three."

    def test_removes_empty_paragraphs(self):
        text = "First.\n\n\n\nSecond."
        paras = split_into_paragraphs(text)
        assert len(paras) == 2

    def test_handles_windows_line_endings(self):
        text = "First paragraph.\r\n\r\nSecond paragraph."
        paras = split_into_paragraphs(text)
        assert len(paras) == 2

    def test_strips_whitespace(self):
        text = "  spaced paragraph  \n\n  another one  "
        paras = split_into_paragraphs(text)
        assert paras[0] == "spaced paragraph"
        assert paras[1] == "another one"

    def test_empty_input(self):
        paras = split_into_paragraphs("")
        assert paras == []


# ─── Chunk Extraction from Page ─────────────────────────────────────


class TestExtractChunksFromPage:
    def test_chunk_ids_format(self):
        text = (
            "COVERAGE DETAILS\n\n"
            "This policy covers hospitalization expenses incurred by the insured "
            "person for medically necessary treatment.\n\n"
            "All claims must be filed within 30 days of discharge from the hospital "
            "and must include original documents."
        )
        chunks, _ = extract_chunks_from_page(text, page_number=3, policy_id="POL-001")
        for chunk in chunks:
            assert chunk.chunk_id.startswith("p3_para")
            assert chunk.policy_id == "POL-001"
            assert chunk.page_number == 3

    def test_paragraph_numbering_is_sequential(self):
        text = (
            "DETAILS\n\n"
            "First substantial paragraph with enough characters to pass the minimum length filter.\n\n"
            "Second substantial paragraph also with enough characters to pass the minimum filter."
        )
        chunks, _ = extract_chunks_from_page(text, page_number=1, policy_id="P1")
        assert len(chunks) >= 2
        assert chunks[0].paragraph_number == 1
        assert chunks[1].paragraph_number == 2

    def test_short_paragraphs_discarded(self):
        text = (
            "Short.\n\n"
            "Also short line here.\n\n"
            "This is a long enough paragraph that should definitely pass the minimum "
            "character length filter of forty characters."
        )
        chunks, _ = extract_chunks_from_page(text, page_number=1, policy_id="P1")
        # Only the long paragraph should survive
        assert len(chunks) == 1
        assert "long enough" in chunks[0].text

    def test_heading_sets_section_title(self):
        text = (
            "EXCLUSIONS\n\n"
            "Cosmetic surgery and plastic surgery are not covered under this policy "
            "unless necessitated by an accident or burn injury."
        )
        chunks, section = extract_chunks_from_page(
            text, page_number=5, policy_id="P1"
        )
        assert len(chunks) == 1
        assert chunks[0].section_title == "EXCLUSIONS"
        assert section == "EXCLUSIONS"

    def test_section_title_carried_from_previous_page(self):
        text = (
            "Pre-existing conditions diagnosed within 48 months prior to the "
            "policy commencement date are excluded from coverage in this plan."
        )
        chunks, _ = extract_chunks_from_page(
            text, page_number=6, policy_id="P1", current_section="EXCLUSIONS"
        )
        assert len(chunks) == 1
        assert chunks[0].section_title == "EXCLUSIONS"

    def test_multiple_headings_on_one_page(self):
        text = (
            "ROOM RENT\n\n"
            "Room rent is limited to 1% of the sum insured per day and any excess charges "
            "shall be borne by the insured person.\n\n"
            "EXCLUSIONS\n\n"
            "Cosmetic surgery, dental treatment, and pre-existing conditions "
            "are not covered under this insurance policy document."
        )
        chunks, section = extract_chunks_from_page(
            text, page_number=2, policy_id="P1"
        )
        assert len(chunks) == 2
        assert chunks[0].section_title == "ROOM RENT"
        assert chunks[1].section_title == "EXCLUSIONS"
        assert section == "EXCLUSIONS"

    def test_heading_not_emitted_as_chunk(self):
        text = (
            "WAITING PERIOD\n\n"
            "A waiting period of 30 days applies from the date of commencement of "
            "this insurance policy for all new enrollments."
        )
        chunks, _ = extract_chunks_from_page(text, page_number=1, policy_id="P1")
        # "WAITING PERIOD" should NOT appear as a chunk
        for chunk in chunks:
            assert chunk.text != "WAITING PERIOD"

    def test_empty_page_returns_no_chunks(self):
        chunks, section = extract_chunks_from_page("", page_number=1, policy_id="P1")
        assert chunks == []
        assert section is None


# ─── Metadata Loading ──────────────────────────────────────────────


class TestLoadPolicyMetadata:
    def test_valid_metadata(self, sample_metadata_json: Path):
        meta = load_policy_metadata(sample_metadata_json, total_pages=10, total_chunks=45)
        assert isinstance(meta, PolicyMeta)
        assert meta.policy_id == "POL-001"
        assert meta.policy_name == "Star Health Gold"
        assert meta.insurer == "Star Health Insurance"
        assert meta.total_pages == 10
        assert meta.total_chunks == 45

    def test_source_file_passed_through(self, sample_metadata_json: Path):
        meta = load_policy_metadata(
            sample_metadata_json, total_pages=1, total_chunks=0, source_file="test.pdf"
        )
        assert meta.source_file == "test.pdf"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_policy_metadata(tmp_path / "missing.json", total_pages=1, total_chunks=0)

    def test_invalid_json_raises(self, tmp_path: Path):
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("not valid json{{{", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_policy_metadata(bad_path, total_pages=1, total_chunks=0)

    def test_missing_policy_id_raises(self, tmp_path: Path):
        no_id_path = tmp_path / "no_id.json"
        no_id_path.write_text('{"policy_name": "Test"}', encoding="utf-8")
        with pytest.raises(ValueError, match="policy_id"):
            load_policy_metadata(no_id_path, total_pages=1, total_chunks=0)

    def test_minimal_metadata(self, tmp_path: Path):
        """Only policy_id is required; other fields are optional."""
        minimal_path = tmp_path / "minimal.json"
        minimal_path.write_text('{"policy_id": "MIN-001"}', encoding="utf-8")
        meta = load_policy_metadata(minimal_path, total_pages=1, total_chunks=0)
        assert meta.policy_id == "MIN-001"
        assert meta.policy_name is None
        assert meta.insurer is None


# ─── End-to-End Pipeline ───────────────────────────────────────────


class TestProcessPolicy:
    def test_returns_correct_types(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        chunks, meta = process_policy(sample_policy_pdf, sample_metadata_json)
        assert isinstance(chunks, list)
        assert all(isinstance(c, PolicyChunk) for c in chunks)
        assert isinstance(meta, PolicyMeta)

    def test_chunks_have_correct_policy_id(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        chunks, meta = process_policy(sample_policy_pdf, sample_metadata_json)
        assert meta.policy_id == "POL-001"
        for chunk in chunks:
            assert chunk.policy_id == "POL-001"

    def test_produces_chunks(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        chunks, meta = process_policy(sample_policy_pdf, sample_metadata_json)
        assert len(chunks) > 0
        assert meta.total_chunks == len(chunks)

    def test_page_numbers_valid(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        chunks, meta = process_policy(sample_policy_pdf, sample_metadata_json)
        for chunk in chunks:
            assert 1 <= chunk.page_number <= meta.total_pages

    def test_embeddings_are_none(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        """Embeddings should NOT be computed in Step 4."""
        chunks, _ = process_policy(sample_policy_pdf, sample_metadata_json)
        for chunk in chunks:
            assert chunk.embedding is None

    def test_chunk_text_is_nonempty(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        chunks, _ = process_policy(sample_policy_pdf, sample_metadata_json)
        for chunk in chunks:
            assert len(chunk.text) >= _MIN_PARAGRAPH_LENGTH

    def test_meta_total_pages_matches_pdf(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        chunks, meta = process_policy(sample_policy_pdf, sample_metadata_json)
        assert meta.total_pages == 3  # We created a 3-page PDF

    def test_missing_pdf_raises(self, sample_metadata_json: Path, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            process_policy(tmp_path / "nope.pdf", sample_metadata_json)

    def test_missing_metadata_raises(self, sample_policy_pdf: Path, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            process_policy(sample_policy_pdf, tmp_path / "nope.json")

    def test_json_serializable(
        self, sample_policy_pdf: Path, sample_metadata_json: Path
    ):
        chunks, meta = process_policy(sample_policy_pdf, sample_metadata_json)
        # All chunks should serialize cleanly
        for chunk in chunks:
            data = chunk.model_dump()
            assert "embedding" not in data  # excluded
            assert isinstance(data["chunk_id"], str)
        # Meta should serialize cleanly
        meta_data = meta.model_dump()
        assert meta_data["policy_id"] == "POL-001"


# ─── Import guard for _MIN_PARAGRAPH_LENGTH ─────────────────────────
from app.services.policy_processor import _MIN_PARAGRAPH_LENGTH  # noqa: E402
