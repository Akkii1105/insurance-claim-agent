"""Decision Engine — orchestrates the full claim processing pipeline.

Combines the Rule Engine, Citation Engine, and summary generation into
a single process_claim() entry point that produces a ClaimDecision.

The decision is ALWAYS deterministic. The optional LLM summary path
(gated behind USE_LLM_SUMMARY=False) is purely for presentation and
never influences the approve/reject outcome.
"""

import logging
import time
from datetime import UTC, date, datetime
from typing import Optional

from app.config import settings
from app.models import (
    Bill,
    ClaimDecision,
    ClaimStatus,
    PolicyChunk,
    RuleVerdict,
)
from app.models.rule import LineItemResult, RuleResult
from app.services.citation_engine import attach_citations
from app.services.rule_engine import PolicyRuleConfig, run_rules

logger = logging.getLogger(__name__)


# ── Approved Amount Computation ─────────────────────────────────────


def compute_item_approved_amount(rule_results: list[RuleResult]) -> float:
    """Compute the final approved amount for a line item.

    The most restrictive rule wins: returns the minimum approved_amount
    across all non-SKIP rules.

    Args:
        rule_results: All RuleResults for this line item.

    Returns:
        The minimum approved_amount from non-SKIP rules,
        or original_amount if all rules are SKIP,
        or 0.0 if rule_results is empty.
    """
    if not rule_results:
        return 0.0

    non_skip = [r for r in rule_results if r.verdict != RuleVerdict.SKIP]
    if not non_skip:
        # All rules skipped — use the original item amount
        return rule_results[0].original_amount

    return min(
        r.approved_amount for r in non_skip
        if r.approved_amount is not None
    )


# ── Totals Computation ──────────────────────────────────────────────


def compute_totals(
    line_item_results: list[LineItemResult],
) -> tuple[float, float, float]:
    """Compute aggregate financial totals.

    Args:
        line_item_results: All line item results.

    Returns:
        Tuple of (total_billed, total_approved, total_rejected),
        all rounded to 2 decimal places.
    """
    total_billed = round(sum(item.original_amount for item in line_item_results), 2)
    total_approved = round(sum(item.approved_amount for item in line_item_results), 2)
    total_rejected = round(total_billed - total_approved, 2)
    return total_billed, total_approved, total_rejected


# ── Status Determination ────────────────────────────────────────────


_TOLERANCE = 0.01


def determine_status(total_billed: float, total_approved: float) -> ClaimStatus:
    """Determine the claim status from financial totals.

    Args:
        total_billed: Total amount billed.
        total_approved: Total amount approved.

    Returns:
        ClaimStatus.APPROVED, REJECTED, or PARTIALLY_APPROVED.
    """
    if total_approved >= total_billed - _TOLERANCE:
        return ClaimStatus.APPROVED
    if total_approved <= _TOLERANCE:
        return ClaimStatus.REJECTED
    return ClaimStatus.PARTIALLY_APPROVED


# ── Summary Generation ──────────────────────────────────────────────


def generate_summary(
    status: ClaimStatus,
    line_item_results: list[LineItemResult],
    total_billed: float,
    total_approved: float,
    bill: Bill,
) -> str:
    """Generate a human-readable claim summary.

    Uses a deterministic template by default.
    If USE_LLM_SUMMARY is True, attempts an LLM call for richer text,
    falling back silently to the deterministic template on any error.

    Args:
        status: The computed claim status.
        line_item_results: Per-item results.
        total_billed: Total billed amount.
        total_approved: Total approved amount.
        bill: The original bill for patient/hospital info.

    Returns:
        A summary string.
    """
    # Collect unique failure reasons (max 3)
    failed_reasons: list[str] = []
    seen: set[str] = set()
    for item in line_item_results:
        for rr in item.rule_results:
            if rr.verdict == RuleVerdict.FAIL and rr.reason not in seen:
                seen.add(rr.reason)
                failed_reasons.append(rr.reason)

    # Deterministic template
    patient = bill.patient_name or "Unknown Patient"
    hospital = bill.hospital_name or "Unknown Hospital"
    status_label = status.value.upper().replace("_", " ")

    if failed_reasons:
        reasons_text = "Rejection reasons: " + "; ".join(failed_reasons[:3])
    else:
        reasons_text = "All covered conditions satisfied."

    deterministic_summary = (
        f"Claim submitted by {patient} from {hospital} "
        f"for ₹{total_billed:,.2f} has been {status_label}. "
        f"Approved amount: ₹{total_approved:,.2f}. "
        f"{len(line_item_results)} line item(s) reviewed. "
        f"{reasons_text}"
    )

    # Optional LLM path
    if settings.use_llm_summary:
        try:
            return _generate_llm_summary(
                status_label, total_billed, total_approved,
                failed_reasons[:3], patient, hospital, len(line_item_results),
            )
        except Exception:
            logger.warning("LLM summary failed, using deterministic template.", exc_info=True)

    return deterministic_summary


