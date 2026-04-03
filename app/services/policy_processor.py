"""Policy Processor — converts insurance policy PDFs into indexed chunks.

Pipeline:
    PDF file → detect type → extract text page-by-page → split paragraphs
    → detect headings → assign section titles → produce PolicyChunk list

This module is the second ingestion layer. Its output feeds:
    - Embedding pipeline (Step 5) for FAISS indexing
    - Semantic Matcher for retrieving relevant clauses per bill line item
    - Citation Engine for exact page/paragraph references
"""

import json
import re
from pathlib import Path
from typing import Optional

from app.models import PolicyChunk, PolicyMeta
from app.utils.pdf_utils import extract_text


# ── Configuration Constants ──────────────────────────────────────────

# Paragraphs shorter than this are discarded as noise (headers, page
# numbers, footers, or fragments that have no policy value).
_MIN_PARAGRAPH_LENGTH = 40


# ── Heading Detection ───────────────────────────────────────────────


def is_heading(line: str, next_line: Optional[str] = None) -> bool:
    """Determine whether a line of text is a section heading.

    A line is classified as a heading if ANY of these hold:
      1. It is ALL UPPERCASE (and at least 4 chars to avoid matching "OR", "IV")
      2. It ends with a colon (e.g. "Exclusions:")
      3. It is shorter than 80 chars AND followed by a blank line

    Args:
        line: The text line to test.
        next_line: The line immediately following (None if last line).

    Returns:
        True if the line looks like a section heading.
    """
    stripped = line.strip()
    if not stripped or len(stripped) < 4:
        return False

    # Rule 1: ALL CAPS (allow digits, punctuation, spaces)
    alpha_chars = [c for c in stripped if c.isalpha()]
    if alpha_chars and all(c.isupper() for c in alpha_chars):
        return True

    # Rule 2: Ends with a colon
    if stripped.endswith(":"):
        return True

    # Rule 3: Short line followed by a blank line
    if len(stripped) < 80 and next_line is not None and next_line.strip() == "":
        return True

    return False


# ── Paragraph Splitting ─────────────────────────────────────────────


def split_into_paragraphs(page_text: str) -> list[str]:
    """Split a page's text into paragraphs.

    Uses double-newline as paragraph boundary. Consecutive single-newlines
    within a paragraph are collapsed into spaces (they are usually soft
    line wraps from PDF extraction).

    Args:
        page_text: Raw text for a single page.

    Returns:
        List of cleaned paragraph strings (empty strings removed).
    """
    # Normalize line endings
    text = page_text.replace("\r\n", "\n").replace("\r", "\n")

    # Split on double-newline (paragraph boundary)
    raw_paragraphs = re.split(r"\n\s*\n", text)

    paragraphs: list[str] = []
    for para in raw_paragraphs:
        # Collapse internal newlines into spaces
        cleaned = re.sub(r"\s+", " ", para).strip()
        if cleaned:
            paragraphs.append(cleaned)

    return paragraphs


# ── Section Title Assignment ────────────────────────────────────────


def extract_chunks_from_page(
    page_text: str,
    page_number: int,
    policy_id: str,
    current_section: Optional[str] = None,
) -> tuple[list[PolicyChunk], Optional[str]]:
    """Extract PolicyChunk objects from a single page's text.

    Splits into paragraphs, detects headings, assigns section titles,
    and filters out short fragments.

    Args:
        page_text: Raw extracted text for this page.
        page_number: 1-based page number.
        policy_id: ID of the parent policy document.
        current_section: Section title carried over from previous page.

    Returns:
        Tuple of (list of PolicyChunks from this page, last active section title).
    """
    lines = page_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraphs = split_into_paragraphs(page_text)

    # Detect headings in the raw lines to find section boundaries.
    # We track headings by scanning lines, then assign them to paragraphs.
    section_title = current_section

    # Build a list of headings found on this page and their rough position
    heading_positions: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        if is_heading(line, next_line):
            heading_positions.append((i, line.strip().rstrip(":")))

    # For each paragraph, find the last heading that appeared before it
    # We do this by checking if the paragraph text starts after a heading
    chunks: list[PolicyChunk] = []
    para_index = 0

    for para in paragraphs:
        # Check if this paragraph IS a heading (update section, don't emit chunk)
        para_stripped = para.strip()

        # Match this paragraph against known headings
        is_para_heading = False
        for _, heading_text in heading_positions:
            # A paragraph might contain the heading text (headings get merged
            # into paragraph text when they share a double-newline block)
            cleaned_heading = heading_text.rstrip(":")
            if (
                para_stripped == cleaned_heading
                or para_stripped == heading_text
                or para_stripped.upper() == cleaned_heading.upper()
            ):
                section_title = cleaned_heading
                is_para_heading = True
                break

        # If the paragraph is short enough to be just a heading line, and it
        # matches heading heuristics, treat it as a section title update
        if not is_para_heading and len(para_stripped) < 80:
            # Check if this short paragraph is itself a heading
            dummy_next = ""  # Paragraphs are already split, assume blank follows
            if is_heading(para_stripped, dummy_next):
                section_title = para_stripped.rstrip(":")
                is_para_heading = True

        if is_para_heading:
            continue

        # Filter: skip short paragraphs (noise)
        if len(para_stripped) < _MIN_PARAGRAPH_LENGTH:
            continue

        # Emit a chunk
        para_index += 1
        chunk = PolicyChunk(
            chunk_id=f"p{page_number}_para{para_index}",
            policy_id=policy_id,
            page_number=page_number,
            paragraph_number=para_index,
            text=para_stripped,
            section_title=section_title,
            embedding=None,
        )
        chunks.append(chunk)

    return chunks, section_title


