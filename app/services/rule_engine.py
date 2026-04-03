"""Deterministic Rule Engine — applies auditable rules to each bill line item.

Zero LLM calls. Every approve/reject decision is based on explicit logic
with exact policy citations where applicable.

The run_rules() function is the only public entry point. Individual rule
functions are importable for unit testing.
"""

from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from app.models import (
    Bill,
    BillItemCategory,
    BillLineItem,
    Citation,
    PolicyChunk,
    RuleVerdict,
)
from app.models.rule import LineItemResult, RuleResult


# ── Policy Rule Config ──────────────────────────────────────────────
# The existing PolicyMeta model stores PDF-level metadata (pages, chunks).
# The rule engine needs policy-level business rules. This config carries
# those fields as a standalone Pydantic model, loaded from policy metadata
# JSON or an API call.


class PolicyRuleConfig(BaseModel):
    """Business-rule configuration extracted from the insurance policy.

    This complements PolicyMeta (which holds PDF metadata) by carrying
    the actual rule parameters needed for claim adjudication.
    """

    policy_id: str
    sum_insured: float = Field(default=500000.0, ge=0)
    waiting_period_days: int = Field(default=30, ge=0)
    policy_start_date: date = Field(default_factory=lambda: date(2025, 1, 1))
    room_rent_limit_per_day: float = Field(default=5000.0, ge=0)
    icu_limit_per_day: float = Field(default=10000.0, ge=0)
    co_payment_percent: float = Field(default=0.0, ge=0, le=100)
    empanelled_hospitals: list[str] = Field(default_factory=list)
    exclusions_list: list[str] = Field(default_factory=list)
    covered_procedures: list[str] = Field(default_factory=list)
    pre_existing_conditions: list[str] = Field(default_factory=list)
    day_care_procedures: list[str] = Field(default_factory=list)
    consumables_excluded: bool = Field(default=False)


# ── Helper: Citation Builder ────────────────────────────────────────


def _best_citation(
    chunks: list[PolicyChunk], relevance_score: float = 0.9
) -> list[Citation]:
    """Build a citation from the best-matching chunk.

    Takes the first chunk (already sorted closest-first by the semantic
    matcher) and returns a single-element list with a Citation.

    Args:
        chunks: Matched policy chunks, sorted by relevance.
        relevance_score: Score to assign to the citation.

    Returns:
        List with one Citation, or empty list if no chunks.
    """
    if not chunks:
        return []

    chunk = chunks[0]
    return [
        Citation(
            policy_id=chunk.policy_id,
            chunk_id=chunk.chunk_id,
            page_number=chunk.page_number,
            paragraph_number=chunk.paragraph_number,
            section_title=chunk.section_title,
            clause_text=chunk.text,
            relevance_score=relevance_score,
        )
    ]


# ── Helper: Build a RuleResult ──────────────────────────────────────


def _result(
    rule_name: str,
    rule_description: str,
    item: BillLineItem,
    verdict: RuleVerdict,
    reason: str,
    approved_amount: float,
    citations: list[Citation] | None = None,
) -> RuleResult:
    """Construct a RuleResult with all fields populated."""
    return RuleResult(
        rule_name=rule_name,
        rule_description=rule_description,
        item_id=item.item_id,
        verdict=verdict,
        reason=reason,
        original_amount=item.amount,
        approved_amount=round(approved_amount, 2),
        citations=citations or [],
    )


# ════════════════════════════════════════════════════════════════════
# THE 12 RULES
# ════════════════════════════════════════════════════════════════════


