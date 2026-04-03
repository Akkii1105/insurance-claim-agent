"""Rule evaluation schemas — output of the deterministic Rule Engine (Step 6)."""

from typing import Optional

from pydantic import BaseModel, Field

from app.models.citation import Citation
from app.models.enums import RuleVerdict


class RuleResult(BaseModel):
    """The outcome of evaluating a single rule against a single bill line item.

    The Rule Engine produces one RuleResult per (rule, line_item) combination.
    The Decision Engine aggregates these to make the final claim decision.
    """

    rule_name: str = Field(
        ..., description="Machine-readable rule identifier (e.g., 'exclusion_check')"
    )
    rule_description: str = Field(
        ..., description="Human-readable explanation of what this rule checks"
    )
    item_id: int = Field(
        ..., description="ID of the BillLineItem this rule was evaluated against"
    )
    verdict: RuleVerdict = Field(
        ..., description="Whether the line item passed, failed, or was skipped"
    )
    reason: str = Field(
        ..., description="Plain-language explanation of the verdict"
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Policy clauses that support this verdict (required for FAIL)",
    )
    original_amount: float = Field(
        ..., ge=0, description="The line item's original billed amount"
    )
    approved_amount: Optional[float] = Field(
        default=None, ge=0,
        description="Amount approved after applying this rule (if reduced)",
    )

    @property
    def is_failure(self) -> bool:
        """Convenience check for downstream aggregation."""
        return self.verdict == RuleVerdict.FAIL

    @property
    def reduction(self) -> float:
        """How much this rule reduced the amount (0 if not applicable)."""
        if self.approved_amount is not None:
            return max(0.0, self.original_amount - self.approved_amount)
        return 0.0


class LineItemResult(BaseModel):
    """Aggregated result of ALL rules evaluated against a single line item.

    The Decision Engine builds one of these per line item, then aggregates
    them into the final ClaimDecision.
    """

    item_id: int = Field(
        ..., description="ID of the BillLineItem"
    )
    item_description: str = Field(
        ..., description="Original line item description"
    )
    original_amount: float = Field(
        ..., ge=0, description="Original billed amount"
    )
    approved_amount: float = Field(
        ..., ge=0, description="Final approved amount after all rules"
    )
    rule_results: list[RuleResult] = Field(
        default_factory=list, description="Results of every rule evaluated"
    )

    @property
    def is_fully_rejected(self) -> bool:
        return self.approved_amount == 0.0

    @property
    def is_reduced(self) -> bool:
        return 0 < self.approved_amount < self.original_amount

    @property
    def all_citations(self) -> list[Citation]:
        """Flatten all citations from failing rules for this line item."""
        return [
            c
            for r in self.rule_results
            if r.is_failure
            for c in r.citations
        ]
