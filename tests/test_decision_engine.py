"""Tests for the Decision Engine — compute, determine, summarize, process.

22+ tests organized by function, including full process_claim integration.
"""

from datetime import date, timezone

import pytest

from app.models import (
    Bill,
    BillItemCategory,
    BillLineItem,
    ClaimDecision,
    ClaimStatus,
    PolicyChunk,
    RuleVerdict,
)
from app.models.rule import LineItemResult, RuleResult
from app.services.decision_engine import (
    compute_item_approved_amount,
    compute_totals,
    determine_status,
    generate_summary,
    process_claim,
)
from app.services.rule_engine import PolicyRuleConfig


# ─── Helpers ────────────────────────────────────────────────────────


def _rule(
    verdict: RuleVerdict = RuleVerdict.PASS,
    amount: float = 50000.0,
    approved: float | None = None,
    reason: str = "Test reason",
) -> RuleResult:
    return RuleResult(
        rule_name="test_rule",
        rule_description="test",
        item_id=1,
        verdict=verdict,
        reason=reason,
        original_amount=amount,
        approved_amount=approved if approved is not None else amount,
    )


def _item_result(
    amount: float = 50000.0,
    approved: float = 50000.0,
) -> LineItemResult:
    return LineItemResult(
        item_id=1,
        item_description="Test item",
        original_amount=amount,
        approved_amount=approved,
        rule_results=[],
    )


def _make_item(
    category: BillItemCategory = BillItemCategory.SURGERY,
    amount: float = 50000.0,
    description: str = "Appendectomy surgery",
    item_id: int = 1,
) -> BillLineItem:
    return BillLineItem(
        item_id=item_id, description=description,
        category=category, amount=amount,
    )


def _make_bill(
    items: list[BillLineItem] | None = None,
    hospital: str = "Apollo Hospital Delhi",
    diagnosis: str = "Acute Appendicitis",
    admission: str = "2025-08-01",
    discharge: str = "2025-08-05",
    total_amount: float | None = None,
) -> Bill:
    items = items or [_make_item()]
    total = total_amount if total_amount is not None else sum(i.amount for i in items)
    return Bill(
        bill_id="BILL-TEST001",
        patient_name="Rajesh Kumar",
        hospital_name=hospital,
        admission_date=date.fromisoformat(admission),
        discharge_date=date.fromisoformat(discharge),
        diagnosis=diagnosis,
        line_items=items,
        total_amount=total,
    )


def _make_meta(**overrides) -> PolicyRuleConfig:
    defaults = dict(
        policy_id="POL-TEST-001",
        sum_insured=500000.0,
        waiting_period_days=30,
        policy_start_date=date(2025, 1, 1),
        room_rent_limit_per_day=5000.0,
        icu_limit_per_day=10000.0,
        co_payment_percent=0.0,
        empanelled_hospitals=[],
        exclusions_list=[],
        covered_procedures=[],
        pre_existing_conditions=[],
        day_care_procedures=[],
        consumables_excluded=False,
    )
    defaults.update(overrides)
    return PolicyRuleConfig(**defaults)


def _make_chunk(
    page: int = 1,
    para: int = 1,
    section: str = "General",
    text: str = "Policy clause for testing.",
) -> PolicyChunk:
    return PolicyChunk(
        chunk_id=f"p{page}_para{para}",
        policy_id="POL-TEST-001",
        page_number=page,
        paragraph_number=para,
        text=text,
        section_title=section,
    )


# ─── TestComputeItemApprovedAmount ─────────────────────────────────


class TestComputeItemApprovedAmount:
    def test_all_pass_returns_original(self):
        rules = [_rule(RuleVerdict.PASS, amount=50000, approved=50000)]
        assert compute_item_approved_amount(rules) == 50000.0

    def test_one_fail_reduces(self):
        rules = [
            _rule(RuleVerdict.PASS, amount=50000, approved=50000),
            _rule(RuleVerdict.FAIL, amount=50000, approved=20000),
        ]
        assert compute_item_approved_amount(rules) == 20000.0

    def test_multiple_fails_returns_minimum(self):
        rules = [
            _rule(RuleVerdict.FAIL, amount=50000, approved=30000),
            _rule(RuleVerdict.FAIL, amount=50000, approved=10000),
            _rule(RuleVerdict.PASS, amount=50000, approved=50000),
        ]
        assert compute_item_approved_amount(rules) == 10000.0

    def test_all_skip_returns_original(self):
        rules = [
            _rule(RuleVerdict.SKIP, amount=50000, approved=50000),
            _rule(RuleVerdict.SKIP, amount=50000, approved=50000),
        ]
        assert compute_item_approved_amount(rules) == 50000.0

    def test_empty_returns_zero(self):
        assert compute_item_approved_amount([]) == 0.0


# ─── TestComputeTotals ─────────────────────────────────────────────


class TestComputeTotals:
    def test_all_approved(self):
        items = [_item_result(amount=100, approved=100)]
        billed, approved, rejected = compute_totals(items)
        assert billed == 100
        assert approved == 100
        assert rejected == 0

    def test_all_rejected(self):
        items = [_item_result(amount=100, approved=0)]
        billed, approved, rejected = compute_totals(items)
        assert billed == 100
        assert approved == 0
        assert rejected == 100

    def test_partial(self):
        items = [
            _item_result(amount=100, approved=60),
            _item_result(amount=200, approved=200),
        ]
        billed, approved, rejected = compute_totals(items)
        assert billed == 300
        assert approved == 260
        assert rejected == 40


# ─── TestDetermineStatus ───────────────────────────────────────────