def rule_R01(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R01 — Exclusion Check: reject items matching policy exclusions."""
    desc_lower = item.description.lower()
    for term in meta.exclusions_list:
        if term.lower() in desc_lower:
            return _result(
                rule_name="R01_exclusion_check",
                rule_description="Check if procedure is excluded by policy",
                item=item,
                verdict=RuleVerdict.FAIL,
                reason=f"Procedure '{item.description}' matches policy exclusion: '{term}'",
                approved_amount=0.0,
                citations=_best_citation(matched_chunks),
            )
    return _result(
        rule_name="R01_exclusion_check",
        rule_description="Check if procedure is excluded by policy",
        item=item,
        verdict=RuleVerdict.PASS,
        reason="Item is not in the exclusions list.",
        approved_amount=item.amount,
    )


def rule_R02(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R02 — Waiting Period Check: reject if admission is within waiting period."""
    coverage_start = meta.policy_start_date + timedelta(days=meta.waiting_period_days)
    if bill.admission_date and bill.admission_date < coverage_start:
        return _result(
            rule_name="R02_waiting_period",
            rule_description="Check if claim falls within waiting period",
            item=item,
            verdict=RuleVerdict.FAIL,
            reason=(
                f"Admission date {bill.admission_date} is within the "
                f"{meta.waiting_period_days}-day waiting period. "
                f"Coverage begins {coverage_start}."
            ),
            approved_amount=0.0,
        )
    return _result(
        rule_name="R02_waiting_period",
        rule_description="Check if claim falls within waiting period",
        item=item,
        verdict=RuleVerdict.PASS,
        reason="Admission is after the waiting period.",
        approved_amount=item.amount,
    )


def rule_R03(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R03 — Room Rent / ICU Sub-limit: cap daily rates per policy limits."""
    name = "R03_room_icu_sublimit"
    desc = "Check room rent / ICU daily rate against policy sub-limits"

    if item.category not in (BillItemCategory.ROOM_RENT, BillItemCategory.ICU):
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.SKIP, reason="Not applicable to this category.",
            approved_amount=item.amount,
        )

    los = bill.length_of_stay or 1  # Fallback to 1 day
    daily_rate = item.amount / max(los, 1)

    limit = (
        meta.room_rent_limit_per_day
        if item.category == BillItemCategory.ROOM_RENT
        else meta.icu_limit_per_day
    )

    if daily_rate > limit:
        approved = round(limit * los, 2)
        category_label = "Room Rent" if item.category == BillItemCategory.ROOM_RENT else "ICU"
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.FAIL,
            reason=(
                f"Daily {category_label} rate ₹{daily_rate:.2f} exceeds "
                f"policy limit of ₹{limit:.2f}/day. "
                f"Approved for {los} days at limit rate."
            ),
            approved_amount=approved,
            citations=_best_citation(matched_chunks),
        )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.PASS,
        reason="Daily rate is within policy sub-limit.",
        approved_amount=item.amount,
    )


def rule_R04(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R04 — Pre-existing Condition Check: reject if diagnosis matches."""
    name = "R04_pre_existing_condition"
    desc = "Check if diagnosis is a pre-existing condition"

    if not bill.diagnosis:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="No diagnosis provided — pre-existing check skipped.",
            approved_amount=item.amount,
        )

    diag_lower = bill.diagnosis.lower()
    for term in meta.pre_existing_conditions:
        if term.lower() in diag_lower:
            return _result(
                rule_name=name, rule_description=desc, item=item,
                verdict=RuleVerdict.FAIL,
                reason=(
                    f"Diagnosis '{bill.diagnosis}' matches pre-existing "
                    f"condition: '{term}'"
                ),
                approved_amount=0.0,
                citations=_best_citation(matched_chunks),
            )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.PASS,
        reason="Diagnosis is not a pre-existing condition.",
        approved_amount=item.amount,
    )


