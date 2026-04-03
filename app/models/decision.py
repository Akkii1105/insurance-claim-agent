"""Claim decision schema — the final output of the adjudication pipeline."""

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import ClaimStatus
from app.models.rule import LineItemResult


class ClaimDecision(BaseModel):
    """The final, auditable decision for an insurance claim.

    This is the top-level output of the entire pipeline:
        Bill PDF + Policy PDF → ... → ClaimDecision

    Every field is deterministic and traceable — no black-box LLM outputs.
    """

    claim_id: str = Field(
        ..., description="Unique identifier for this claim adjudication"
    )
    bill_id: str = Field(
        ..., description="ID of the bill that was evaluated"
    )
    policy_id: str = Field(
        ..., description="ID of the policy the bill was evaluated against"
    )
    status: ClaimStatus = Field(
        ..., description="Final claim outcome"
    )
    total_billed: float = Field(
        ..., ge=0, description="Total amount on the original bill"
    )
    total_approved: float = Field(
        ..., ge=0, description="Total amount approved after all rules"
    )
    total_rejected: float = Field(
        ..., ge=0, description="Total amount rejected (billed - approved)"
    )
    line_item_results: list[LineItemResult] = Field(
        default_factory=list,
        description="Per-line-item breakdown with rule results and citations",
    )
    summary: str = Field(
        default="",
        description="Human-readable summary of the decision",
    )
    rejection_reasons: list[str] = Field(
        default_factory=list,
        description="Consolidated list of distinct rejection reasons",
    )
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the claim was processed",
    )
    processing_time_ms: Optional[int] = Field(
        default=None, description="Total pipeline processing time in milliseconds"
    )

    @property
    def approval_rate(self) -> float:
        """What percentage of the bill was approved."""
        if self.total_billed == 0:
            return 0.0
        return round(self.total_approved / self.total_billed * 100, 2)

    @property
    def fully_approved(self) -> bool:
        return self.status == ClaimStatus.APPROVED

    @property
    def has_rejections(self) -> bool:
        return self.total_rejected > 0