class TestDetermineStatus:
    def test_fully_approved(self):
        assert determine_status(100000, 100000) == ClaimStatus.APPROVED

    def test_fully_rejected(self):
        assert determine_status(100000, 0) == ClaimStatus.REJECTED

    def test_partial(self):
        assert determine_status(100000, 50000) == ClaimStatus.PARTIALLY_APPROVED

    def test_tolerance_approved(self):
        # 0.005 less than billed should still be APPROVED (within tolerance)
        assert determine_status(100000, 99999.995) == ClaimStatus.APPROVED


# ─── TestGenerateSummary ───────────────────────────────────────────


class TestGenerateSummary:
    def test_includes_patient_and_hospital(self):
        bill = _make_bill()
        summary = generate_summary(
            ClaimStatus.APPROVED, [], 100000, 100000, bill,
        )
        assert "Rajesh Kumar" in summary
        assert "Apollo Hospital Delhi" in summary

    def test_includes_amounts(self):
        bill = _make_bill()
        summary = generate_summary(
            ClaimStatus.APPROVED, [], 150000, 120000, bill,
        )
        assert "1,50,000.00" in summary or "150,000.00" in summary
        assert "1,20,000.00" in summary or "120,000.00" in summary

    def test_rejection_reasons_appear(self):
        fail_rule = _rule(RuleVerdict.FAIL, reason="Exclusion matched: cosmetic")
        item = LineItemResult(
            item_id=1, item_description="Surgery",
            original_amount=50000, approved_amount=0,
            rule_results=[fail_rule],
        )
        bill = _make_bill()
        summary = generate_summary(
            ClaimStatus.REJECTED, [item], 50000, 0, bill,
        )
        assert "cosmetic" in summary.lower()

    def test_no_failures_says_all_satisfied(self):
        pass_rule = _rule(RuleVerdict.PASS)
        item = LineItemResult(
            item_id=1, item_description="Surgery",
            original_amount=50000, approved_amount=50000,
            rule_results=[pass_rule],
        )
        bill = _make_bill()
        summary = generate_summary(
            ClaimStatus.APPROVED, [item], 50000, 50000, bill,
        )
        assert "All covered conditions satisfied." in summary


# ─── TestProcessClaim ──────────────────────────────────────────────


class TestProcessClaim:
    def test_returns_claim_decision(self):
        bill = _make_bill()
        meta = _make_meta()
        result = process_claim("CLM-001", bill, meta, {})
        assert isinstance(result, ClaimDecision)

    def test_claim_id_preserved(self):
        bill = _make_bill()
        meta = _make_meta()
        result = process_claim("CLM-SPECIAL-42", bill, meta, {})
        assert result.claim_id == "CLM-SPECIAL-42"

    def test_approved_claim(self):
        """Clean claim with no triggers → APPROVED."""
        item = _make_item(amount=50000)
        bill = _make_bill(items=[item], total_amount=50000)
        meta = _make_meta()
        result = process_claim("CLM-A", bill, meta, {})
        assert result.status == ClaimStatus.APPROVED
        assert result.total_approved == result.total_billed

    def test_rejected_claim(self):
        """Excluded procedure → REJECTED."""
        item = _make_item(description="Cosmetic liposuction", amount=80000)
        bill = _make_bill(items=[item], total_amount=80000)
        meta = _make_meta(exclusions_list=["cosmetic"])
        result = process_claim("CLM-R", bill, meta, {})
        assert result.status == ClaimStatus.REJECTED
        assert result.total_approved == 0

    def test_partial_claim(self):
        """Room rent over limit → partial approval."""
        item = _make_item(
            category=BillItemCategory.ROOM_RENT,
            amount=40000,
            description="Room rent general ward",
        )
        bill = _make_bill(items=[item], total_amount=40000)
        meta = _make_meta(room_rent_limit_per_day=5000)
        # 4-day stay → daily rate 10000 > limit 5000
        # approved = 5000 * 4 = 20000
        result = process_claim("CLM-P", bill, meta, {})
        assert result.status == ClaimStatus.PARTIALLY_APPROVED
        assert result.total_approved < result.total_billed
        assert result.total_approved > 0

    def test_rejected_claim_has_citations(self):
        """Rejected claim with matched chunks should have citations."""
        item = _make_item(description="Cosmetic surgery", amount=80000)
        bill = _make_bill(items=[item], total_amount=80000)
        meta = _make_meta(exclusions_list=["cosmetic"])
        chunk = _make_chunk(section="Exclusions", text="Cosmetic procedures excluded.")
        result = process_claim("CLM-C", bill, meta, {1: [chunk]})

        # Find the exclusion failure
        has_citation = False
        for lr in result.line_item_results:
            for rr in lr.rule_results:
                if rr.verdict == RuleVerdict.FAIL and rr.citations:
                    has_citation = True
        assert has_citation

    def test_processed_at_is_timezone_aware(self):
        bill = _make_bill()
        meta = _make_meta()
        result = process_claim("CLM-TZ", bill, meta, {})
        assert result.processed_at.tzinfo is not None

    def test_rejection_reasons_populated(self):
        """Rejected claim should have rejection_reasons list filled."""
        item = _make_item(description="Dental cleaning", amount=30000)
        bill = _make_bill(items=[item], total_amount=30000)
        meta = _make_meta(exclusions_list=["dental"])
        result = process_claim("CLM-RR", bill, meta, {})
        assert len(result.rejection_reasons) > 0

    def test_processing_time_recorded(self):
        bill = _make_bill()
        meta = _make_meta()
        result = process_claim("CLM-TIME", bill, meta, {})
        assert result.processing_time_ms is not None
        assert result.processing_time_ms >= 0