def rule_R05(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R05 — Claim Cap (Sum Insured): proportionally reduce if over limit."""
    name = "R05_claim_cap"
    desc = "Check if total claim exceeds sum insured"

    if meta.sum_insured <= 0:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.SKIP, reason="No sum insured defined.",
            approved_amount=item.amount,
        )

    if bill.total_amount <= meta.sum_insured:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="Total claim is within sum insured.",
            approved_amount=item.amount,
        )

    ratio = meta.sum_insured / bill.total_amount
    approved = round(item.amount * ratio, 2)
    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.FAIL,
        reason=(
            f"Total claim ₹{bill.total_amount:.2f} exceeds sum insured "
            f"₹{meta.sum_insured:.2f}. Item approved proportionally "
            f"({ratio * 100:.1f}%)."
        ),
        approved_amount=approved,
    )


def rule_R06(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R06 — Covered Procedure Check: reject unlisted surgical procedures."""
    name = "R06_covered_procedure"
    desc = "Check if surgical procedure is in the covered list"

    if item.category != BillItemCategory.SURGERY:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.SKIP, reason="Not a surgical procedure.",
            approved_amount=item.amount,
        )

    if not meta.covered_procedures:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="All surgical procedures are covered.",
            approved_amount=item.amount,
        )

    desc_lower = item.description.lower()
    for proc in meta.covered_procedures:
        if proc.lower() in desc_lower:
            return _result(
                rule_name=name, rule_description=desc, item=item,
                verdict=RuleVerdict.PASS,
                reason=f"Procedure matches covered item: '{proc}'.",
                approved_amount=item.amount,
            )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.FAIL,
        reason=f"Procedure '{item.description}' is not in the list of covered surgical procedures.",
        approved_amount=0.0,
        citations=_best_citation(matched_chunks),
    )


def rule_R07(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R07 — Day Care Procedure Check: reject if day-care billed as inpatient."""
    name = "R07_day_care_check"
    desc = "Check if day-care procedure is incorrectly billed as inpatient"

    if not meta.day_care_procedures:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="No day-care procedure list defined.",
            approved_amount=item.amount,
        )

    desc_lower = item.description.lower()
    los = bill.length_of_stay or 1

    for proc in meta.day_care_procedures:
        if proc.lower() in desc_lower and los > 1:
            return _result(
                rule_name=name, rule_description=desc, item=item,
                verdict=RuleVerdict.FAIL,
                reason=(
                    f"'{item.description}' is a day-care procedure but was "
                    f"billed as a {los}-day inpatient stay."
                ),
                approved_amount=0.0,
                citations=_best_citation(matched_chunks),
            )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.PASS,
        reason="Not a day-care procedure or stay is 1 day.",
        approved_amount=item.amount,
    )


def rule_R08(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R08 — Consumables Exclusion: reject consumables if policy excludes them."""
    name = "R08_consumables_exclusion"
    desc = "Check if consumables are excluded by policy"

    if item.category != BillItemCategory.CONSUMABLES:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.SKIP, reason="Not a consumable item.",
            approved_amount=item.amount,
        )

    if not meta.consumables_excluded:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="Consumables are covered under this policy.",
            approved_amount=item.amount,
        )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.FAIL,
        reason="Consumables and disposables are excluded under this policy.",
        approved_amount=0.0,
        citations=_best_citation(matched_chunks),
    )


