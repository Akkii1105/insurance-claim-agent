"""Tests for data model validation and serialization."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.models import (
    Bill,
    BillItemCategory,
    BillLineItem,
    Citation,
    ClaimDecision,
    ClaimStatus,
    LineItemResult,
    PDFType,
    PolicyChunk,
    PolicyMeta,
    RuleResult,
    RuleVerdict,
)


# ─── BillLineItem ──────────────────────────────────────────────────


class TestBillLineItem:
    def test_valid_line_item(self):
        item = BillLineItem(
            item_id=1,
            description="Room Rent - General Ward",
            category=BillItemCategory.ROOM_RENT,
            amount=6000.0,
            quantity=3,
            unit_price=2000.0,
        )
        assert item.item_id == 1
        assert item.category == BillItemCategory.ROOM_RENT
        assert item.amount == 6000.0

    def test_default_category_is_other(self):
        item = BillLineItem(item_id=1, description="Misc charges", amount=500.0)
        assert item.category == BillItemCategory.OTHER

    def test_negative_amount_rejected(self):
        with pytest.raises(ValidationError):
            BillLineItem(item_id=1, description="Test", amount=-100.0)

    def test_json_serialization(self):
        item = BillLineItem(item_id=1, description="Test", amount=100.0)
        data = item.model_dump()
        assert isinstance(data, dict)
        assert data["category"] == "other"  # str enum serializes to string


# ─── Bill ───────────────────────────────────────────────────────────


class TestBill:
    def test_valid_bill(self):
        bill = Bill(
            bill_id="BILL-001",
            patient_name="Rajesh Kumar",
            hospital_name="Apollo Hospital",
            admission_date=date(2024, 1, 10),
            discharge_date=date(2024, 1, 15),
            diagnosis="Appendicitis",
            total_amount=150000.0,
            line_items=[
                BillLineItem(item_id=1, description="Room Rent", amount=30000.0, category=BillItemCategory.ROOM_RENT),
                BillLineItem(item_id=2, description="Surgery", amount=80000.0, category=BillItemCategory.SURGERY),
                BillLineItem(item_id=3, description="Medication", amount=40000.0, category=BillItemCategory.MEDICATION),
            ],
        )
        assert bill.length_of_stay == 5
        assert bill.computed_total == 150000.0

    def test_length_of_stay_none_when_dates_missing(self):
        bill = Bill(bill_id="BILL-002", total_amount=1000.0)
        assert bill.length_of_stay is None

    def test_pdf_type_default(self):
        bill = Bill(bill_id="BILL-003", total_amount=0.0)
        assert bill.pdf_type == PDFType.TEXT_BASED

    def test_json_roundtrip(self):
        bill = Bill(
            bill_id="BILL-004",
            total_amount=5000.0,
            line_items=[BillLineItem(item_id=1, description="Test", amount=5000.0)],
        )
        json_str = bill.model_dump_json()
        restored = Bill.model_validate_json(json_str)
        assert restored.bill_id == "BILL-004"
        assert len(restored.line_items) == 1


# ─── PolicyChunk ────────────────────────────────────────────────────


class TestPolicyChunk:
    def test_valid_chunk(self):
        chunk = PolicyChunk(
            chunk_id="pol001_p5_para3",
            policy_id="POL-001",
            page_number=5,
            paragraph_number=3,
            text="Room rent is limited to 1% of sum insured per day.",
            section_title="Room Rent Sub-Limits",
        )
        assert chunk.location_label == "Page 5, Paragraph 3"

    def test_empty_text_rejected(self):
        with pytest.raises(ValidationError):
            PolicyChunk(
                chunk_id="x", policy_id="x", page_number=1,
                paragraph_number=1, text="",
            )

    def test_embedding_excluded_from_json(self):
        chunk = PolicyChunk(
            chunk_id="x", policy_id="x", page_number=1,
            paragraph_number=1, text="Some text",
            embedding=[0.1, 0.2, 0.3],
        )
        data = chunk.model_dump()
        assert "embedding" not in data

    def test_page_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            PolicyChunk(
                chunk_id="x", policy_id="x", page_number=0,
                paragraph_number=1, text="Some text",
            )


# ─── PolicyMeta ─────────────────────────────────────────────────────


class TestPolicyMeta:
    def test_valid_meta(self):
        meta = PolicyMeta(
            policy_id="POL-001",
            policy_name="Star Health Gold",
            insurer="Star Health",
            total_pages=45,
            total_chunks=120,
            source_file="star_health_gold.pdf",
        )
        assert meta.total_pages == 45


# ─── Citation ───────────────────────────────────────────────────────


class TestCitation:
    def test_valid_citation(self):
        citation = Citation(
            policy_id="POL-001",
            chunk_id="pol001_p12_para3",
            page_number=12,
            paragraph_number=3,
            section_title="Exclusions",
            clause_text="Pre-existing conditions within 48 months are excluded.",
            relevance_score=0.87,
        )
        assert citation.location_label == "Page 12, Paragraph 3 (Exclusions)"

    def test_location_label_without_section(self):
        citation = Citation(
            policy_id="POL-001",
            chunk_id="x",
            page_number=5,
            paragraph_number=2,
            clause_text="Some clause",
            relevance_score=0.5,
        )
        assert citation.location_label == "Page 5, Paragraph 2"

    def test_relevance_score_bounds(self):
        with pytest.raises(ValidationError):
            Citation(
                policy_id="x", chunk_id="x", page_number=1,
                paragraph_number=1, clause_text="x",
                relevance_score=1.5,  # out of bounds
            )


# ─── RuleResult ─────────────────────────────────────────────────────


class TestRuleResult:
    def test_pass_verdict(self):
        result = RuleResult(
            rule_name="exclusion_check",
            rule_description="Check if item is excluded",
            item_id=1,
            verdict=RuleVerdict.PASS,
            reason="Item is not excluded.",
            original_amount=10000.0,
        )
        assert not result.is_failure
        assert result.reduction == 0.0

    def test_fail_verdict_with_reduction(self):
        result = RuleResult(
            rule_name="room_rent_cap",
            rule_description="Check room rent sub-limit",
            item_id=1,
            verdict=RuleVerdict.FAIL,
            reason="Room rent exceeds limit of ₹5000/day.",
            original_amount=8000.0,
            approved_amount=5000.0,
            citations=[
                Citation(
                    policy_id="POL-001",
                    chunk_id="x",
                    page_number=10,
                    paragraph_number=2,
                    clause_text="Room rent limited to ₹5000/day.",
                    relevance_score=0.92,
                )
            ],
        )
        assert result.is_failure
        assert result.reduction == 3000.0
        assert len(result.citations) == 1


# ─── LineItemResult ─────────────────────────────────────────────────


class TestLineItemResult:
    def test_fully_rejected(self):
        result = LineItemResult(
            item_id=1,
            item_description="Cosmetic surgery",
            original_amount=50000.0,
            approved_amount=0.0,
        )
        assert result.is_fully_rejected
        assert not result.is_reduced

    def test_partially_reduced(self):
        result = LineItemResult(
            item_id=2,
            item_description="Room Rent",
            original_amount=10000.0,
            approved_amount=5000.0,
        )
        assert not result.is_fully_rejected
        assert result.is_reduced

    def test_all_citations_flattened(self):
        citation = Citation(
            policy_id="x", chunk_id="x", page_number=1,
            paragraph_number=1, clause_text="Excluded",
            relevance_score=0.9,
        )
        result = LineItemResult(
            item_id=1,
            item_description="Test",
            original_amount=1000.0,
            approved_amount=0.0,
            rule_results=[
                RuleResult(
                    rule_name="r1", rule_description="d1", item_id=1,
                    verdict=RuleVerdict.FAIL, reason="Excluded",
                    original_amount=1000.0, citations=[citation],
                ),
                RuleResult(
                    rule_name="r2", rule_description="d2", item_id=1,
                    verdict=RuleVerdict.PASS, reason="OK",
                    original_amount=1000.0,
                ),
            ],
        )
        assert len(result.all_citations) == 1  # Only from failing rules


# ─── ClaimDecision ──────────────────────────────────────────────────


class TestClaimDecision:
    def test_approved_claim(self):
        decision = ClaimDecision(
            claim_id="CLM-001",
            bill_id="BILL-001",
            policy_id="POL-001",
            status=ClaimStatus.APPROVED,
            total_billed=100000.0,
            total_approved=100000.0,
            total_rejected=0.0,
            summary="All items approved.",
        )
        assert decision.fully_approved
        assert not decision.has_rejections
        assert decision.approval_rate == 100.0

    def test_partially_approved_claim(self):
        decision = ClaimDecision(
            claim_id="CLM-002",
            bill_id="BILL-002",
            policy_id="POL-001",
            status=ClaimStatus.PARTIALLY_APPROVED,
            total_billed=100000.0,
            total_approved=60000.0,
            total_rejected=40000.0,
            summary="Some items reduced.",
            rejection_reasons=["Room rent exceeds sub-limit."],
        )
        assert decision.approval_rate == 60.0
        assert decision.has_rejections
        assert len(decision.rejection_reasons) == 1

    def test_json_serialization(self):
        decision = ClaimDecision(
            claim_id="CLM-003",
            bill_id="BILL-003",
            policy_id="POL-001",
            status=ClaimStatus.REJECTED,
            total_billed=50000.0,
            total_approved=0.0,
            total_rejected=50000.0,
        )
        data = decision.model_dump()
        assert data["status"] == "rejected"
        assert isinstance(data["processed_at"], datetime)

    def test_zero_billed_approval_rate(self):
        decision = ClaimDecision(
            claim_id="CLM-004",
            bill_id="BILL-004",
            policy_id="POL-001",
            status=ClaimStatus.PENDING,
            total_billed=0.0,
            total_approved=0.0,
            total_rejected=0.0,
        )
        assert decision.approval_rate == 0.0
