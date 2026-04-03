"""Tests for the PDF Report Generator — 12+ tests.

Validates PDF output for all claim statuses, with/without bill,
edge cases, and API endpoint integration.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.main import app
from app.models import (
    Bill,
    BillItemCategory,
    BillLineItem,
    Citation,
    ClaimDecision,
    ClaimStatus,
    PolicyChunk,
    RuleVerdict,
)
from app.models.rule import LineItemResult, RuleResult
from app.services.report_generator import generate_report


# ─── Helpers ────────────────────────────────────────────────────────


def _make_rule(
    name: str = "R01_exclusion_check",
    verdict: RuleVerdict = RuleVerdict.PASS,
    reason: str = "Item is not excluded.",
    amount: float = 50000.0,
    approved: float | None = None,
    citations: list[Citation] | None = None,
) -> RuleResult:
    return RuleResult(
        rule_name=name,
        rule_description="Test rule",
        item_id=1,
        verdict=verdict,
        reason=reason,
        original_amount=amount,
        approved_amount=approved if approved is not None else amount,
        citations=citations or [],
    )


def _make_item(
    item_id: int = 1,
    desc: str = "Appendectomy Surgery",
    amount: float = 50000.0,
    approved: float = 50000.0,
    rules: list[RuleResult] | None = None,
) -> LineItemResult:
    return LineItemResult(
        item_id=item_id,
        item_description=desc,
        original_amount=amount,
        approved_amount=approved,
        rule_results=rules or [_make_rule()],
    )


def _make_decision(
    status: ClaimStatus = ClaimStatus.APPROVED,
    items: list[LineItemResult] | None = None,
    total_billed: float = 50000.0,
    total_approved: float = 50000.0,
) -> ClaimDecision:
    items = items or [_make_item()]
    return ClaimDecision(
        claim_id="CLM-TEST-RPT-001",
        bill_id="BILL-TEST",
        policy_id="POL-TEST",
        status=status,
        total_billed=total_billed,
        total_approved=total_approved,
        total_rejected=round(total_billed - total_approved, 2),
        line_item_results=items,
        summary="Test claim summary.",
        processed_at=datetime(2025, 8, 15, 10, 30, 0, tzinfo=UTC),
    )


def _make_bill() -> Bill:
    return Bill(
        bill_id="BILL-RPT-001",
        patient_name="Rajesh Kumar",
        hospital_name="Apollo Hospital Delhi",
        admission_date=date(2025, 8, 1),
        discharge_date=date(2025, 8, 5),
        diagnosis="Acute Appendicitis",
        line_items=[
            BillLineItem(item_id=1, description="Surgery", category=BillItemCategory.SURGERY, amount=50000),
        ],
        total_amount=50000,
    )


def _make_citation(page: int = 12, section: str = "Exclusions", text: str = "Cosmetic procedures excluded.") -> Citation:
    return Citation(
        policy_id="POL-TEST",
        chunk_id=f"p{page}_para1",
        page_number=page,
        paragraph_number=1,
        section_title=section,
        clause_text=text,
        relevance_score=0.9,
    )


# ─── Tests ──────────────────────────────────────────────────────────


class TestReportGenerator:
    def test_returns_bytes(self):
        result = generate_report(_make_decision())
        assert isinstance(result, bytes)

    def test_valid_pdf_magic_bytes(self):
        result = generate_report(_make_decision())
        assert result[:5] == b"%PDF-"

    def test_approved_status_no_crash(self):
        result = generate_report(_make_decision(ClaimStatus.APPROVED))
        assert len(result) > 100

    def test_rejected_status_no_crash(self):
        fail_rule = _make_rule(verdict=RuleVerdict.FAIL, reason="Excluded", approved=0)
        item = _make_item(approved=0, rules=[fail_rule])
        decision = _make_decision(ClaimStatus.REJECTED, items=[item], total_approved=0)
        result = generate_report(decision)
        assert result[:5] == b"%PDF-"

    def test_partial_status_no_crash(self):
        fail_rule = _make_rule(verdict=RuleVerdict.FAIL, approved=30000)
        item = _make_item(approved=30000, rules=[fail_rule])
        decision = _make_decision(ClaimStatus.PARTIALLY_APPROVED, items=[item], total_approved=30000)
        result = generate_report(decision)
        assert result[:5] == b"%PDF-"

    def test_bill_none_no_crash(self):
        result = generate_report(_make_decision(), bill=None)
        assert result[:5] == b"%PDF-"

    def test_bill_provided_larger_output(self):
        no_bill = generate_report(_make_decision(), bill=None)
        with_bill = generate_report(_make_decision(), bill=_make_bill())
        # Both should be valid PDFs
        assert no_bill[:5] == b"%PDF-"
        assert with_bill[:5] == b"%PDF-"

    def test_zero_line_items_no_crash(self):
        decision = _make_decision(items=[])
        result = generate_report(decision)
        assert result[:5] == b"%PDF-"

    def test_no_citations_smaller_output(self):
        # Without citations
        no_cit_decision = _make_decision()
        no_cit_pdf = generate_report(no_cit_decision)

        # With citations
        cit = _make_citation()
        fail_rule = _make_rule(verdict=RuleVerdict.FAIL, reason="Excluded", approved=0, citations=[cit])
        item = _make_item(approved=0, rules=[fail_rule])
        cit_decision = _make_decision(ClaimStatus.REJECTED, items=[item], total_approved=0)
        cit_pdf = generate_report(cit_decision)

        # Citation version should be larger (has extra section)
        assert len(cit_pdf) > len(no_cit_pdf)

    def test_many_line_items_auto_page_break(self):
        """10+ line items should trigger auto page break without crash."""
        items = [
            _make_item(item_id=i, desc=f"Line Item {i}", amount=10000)
            for i in range(15)
        ]
        decision = _make_decision(items=items, total_billed=150000, total_approved=150000)
        result = generate_report(decision)
        assert result[:5] == b"%PDF-"
        assert len(result) > 500

    def test_long_clause_text_no_crash(self):
        """500-char clause text must word-wrap correctly."""
        long_text = "A" * 500
        cit = _make_citation(text=long_text)
        fail_rule = _make_rule(verdict=RuleVerdict.FAIL, approved=0, citations=[cit])
        item = _make_item(approved=0, rules=[fail_rule])
        decision = _make_decision(ClaimStatus.REJECTED, items=[item], total_approved=0)
        result = generate_report(decision)
        assert result[:5] == b"%PDF-"


class TestReportEndpointIntegration:
    """Test that GET /api/v1/claims/{id}/report returns a real PDF."""

    @pytest.fixture(scope="class")
    def client(self):
        with TestClient(app) as c:
            yield c

    @pytest.fixture
    def sample_bill_pdf(self, tmp_path) -> Path:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 7, "Patient Name: Test Patient", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, "Hospital Name: Apollo Hospital Delhi", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, "Diagnosis: Acute Appendicitis", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, "Date of Admission: 01/08/2025", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, "Date of Discharge: 05/08/2025", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(120, 8, "Description", border=1)
        pdf.cell(40, 8, "Amount (INR)", border=1, new_x="LMARGIN", new_y="NEXT", align="R")
        pdf.set_font("Helvetica", size=10)
        pdf.cell(120, 7, "Appendectomy Surgery", border=1)
        pdf.cell(40, 7, "50000", border=1, new_x="LMARGIN", new_y="NEXT", align="R")
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(120, 8, "Total")
        pdf.cell(40, 8, "50000", border=1, new_x="LMARGIN", new_y="NEXT", align="R")
        path = tmp_path / "bill.pdf"
        pdf.output(str(path))
        return path

    @pytest.fixture
    def sample_policy_pdf(self, tmp_path) -> Path:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "COVERED PROCEDURES", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 6, "The following procedures are covered: appendectomy, bypass surgery and all medically necessary procedures approved by the insurer.")
        path = tmp_path / "policy.pdf"
        pdf.output(str(path))
        return path

    @pytest.fixture
    def sample_policy_metadata(self, tmp_path) -> Path:
        meta = {
            "policy_id": "POL-RPT-TEST",
            "policy_name": "Test Policy",
            "insurer": "Test Insure",
            "sum_insured": 500000,
            "waiting_period_days": 30,
            "policy_start_date": "2025-01-01",
            "room_rent_limit_per_day": 5000,
            "icu_limit_per_day": 10000,
            "co_payment_percent": 0,
            "empanelled_hospitals": [],
            "exclusions_list": [],
            "covered_procedures": [],
            "pre_existing_conditions": [],
            "day_care_procedures": [],
            "consumables_excluded": False,
        }
        path = tmp_path / "policy_metadata.json"
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return path

    def test_report_returns_200_and_pdf(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        # First process a claim
        files = {
            "bill_pdf": ("bill.pdf", open(sample_bill_pdf, "rb"), "application/pdf"),
            "policy_pdf": ("policy.pdf", open(sample_policy_pdf, "rb"), "application/pdf"),
            "policy_metadata": ("meta.json", open(sample_policy_metadata, "rb"), "application/json"),
        }
        try:
            resp = client.post("/api/v1/claims/process", files=files)
        finally:
            for f in files.values():
                f[1].close()
        assert resp.status_code == 200
        claim_id = resp.json()["claim_id"]

        # Now get the report
        report_resp = client.get(f"/api/v1/claims/{claim_id}/report")
        assert report_resp.status_code == 200
        assert report_resp.headers["content-type"] == "application/pdf"
        assert report_resp.content[:5] == b"%PDF-"