def rule_R09(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R09 — Co-payment: reduce approved amount by co-pay percentage. Always PASS."""
    name = "R09_co_payment"
    desc = "Apply co-payment percentage"

    if meta.co_payment_percent <= 0:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="No co-payment applicable.",
            approved_amount=item.amount,
        )

    approved = round(item.amount * (1 - meta.co_payment_percent / 100), 2)
    patient_share = round(item.amount - approved, 2)
    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.PASS,
        reason=(
            f"Co-payment of {meta.co_payment_percent}% applied. "
            f"Patient share: ₹{patient_share:.2f}."
        ),
        approved_amount=approved,
    )


def rule_R10(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
) -> RuleResult:
    """R10 — Network Hospital Check: reject if hospital is not empanelled."""
    name = "R10_network_hospital"
    desc = "Check if hospital is in the empanelled network"

    if not meta.empanelled_hospitals:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="Open network — all hospitals accepted.",
            approved_amount=item.amount,
        )

    hospital_lower = (bill.hospital_name or "").lower()
    for emp in meta.empanelled_hospitals:
        if emp.lower() in hospital_lower:
            return _result(
                rule_name=name, rule_description=desc, item=item,
                verdict=RuleVerdict.PASS,
                reason=f"Hospital matches empanelled network: '{emp}'.",
                approved_amount=item.amount,
            )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.FAIL,
        reason=f"Hospital '{bill.hospital_name}' is not in the list of empanelled network hospitals.",
        approved_amount=0.0,
    )


def rule_R11(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
    prior_claim_dates: list[date] | None = None,
) -> RuleResult:
    """R11 — Duplicate Claim Detection: reject if same admission date was already claimed."""
    name = "R11_duplicate_claim"
    desc = "Check for duplicate claim submissions"

    if not prior_claim_dates:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="No prior claims to check against.",
            approved_amount=item.amount,
        )

    if bill.admission_date in prior_claim_dates:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.FAIL,
            reason=f"A claim for admission date {bill.admission_date} has already been submitted.",
            approved_amount=0.0,
        )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.PASS,
        reason="No duplicate claims found.",
        approved_amount=item.amount,
    )


def rule_R12(
    item: BillLineItem,
    matched_chunks: list[PolicyChunk],
    meta: PolicyRuleConfig,
    bill: Bill,
    required_docs: list[str] | None = None,
    submitted_docs: list[str] | None = None,
) -> RuleResult:
    """R12 — Document Completeness: reject if required documents are missing."""
    name = "R12_document_completeness"
    desc = "Check for required supporting documents"

    if not required_docs:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.PASS,
            reason="No required documents specified.",
            approved_amount=item.amount,
        )

    submitted_lower = [s.lower() for s in (submitted_docs or [])]
    missing = [d for d in required_docs if d.lower() not in submitted_lower]

    if missing:
        return _result(
            rule_name=name, rule_description=desc, item=item,
            verdict=RuleVerdict.FAIL,
            reason=f"Missing required documents: {', '.join(missing)}",
            approved_amount=0.0,
        )

    return _result(
        rule_name=name, rule_description=desc, item=item,
        verdict=RuleVerdict.PASS,
        reason="All required documents submitted.",
        approved_amount=item.amount,
    )


# ════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ════════════════════════════════════════════════════════════════════


# Ordered list of all rules for the orchestrator
_ALL_RULES = [
    rule_R01, rule_R02, rule_R03, rule_R04, rule_R05, rule_R06,
    rule_R07, rule_R08, rule_R09, rule_R10, rule_R11, rule_R12,
]


def run_rules(
    bill: Bill,
    meta: PolicyRuleConfig,
    matched_chunks_per_item: dict[int, list[PolicyChunk]],
    prior_claim_dates: list[date] | None = None,
    required_docs: list[str] | None = None,
    submitted_docs: list[str] | None = None,
) -> list[LineItemResult]:
    """Run all 12 deterministic rules against every bill line item.

    This is the ONLY public entry point for the rule engine.

    Args:
        bill: The parsed hospital bill.
        meta: Policy rule configuration.
        matched_chunks_per_item: Dict mapping item_id → matched PolicyChunks.
        prior_claim_dates: Previous claim admission dates (for R11).
        required_docs: Required supporting documents (for R12).
        submitted_docs: Actually submitted documents (for R12).

    Returns:
        List of LineItemResult, one per bill line item.
    """
    results: list[LineItemResult] = []

    for item in bill.line_items:
        chunks = matched_chunks_per_item.get(item.item_id, [])

        # Run all 12 rules
        rule_results: list[RuleResult] = []
        for rule_fn in _ALL_RULES:
            if rule_fn is rule_R11:
                rr = rule_fn(item, chunks, meta, bill, prior_claim_dates)
            elif rule_fn is rule_R12:
                rr = rule_fn(item, chunks, meta, bill, required_docs, submitted_docs)
            else:
                rr = rule_fn(item, chunks, meta, bill)
            rule_results.append(rr)

        # Compute approved amount: minimum across non-SKIP results
        non_skip = [r for r in rule_results if r.verdict != RuleVerdict.SKIP]
        if non_skip:
            approved_amount = min(
                r.approved_amount for r in non_skip
                if r.approved_amount is not None
            )
        else:
            approved_amount = item.amount

        results.append(
            LineItemResult(
                item_id=item.item_id,
                item_description=item.description,
                original_amount=item.amount,
                approved_amount=round(approved_amount, 2),
                rule_results=rule_results,
            )
        )

    return results
