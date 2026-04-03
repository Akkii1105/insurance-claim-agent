"""Policy-related schemas — output of the Policy Processor (Step 4)."""

from typing import Optional

from pydantic import BaseModel, Field


class PolicyChunk(BaseModel):
    """A single chunk of text from an insurance policy document.

    The Policy Processor splits each policy PDF into page-aware, paragraph-level
    chunks.  Each chunk is embedded and stored in a FAISS index for semantic
    retrieval.  The chunk metadata (page, paragraph) is carried through the
    entire pipeline so the Citation Engine can produce exact references.
    """

    chunk_id: str = Field(
        ..., description="Unique identifier for this chunk (e.g., 'policy_001_p3_para2')"
    )
    policy_id: str = Field(
        ..., description="Identifier of the parent policy document"
    )
    page_number: int = Field(
        ..., ge=1, description="1-based page number where this chunk appears"
    )
    paragraph_number: int = Field(
        ..., ge=1, description="1-based paragraph number within the page"
    )
    text: str = Field(
        ..., min_length=1, description="The actual text content of this chunk"
    )
    section_title: Optional[str] = Field(
        default=None,
        description="Section or heading this chunk falls under (e.g., 'Exclusions', 'Room Rent')",
    )
    embedding: Optional[list[float]] = Field(
        default=None,
        description="Embedding vector (populated during indexing, excluded from JSON output)",
        exclude=True,  # Don't serialize the full vector in API responses
    )

    @property
    def location_label(self) -> str:
        """Human-readable location string for citations."""
        return f"Page {self.page_number}, Paragraph {self.paragraph_number}"


class PolicyMeta(BaseModel):
    """Top-level metadata for a parsed insurance policy document.

    Lightweight summary — the actual content lives in PolicyChunk objects.
    """

    policy_id: str = Field(
        ..., description="Unique identifier for this policy"
    )
    policy_name: Optional[str] = Field(
        default=None, description="Name or title of the policy document"
    )
    insurer: Optional[str] = Field(
        default=None, description="Insurance company name"
    )
    total_pages: int = Field(
        ..., ge=1, description="Total number of pages in the policy PDF"
    )
    total_chunks: int = Field(
        ..., ge=0, description="Number of chunks extracted from this policy"
    )
    source_file: Optional[str] = Field(
        default=None, description="Original PDF filename"
    )