# ── Metadata Loading ────────────────────────────────────────────────


def load_policy_metadata(
    metadata_path: str | Path,
    total_pages: int,
    total_chunks: int,
    source_file: Optional[str] = None,
) -> PolicyMeta:
    """Load and validate policy metadata from a JSON file.

    The JSON file should contain at minimum:
        {"policy_id": "...", "policy_name": "...", "insurer": "..."}

    total_pages and total_chunks are filled in by the processor
    (not expected in the JSON).

    Args:
        metadata_path: Path to the policy_metadata.json file.
        total_pages: Total pages extracted from the PDF.
        total_chunks: Total chunks produced.
        source_file: Original PDF filename.

    Returns:
        A validated PolicyMeta model.

    Raises:
        FileNotFoundError: If the metadata file doesn't exist.
        ValueError: If the JSON is invalid or missing required fields.
    """
    metadata_path = Path(metadata_path)
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in metadata file: {e}") from e

    if "policy_id" not in raw:
        raise ValueError("Metadata JSON must contain a 'policy_id' field.")

    return PolicyMeta(
        policy_id=raw["policy_id"],
        policy_name=raw.get("policy_name"),
        insurer=raw.get("insurer"),
        total_pages=total_pages,
        total_chunks=total_chunks,
        source_file=source_file,
    )


# ── Main Entry Point ────────────────────────────────────────────────


def process_policy(
    pdf_path: str | Path,
    metadata_path: str | Path,
) -> tuple[list[PolicyChunk], PolicyMeta]:
    """Process an insurance policy PDF end-to-end.

    This is the single public entry point for the Policy Processor.

    Pipeline:
        1. Detect PDF type (text-based vs scanned)
        2. Extract text page by page
        3. Split each page into paragraphs
        4. Detect section headings and assign to chunks
        5. Filter short fragments
        6. Load and validate metadata
        7. Return (chunks, metadata)

    Args:
        pdf_path: Path to the insurance policy PDF.
        metadata_path: Path to the policy_metadata.json file.

    Returns:
        Tuple of (list of PolicyChunk objects, PolicyMeta).

    Raises:
        FileNotFoundError: If PDF or metadata file doesn't exist.
        ValueError: If PDF has no pages or metadata is invalid.
    """
    pdf_path = Path(pdf_path)

    # Step 1 + 2: Detect type and extract text page by page
    pages, pdf_type = extract_text(pdf_path)

    if not pages:
        raise ValueError(f"PDF has no pages: {pdf_path}")

    # Step 3-5: Process each page into chunks
    all_chunks: list[PolicyChunk] = []
    current_section: Optional[str] = None

    # We need the policy_id from metadata before building chunks.
    # Read it early.
    metadata_path = Path(metadata_path)
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

    raw_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    policy_id = raw_meta.get("policy_id", "UNKNOWN")

    for page_idx, page_text in enumerate(pages):
        page_number = page_idx + 1  # 1-based

        if not page_text.strip():
            continue  # Skip blank pages

        page_chunks, current_section = extract_chunks_from_page(
            page_text=page_text,
            page_number=page_number,
            policy_id=policy_id,
            current_section=current_section,
        )
        all_chunks.extend(page_chunks)

    # Step 6: Load and validate metadata
    meta = load_policy_metadata(
        metadata_path=metadata_path,
        total_pages=len(pages),
        total_chunks=len(all_chunks),
        source_file=pdf_path.name,
    )

    return all_chunks, meta
