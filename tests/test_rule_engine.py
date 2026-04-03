"""Tests for the Deterministic Rule Engine — 12 rules + orchestrator.

At least 40 tests organized by rule with fixtures for constructing
test objects with minimal boilerplate.
"""

from datetime import date

import pytest

from app.models import (
    Bill,
    BillItemCategory,
    BillLineItem,
    PolicyChunk,
    RuleVerdict,
)
from app.models.rule import LineItemResult, RuleResult
from app.services.rule_engine import (
    PolicyRuleConfig,
    _best_citation,
    rule_R01,
    rule_R02,
    rule_R03,
    rule_R04,
    rule_R05,
    rule_R06,
    rule_R07,
    rule_R08,
    rule_R09,
    rule_R10,
    rule_R11,
    rule_R12,
    run_rules,
)


# ─── Fixture Helpers ────────────────────────────────────────────────


def make_item(
    category: BillItemCategory = BillItemCategory.SURGERY,
    amount: float = 50000.0,
    description: str = "Appendectomy surgery",
    item_id: int = 1,
) -> BillLineItem:
    return BillLineItem(
        item_id=item_id,
        description=description,
        category=category,
        amount=amount,
    )


def make_bill(
    items: list[BillLineItem] | None = None,
    hospital: str = "Apollo Hospital Delhi",
    diagnosis: str = "Acute Appendicitis",
    admission: str = "2025-08-01",
    discharge: str = "2025-08-05",
    total_amount: float | None = None,
) -> Bill:
    items = items or [make_item()]
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


def make_meta(**overrides) -> PolicyRuleConfig:
    """Build a PolicyRuleConfig with safe defaults, accepting keyword overrides."""
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


def make_chunk(
    page: int = 1,
    para: int = 1,
    section: str = "General",
    text: str = "Policy clause text for testing purposes.",
) -> PolicyChunk:
    return PolicyChunk(
        chunk_id=f"p{page}_para{para}",
        policy_id="POL-TEST-001",
        page_number=page,
        paragraph_number=para,
        text=text,
        section_title=section,
    )


# ─── _best_citation Helper ─────────────────────────────────────────


class TestBestCitation:
    def test_empty_chunks_returns_empty(self):
        assert _best_citation([]) == []

    def test_returns_single_citation(self):
        chunk = make_chunk(page=5, para=3, section="Exclusions", text="Some clause")
        result = _best_citation([chunk])
        assert len(result) == 1
        assert result[0].page_number == 5
        assert result[0].paragraph_number == 3
        assert result[0].section_title == "Exclusions"

    def test_uses_first_chunk(self):
        chunks = [
            make_chunk(page=1, para=1, text="First"),
            make_chunk(page=2, para=2, text="Second"),
        ]
        result = _best_citation(chunks)
        assert result[0].clause_text == "First"


# ─── R01: Exclusion Check ──────────────────────────────────────────