def _generate_llm_summary(
    status_label: str,
    total_billed: float,
    total_approved: float,
    top_reasons: list[str],
    patient: str,
    hospital: str,
    item_count: int,
) -> str:
    """Call Anthropic API for a richer summary (optional, non-critical)."""
    import anthropic

    client = anthropic.Anthropic()

    reasons_str = "; ".join(top_reasons) if top_reasons else "None"
    user_msg = (
        f"Status: {status_label}\n"
        f"Patient: {patient}\n"
        f"Hospital: {hospital}\n"
        f"Total Billed: ₹{total_billed:,.2f}\n"
        f"Total Approved: ₹{total_approved:,.2f}\n"
        f"Items Reviewed: {item_count}\n"
        f"Top Rejection Reasons: {reasons_str}"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=(
            "You are an insurance claim processing assistant. "
            "Write a single clear paragraph summarizing the claim decision "
            "for the patient. Be factual and concise."
        ),
        messages=[{"role": "user", "content": user_msg}],
    )

    return response.content[0].text


# ── Rejection Reasons Aggregation ───────────────────────────────────


def _collect_rejection_reasons(
    line_item_results: list[LineItemResult],
) -> list[str]:
    """Collect unique rejection reasons across all items."""
    reasons: list[str] = []
    seen: set[str] = set()
    for item in line_item_results:
        for rr in item.rule_results:
            if rr.verdict == RuleVerdict.FAIL and rr.reason not in seen:
                seen.add(rr.reason)
                reasons.append(rr.reason)
    return reasons


# ════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════


def process_claim(
    claim_id: str,
    bill: Bill,
    meta: PolicyRuleConfig,
    matched_chunks_per_item: dict[int, list[PolicyChunk]],
    prior_claim_dates: list[date] | None = None,
    required_docs: list[str] | None = None,
    submitted_docs: list[str] | None = None,
) -> ClaimDecision:
    """Process an insurance claim end-to-end.

    This is the SINGLE PUBLIC ENTRY POINT for the entire claim
    processing pipeline. It orchestrates:
        1. Rule evaluation (12 deterministic rules per line item)
        2. Citation attachment (policy clause references for failures)
        3. Amount recomputation (most restrictive rule wins)
        4. Financial totals
        5. Status determination
        6. Summary generation

    The final decision is NEVER made by an LLM — it is fully
    deterministic and auditable.

    Args:
        claim_id: Unique identifier for this claim.
        bill: The parsed hospital bill.
        meta: Policy rule configuration.
        matched_chunks_per_item: Dict mapping item_id → matched PolicyChunks.
        prior_claim_dates: Previous claim admission dates (for duplicate check).
        required_docs: Required supporting documents.
        submitted_docs: Actually submitted documents.

    Returns:
        A fully populated ClaimDecision.
    """
    start_ms = time.monotonic_ns() // 1_000_000

    # Step 1: Run all 12 rules against every line item
    line_item_results = run_rules(
        bill, meta, matched_chunks_per_item,
        prior_claim_dates, required_docs, submitted_docs,
    )

    # Step 2: Attach citations to FAIL rules missing them
    line_item_results = attach_citations(line_item_results, matched_chunks_per_item)

    # Step 3: Recompute approved amounts (most restrictive rule wins)
    for item_result in line_item_results:
        item_result.approved_amount = round(
            compute_item_approved_amount(item_result.rule_results), 2
        )

    # Step 4: Compute financial totals
    total_billed, total_approved, total_rejected = compute_totals(line_item_results)

    # Step 5: Determine claim status
    status = determine_status(total_billed, total_approved)

    # Step 6: Generate summary
    summary = generate_summary(
        status, line_item_results, total_billed, total_approved, bill,
    )

    # Collect rejection reasons
    rejection_reasons = _collect_rejection_reasons(line_item_results)

    elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms

    return ClaimDecision(
        claim_id=claim_id,
        bill_id=bill.bill_id,
        policy_id=meta.policy_id,
        status=status,
        total_billed=round(total_billed, 2),
        total_approved=round(total_approved, 2),
        total_rejected=round(total_rejected, 2),
        line_item_results=line_item_results,
        summary=summary,
        rejection_reasons=rejection_reasons,
        processed_at=datetime.now(UTC),
        processing_time_ms=elapsed_ms,
    )
