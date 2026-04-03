"""Citation schema — exact policy references for every rule result."""

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """An exact reference to a specific clause in the policy document.

    Every rule failure MUST include at least one Citation so the decision
    is fully auditable and explainable.

    Example:
        Citation(
            policy_id="POL-001",
            page_number=12,
            paragraph_number=3,
            section_title="Exclusions",
            clause_text="Pre-existing conditions diagnosed within 48 months ...",
            relevance_score=0.87,
        )
    """

    policy_id: str = Field(
        ..., description="Which policy document this citation refers to"
    )
    chunk_id: str = Field(
        ..., description="ID of the PolicyChunk this citation was derived from"
    )
    page_number: int = Field(
        ..., ge=1, description="1-based page number in the policy PDF"
    )
    paragraph_number: int = Field(
        ..., ge=1, description="1-based paragraph number within the page"
    )
    section_title: str | None = Field(
        default=None, description="Policy section heading (e.g., 'Exclusions')"
    )
    clause_text: str = Field(
        ..., min_length=1,
        description="The exact text of the policy clause being cited",
    )
    relevance_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Semantic similarity score between the bill item and this clause",
    )

    @property
    def location_label(self) -> str:
        """Human-readable location for display in reports."""
        base = f"Page {self.page_number}, Paragraph {self.paragraph_number}"
        if self.section_title:
            return f"{base} ({self.section_title})"
        return base