class TestR01:
    def test_pass_no_exclusions(self):
        item = make_item(description="Appendectomy surgery")
        bill = make_bill(items=[item])
        meta = make_meta(exclusions_list=[])
        r = rule_R01(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS
        assert r.approved_amount == item.amount

    def test_fail_matches_exclusion(self):
        item = make_item(description="Cosmetic surgery nose job")
        bill = make_bill(items=[item])
        meta = make_meta(exclusions_list=["cosmetic"])
        r = rule_R01(item, [make_chunk()], meta, bill)
        assert r.verdict == RuleVerdict.FAIL
        assert "cosmetic" in r.reason.lower()

    def test_fail_approved_amount_is_zero(self):
        item = make_item(description="Dental cleaning")
        bill = make_bill(items=[item])
        meta = make_meta(exclusions_list=["dental"])
        r = rule_R01(item, [], meta, bill)
        assert r.approved_amount == 0.0


# ─── R02: Waiting Period ───────────────────────────────────────────


class TestR02:
    def test_pass_after_waiting_period(self):
        item = make_item()
        bill = make_bill(items=[item], admission="2025-08-01")
        meta = make_meta(policy_start_date=date(2025, 1, 1), waiting_period_days=30)
        r = rule_R02(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_within_waiting_period(self):
        item = make_item()
        bill = make_bill(items=[item], admission="2025-01-15")
        meta = make_meta(policy_start_date=date(2025, 1, 1), waiting_period_days=30)
        r = rule_R02(item, [], meta, bill)
        assert r.verdict == RuleVerdict.FAIL

    def test_fail_approved_amount_is_zero(self):
        item = make_item(amount=75000)
        bill = make_bill(items=[item], admission="2025-01-10")
        meta = make_meta(policy_start_date=date(2025, 1, 1), waiting_period_days=30)
        r = rule_R02(item, [], meta, bill)
        assert r.approved_amount == 0.0


# ─── R03: Room Rent / ICU Sub-limit ────────────────────────────────


class TestR03:
    def test_pass_within_limit(self):
        item = make_item(category=BillItemCategory.ROOM_RENT, amount=20000)
        bill = make_bill(items=[item])  # 4 days → 5000/day
        meta = make_meta(room_rent_limit_per_day=5000)
        r = rule_R03(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_exceeds_limit(self):
        item = make_item(category=BillItemCategory.ROOM_RENT, amount=40000)
        bill = make_bill(items=[item])  # 4 days → 10000/day, limit 5000
        meta = make_meta(room_rent_limit_per_day=5000)
        r = rule_R03(item, [make_chunk()], meta, bill)
        assert r.verdict == RuleVerdict.FAIL

    def test_fail_partial_approval_room_rent(self):
        item = make_item(category=BillItemCategory.ROOM_RENT, amount=40000)
        bill = make_bill(items=[item])  # 4-day stay
        meta = make_meta(room_rent_limit_per_day=5000)
        r = rule_R03(item, [], meta, bill)
        # 5000 * 4 = 20000
        assert r.approved_amount == 20000.0

    def test_skip_for_surgery(self):
        item = make_item(category=BillItemCategory.SURGERY)
        bill = make_bill(items=[item])
        meta = make_meta()
        r = rule_R03(item, [], meta, bill)
        assert r.verdict == RuleVerdict.SKIP

    def test_icu_pass_within_limit(self):
        item = make_item(category=BillItemCategory.ICU, amount=40000)
        bill = make_bill(items=[item])  # 4 days → 10000/day
        meta = make_meta(icu_limit_per_day=10000)
        r = rule_R03(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_icu_fail_exceeds_limit(self):
        item = make_item(category=BillItemCategory.ICU, amount=80000)
        bill = make_bill(items=[item])  # 4 days → 20000/day, limit 10000
        meta = make_meta(icu_limit_per_day=10000)
        r = rule_R03(item, [make_chunk()], meta, bill)
        assert r.verdict == RuleVerdict.FAIL
        assert r.approved_amount == 40000.0  # 10000 * 4


# ─── R04: Pre-existing Condition ───────────────────────────────────


class TestR04:
    def test_pass_no_pre_existing(self):
        item = make_item()
        bill = make_bill(items=[item], diagnosis="Acute Appendicitis")
        meta = make_meta(pre_existing_conditions=[])
        r = rule_R04(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_matches_pre_existing(self):
        item = make_item()
        bill = make_bill(items=[item], diagnosis="Type 2 Diabetes Management")
        meta = make_meta(pre_existing_conditions=["diabetes"])
        r = rule_R04(item, [make_chunk()], meta, bill)
        assert r.verdict == RuleVerdict.FAIL

    def test_fail_approved_amount_is_zero(self):
        item = make_item(amount=100000)
        bill = make_bill(items=[item], diagnosis="Hypertension")
        meta = make_meta(pre_existing_conditions=["hypertension"])
        r = rule_R04(item, [], meta, bill)
        assert r.approved_amount == 0.0


# ─── R05: Claim Cap (Sum Insured) ──────────────────────────────────


class TestR05:
    def test_pass_within_sum_insured(self):
        item = make_item(amount=50000)
        bill = make_bill(items=[item], total_amount=100000)
        meta = make_meta(sum_insured=500000)
        r = rule_R05(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_exceeds_sum_insured(self):
        item = make_item(amount=50000)
        bill = make_bill(items=[item], total_amount=1000000)
        meta = make_meta(sum_insured=500000)
        r = rule_R05(item, [], meta, bill)
        assert r.verdict == RuleVerdict.FAIL

    def test_fail_proportional_approval_math(self):
        item = make_item(amount=100000)
        bill = make_bill(items=[item], total_amount=1000000)
        meta = make_meta(sum_insured=500000)
        r = rule_R05(item, [], meta, bill)
        # ratio = 500000/1000000 = 0.5 → 100000 * 0.5 = 50000
        assert r.approved_amount == 50000.0

    def test_skip_zero_sum_insured(self):
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta(sum_insured=0)
        r = rule_R05(item, [], meta, bill)
        assert r.verdict == RuleVerdict.SKIP


# ─── R06: Covered Procedure ────────────────────────────────────────


class TestR06:
    def test_pass_all_procedures_covered(self):
        item = make_item(category=BillItemCategory.SURGERY, description="Appendectomy")
        bill = make_bill(items=[item])
        meta = make_meta(covered_procedures=[])
        r = rule_R06(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_not_in_covered_list(self):
        item = make_item(category=BillItemCategory.SURGERY, description="Rhinoplasty")
        bill = make_bill(items=[item])
        meta = make_meta(covered_procedures=["appendectomy", "hernia repair"])
        r = rule_R06(item, [make_chunk()], meta, bill)
        assert r.verdict == RuleVerdict.FAIL
        assert r.approved_amount == 0.0

    def test_skip_for_medication(self):
        item = make_item(category=BillItemCategory.MEDICATION)
        bill = make_bill(items=[item])
        meta = make_meta(covered_procedures=["appendectomy"])
        r = rule_R06(item, [], meta, bill)
        assert r.verdict == RuleVerdict.SKIP

    def test_pass_matches_covered_procedure(self):
        item = make_item(category=BillItemCategory.SURGERY, description="Hernia repair surgery")
        bill = make_bill(items=[item])
        meta = make_meta(covered_procedures=["hernia repair"])
        r = rule_R06(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS


# ─── R07: Day Care Procedure ───────────────────────────────────────


class TestR07:
    def test_pass_no_day_care_list(self):
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta(day_care_procedures=[])
        r = rule_R07(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_day_care_billed_as_inpatient(self):
        item = make_item(description="Cataract surgery left eye")
        bill = make_bill(items=[item], admission="2025-08-01", discharge="2025-08-05")
        meta = make_meta(day_care_procedures=["cataract"])
        r = rule_R07(item, [make_chunk()], meta, bill)
        assert r.verdict == RuleVerdict.FAIL
        assert r.approved_amount == 0.0

    def test_pass_day_care_with_1_day_stay(self):
        item = make_item(description="Cataract surgery")
        bill = make_bill(items=[item], admission="2025-08-01", discharge="2025-08-02")
        meta = make_meta(day_care_procedures=["cataract"])
        r = rule_R07(item, [], meta, bill)
        # length_of_stay = 1, so day-care is acceptable
        assert r.verdict == RuleVerdict.PASS


# ─── R08: Consumables Exclusion ─────────────────────────────────────


class TestR08:
    def test_pass_consumables_covered(self):
        item = make_item(category=BillItemCategory.CONSUMABLES, amount=5000)
        bill = make_bill(items=[item])
        meta = make_meta(consumables_excluded=False)
        r = rule_R08(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_consumables_excluded(self):
        item = make_item(category=BillItemCategory.CONSUMABLES, amount=5000)
        bill = make_bill(items=[item])
        meta = make_meta(consumables_excluded=True)
        r = rule_R08(item, [make_chunk()], meta, bill)
        assert r.verdict == RuleVerdict.FAIL
        assert r.approved_amount == 0.0

    def test_skip_for_room_rent(self):
        item = make_item(category=BillItemCategory.ROOM_RENT)
        bill = make_bill(items=[item])
        meta = make_meta(consumables_excluded=True)
        r = rule_R08(item, [], meta, bill)
        assert r.verdict == RuleVerdict.SKIP


# ─── R09: Co-payment ───────────────────────────────────────────────


class TestR09:
    def test_always_pass_even_with_copay(self):
        item = make_item(amount=100000)
        bill = make_bill(items=[item])
        meta = make_meta(co_payment_percent=20)
        r = rule_R09(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_zero_copay_no_change(self):
        item = make_item(amount=50000)
        bill = make_bill(items=[item])
        meta = make_meta(co_payment_percent=0)
        r = rule_R09(item, [], meta, bill)
        assert r.approved_amount == 50000.0

    def test_copay_reduces_amount(self):
        item = make_item(amount=100000)
        bill = make_bill(items=[item])
        meta = make_meta(co_payment_percent=20)
        r = rule_R09(item, [], meta, bill)
        # 100000 * 0.80 = 80000
        assert r.approved_amount == 80000.0


# ─── R10: Network Hospital ─────────────────────────────────────────


class TestR10:
    def test_open_network_always_passes(self):
        item = make_item()
        bill = make_bill(items=[item], hospital="Random Hospital")
        meta = make_meta(empanelled_hospitals=[])
        r = rule_R10(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_pass_empanelled_hospital(self):
        item = make_item()
        bill = make_bill(items=[item], hospital="Apollo Hospital Delhi")
        meta = make_meta(empanelled_hospitals=["Apollo Hospital"])
        r = rule_R10(item, [], meta, bill)
        assert r.verdict == RuleVerdict.PASS

    def test_fail_non_empanelled_hospital(self):
        item = make_item()
        bill = make_bill(items=[item], hospital="City Clinic")
        meta = make_meta(empanelled_hospitals=["Apollo Hospital", "Max Hospital"])
        r = rule_R10(item, [], meta, bill)
        assert r.verdict == RuleVerdict.FAIL
        assert r.approved_amount == 0.0


# ─── R11: Duplicate Claim ──────────────────────────────────────────


class TestR11:
    def test_no_prior_dates_passes(self):
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta()
        r = rule_R11(item, [], meta, bill, prior_claim_dates=None)
        assert r.verdict == RuleVerdict.PASS

    def test_pass_no_duplicate(self):
        item = make_item()
        bill = make_bill(items=[item], admission="2025-08-01")
        meta = make_meta()
        r = rule_R11(item, [], meta, bill, prior_claim_dates=[date(2025, 7, 1)])
        assert r.verdict == RuleVerdict.PASS

    def test_fail_duplicate_date(self):
        item = make_item()
        bill = make_bill(items=[item], admission="2025-08-01")
        meta = make_meta()
        r = rule_R11(item, [], meta, bill, prior_claim_dates=[date(2025, 8, 1)])
        assert r.verdict == RuleVerdict.FAIL
        assert r.approved_amount == 0.0


# ─── R12: Document Completeness ────────────────────────────────────


class TestR12:
    def test_no_required_docs_passes(self):
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta()
        r = rule_R12(item, [], meta, bill, required_docs=None)
        assert r.verdict == RuleVerdict.PASS

    def test_pass_all_docs_submitted(self):
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta()
        r = rule_R12(item, [], meta, bill,
                     required_docs=["Discharge Summary", "Bill"],
                     submitted_docs=["discharge summary", "bill"])
        assert r.verdict == RuleVerdict.PASS

    def test_fail_missing_docs(self):
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta()
        r = rule_R12(item, [], meta, bill,
                     required_docs=["Discharge Summary", "Lab Report"],
                     submitted_docs=["Discharge Summary"])
        assert r.verdict == RuleVerdict.FAIL
        assert "Lab Report" in r.reason
        assert r.approved_amount == 0.0


# ─── Orchestrator (run_rules) ──────────────────────────────────────


class TestRunRules:
    def test_returns_line_item_results(self):
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta()
        results = run_rules(bill, meta, {})
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], LineItemResult)

    def test_approved_amount_is_minimum_across_rules(self):
        """Most restrictive rule wins."""
        item = make_item(category=BillItemCategory.ROOM_RENT, amount=40000)
        bill = make_bill(items=[item])
        # R03 will cap: 5000 * 4 = 20000
        # R09 co-pay will reduce: 40000 * 0.8 = 32000
        # Minimum of (20000, 32000) = 20000
        meta = make_meta(
            room_rent_limit_per_day=5000,
            co_payment_percent=20,
        )
        results = run_rules(bill, meta, {})
        assert results[0].approved_amount == 20000.0

    def test_all_skip_uses_original_amount(self):
        """When all applicable rules are SKIP, use original amount."""
        # Create item that triggers SKIP on R03, R06, R08
        # and PASS on everything else
        item = make_item(
            category=BillItemCategory.DIAGNOSTICS,
            amount=10000,
            description="Blood Test CBC",
        )
        bill = make_bill(items=[item], total_amount=10000)
        meta = make_meta()
        results = run_rules(bill, meta, {})
        # Some rules will PASS (R01, R02, etc) with approved = 10000
        # Some will SKIP (R03, R06, R08)
        # Minimum of PASS results is 10000
        assert results[0].approved_amount == 10000.0

    def test_multiple_failures_all_recorded(self):
        """Both R01 (exclusion) and R04 (pre-existing) can FAIL simultaneously."""
        item = make_item(
            category=BillItemCategory.SURGERY,
            description="Cosmetic rhinoplasty",
        )
        bill = make_bill(
            items=[item],
            diagnosis="Chronic Diabetes",
        )
        meta = make_meta(
            exclusions_list=["cosmetic"],
            pre_existing_conditions=["diabetes"],
        )
        results = run_rules(bill, meta, {})
        fail_rules = [
            r for r in results[0].rule_results if r.verdict == RuleVerdict.FAIL
        ]
        rule_names = {r.rule_name for r in fail_rules}
        assert "R01_exclusion_check" in rule_names
        assert "R04_pre_existing_condition" in rule_names

    def test_twelve_rules_evaluated(self):
        """Every line item should have exactly 12 rule results."""
        item = make_item()
        bill = make_bill(items=[item])
        meta = make_meta()
        results = run_rules(bill, meta, {})
        assert len(results[0].rule_results) == 12

    def test_multiple_items_processed(self):
        """Multiple line items should each get their own result."""
        items = [
            make_item(item_id=1, amount=10000, description="Room Rent", category=BillItemCategory.ROOM_RENT),
            make_item(item_id=2, amount=50000, description="Surgery", category=BillItemCategory.SURGERY),
            make_item(item_id=3, amount=5000, description="Medicine", category=BillItemCategory.MEDICATION),
        ]
        bill = make_bill(items=items)
        meta = make_meta()
        results = run_rules(bill, meta, {})
        assert len(results) == 3
        assert [r.item_id for r in results] == [1, 2, 3]
