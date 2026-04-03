"""Tests for the API layer — all 4 endpoints.

Uses FastAPI's TestClient (httpx) with synthetic PDFs generated
by fpdf2 and a JSON policy metadata fixture.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.config import settings
from app.main import app


# ─── TestClient ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


# ─── Synthetic File Fixtures ────────────────────────────────────────


@pytest.fixture
def sample_bill_pdf(tmp_path) -> Path:
    """Generate a minimal hospital bill PDF using fpdf2."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16)
    pdf.cell(0, 10, "Apollo Hospital Delhi", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 7, "Patient Name: Test Patient", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Diagnosis: Acute Appendicitis", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Date of Admission: 01/08/2025", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Date of Discharge: 05/08/2025", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Table header
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(120, 8, "Description", border=1)
    pdf.cell(40, 8, "Amount (INR)", border=1, new_x="LMARGIN", new_y="NEXT", align="R")

    # Line items
    items = [
        ("Appendectomy Surgery", "50,000.00"),
        ("Room Rent (General Ward) - 4 days", "20,000.00"),
        ("Medicines and Drugs", "15,000.00"),
        ("Diagnostic Tests - Blood/Urine", "8,000.00"),
    ]
    pdf.set_font("Helvetica", size=10)
    for desc, amount in items:
        pdf.cell(120, 7, desc, border=1)
        pdf.cell(40, 7, amount, border=1, new_x="LMARGIN", new_y="NEXT", align="R")

    # Total
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(120, 8, "Total")
    pdf.cell(40, 8, "93,000.00", border=1, new_x="LMARGIN", new_y="NEXT", align="R")

    path = tmp_path / "bill.pdf"
    pdf.output(str(path))
    return path


@pytest.fixture
def sample_policy_pdf(tmp_path) -> Path:
    """Generate a minimal 3-page policy PDF using fpdf2."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=10)

    # Page 1: Covered Procedures
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "COVERED PROCEDURES", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 6, (
        "The following surgical procedures are covered under this policy. "
        "This includes appendectomy, hernia repair, cholecystectomy, and "
        "other medically necessary surgeries as determined by the treating "
        "physician. All covered procedures must be performed at a network "
        "hospital with valid pre-authorization."
    ))

    # Page 2: Exclusions
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "GENERAL EXCLUSIONS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 6, (
        "The insurer shall not be liable for any expenses related to "
        "cosmetic surgery, plastic surgery, or any elective procedures "
        "not medically necessary. Cataract surgery is excluded during "
        "the first year of the policy. Dental treatments and corrective "
        "vision surgery (LASIK) are not covered under any circumstances."
    ))

    # Page 3: Waiting Period
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "WAITING PERIOD", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 6, (
        "A waiting period of 30 days applies from the date of policy "
        "commencement. No claims are admissible during this initial "
        "waiting period. Pre-existing conditions have a waiting period "
        "of 48 months from the policy start date."
    ))

    path = tmp_path / "policy.pdf"
    pdf.output(str(path))
    return path


@pytest.fixture
def sample_policy_metadata(tmp_path) -> Path:
    """Write a valid policy_metadata.json with rule engine parameters."""
    meta = {
        "policy_id": "POL-TEST-API-001",
        "policy_name": "Test Health Shield",
        "insurer": "TestInsure Ltd",
        "sum_insured": 500000,
        "waiting_period_days": 30,
        "policy_start_date": "2025-01-01",
        "room_rent_limit_per_day": 5000,
        "icu_limit_per_day": 10000,
        "co_payment_percent": 10,
        "empanelled_hospitals": ["Apollo Hospital"],
        "exclusions_list": ["cosmetic", "cataract"],
        "covered_procedures": ["appendectomy"],
        "pre_existing_conditions": [],
        "day_care_procedures": [],
        "consumables_excluded": False,
    }
    path = tmp_path / "policy_metadata.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


# ─── Helper: POST a claim and return the response ──────────────────


def _post_claim(client, bill_pdf, policy_pdf, policy_metadata, **extra_form):
    """Helper to POST /api/v1/claims/process with files."""
    files = {
        "bill_pdf": ("bill.pdf", open(bill_pdf, "rb"), "application/pdf"),
        "policy_pdf": ("policy.pdf", open(policy_pdf, "rb"), "application/pdf"),
        "policy_metadata": ("meta.json", open(policy_metadata, "rb"), "application/json"),
    }
    try:
        return client.post("/api/v1/claims/process", files=files, data=extra_form)
    finally:
        for _, f in files.items():
            f[1].close()


# ─── TestHealthEndpoint ─────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


# ─── TestListClaims ─────────────────────────────────────────────────


class TestListClaims:
    def test_empty_claims_list(self, client):
        # Clean claims dir for this test
        claims_dir = Path(settings.storage_dir) / "claims"
        if claims_dir.exists():
            for f in claims_dir.glob("*.json"):
                f.unlink()
        resp = client.get("/api/v1/claims/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["claims"] == []
        assert data["total"] == 0

    def test_claims_list_after_processing(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        # Process a claim first
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        assert resp.status_code == 200
        claim_id = resp.json()["claim_id"]

        # Now list should include it
        list_resp = client.get("/api/v1/claims/")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert claim_id in data["claims"]
        assert data["total"] >= 1


# ─── TestGetClaim ──────────────────────────────────────────────────


class TestGetClaim:
    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/v1/claims/nonexistent-id-12345")
        assert resp.status_code == 404

    def test_get_existing_claim(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        # Process a claim first
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        assert resp.status_code == 200
        claim_id = resp.json()["claim_id"]

        # Retrieve it
        get_resp = client.get(f"/api/v1/claims/{claim_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["claim_id"] == claim_id
        assert "status" in data
        assert "total_billed" in data


# ─── TestProcessClaim ──────────────────────────────────────────────


class TestProcessClaim:
    def test_returns_200_with_valid_files(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        assert resp.status_code == 200

    def test_response_has_claim_id(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        data = resp.json()
        assert "claim_id" in data
        assert len(data["claim_id"]) > 0

    def test_response_has_status(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        data = resp.json()
        assert data["status"] in ["approved", "rejected", "partially_approved", "pending"]

    def test_response_has_total_billed(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        data = resp.json()
        assert data["total_billed"] > 0

    def test_response_has_line_item_results(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        data = resp.json()
        assert isinstance(data["line_item_results"], list)
        assert len(data["line_item_results"]) > 0

    def test_missing_bill_pdf_returns_422(
        self, client, sample_policy_pdf, sample_policy_metadata,
    ):
        files = {
            "policy_pdf": ("policy.pdf", open(sample_policy_pdf, "rb"), "application/pdf"),
            "policy_metadata": ("meta.json", open(sample_policy_metadata, "rb"), "application/json"),
        }
        try:
            resp = client.post("/api/v1/claims/process", files=files)
        finally:
            for f in files.values():
                f[1].close()
        assert resp.status_code == 422

    def test_missing_policy_pdf_returns_422(
        self, client, sample_bill_pdf, sample_policy_metadata,
    ):
        files = {
            "bill_pdf": ("bill.pdf", open(sample_bill_pdf, "rb"), "application/pdf"),
            "policy_metadata": ("meta.json", open(sample_policy_metadata, "rb"), "application/json"),
        }
        try:
            resp = client.post("/api/v1/claims/process", files=files)
        finally:
            for f in files.values():
                f[1].close()
        assert resp.status_code == 422

    def test_missing_metadata_returns_422(
        self, client, sample_bill_pdf, sample_policy_pdf,
    ):
        files = {
            "bill_pdf": ("bill.pdf", open(sample_bill_pdf, "rb"), "application/pdf"),
            "policy_pdf": ("policy.pdf", open(sample_policy_pdf, "rb"), "application/pdf"),
        }
        try:
            resp = client.post("/api/v1/claims/process", files=files)
        finally:
            for f in files.values():
                f[1].close()
        assert resp.status_code == 422


# ─── TestReportEndpoint ────────────────────────────────────────────


class TestReportEndpoint:
    def test_report_returns_pdf(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        # Process a claim first
        resp = _post_claim(client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata)
        claim_id = resp.json()["claim_id"]

        report_resp = client.get(f"/api/v1/claims/{claim_id}/report")
        assert report_resp.status_code == 200
        assert report_resp.headers["content-type"] == "application/pdf"

    def test_report_nonexistent_returns_404(self, client):
        resp = client.get("/api/v1/claims/nonexistent-xyz/report")
        assert resp.status_code == 404


# ─── TestOptionalFields ───────────────────────────────────────────


class TestOptionalFields:
    def test_prior_claim_date_triggers_duplicate_rejection(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        """R11: matching prior_claim_date should cause a FAIL."""
        resp = _post_claim(
            client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
            prior_claim_dates="2025-08-01",
        )
        data = resp.json()
        assert resp.status_code == 200
        # Find the duplicate claim rule result
        has_r11_fail = False
        for lr in data.get("line_item_results", []):
            for rr in lr.get("rule_results", []):
                if rr["rule_name"] == "R11_duplicate_claim" and rr["verdict"] == "fail":
                    has_r11_fail = True
        assert has_r11_fail, "R11 should FAIL when prior_claim_dates matches admission"

    def test_required_docs_missing_triggers_failure(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        """R12: required docs not submitted → FAIL."""
        resp = _post_claim(
            client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
            required_docs="Discharge Summary,Lab Report",
            submitted_docs="",
        )
        data = resp.json()
        assert resp.status_code == 200
        has_r12_fail = False
        for lr in data.get("line_item_results", []):
            for rr in lr.get("rule_results", []):
                if rr["rule_name"] == "R12_document_completeness" and rr["verdict"] == "fail":
                    has_r12_fail = True
        assert has_r12_fail, "R12 should FAIL when required docs are missing"

    def test_empty_prior_dates_no_crash(
        self, client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
    ):
        """Empty string for prior_claim_dates should not crash."""
        resp = _post_claim(
            client, sample_bill_pdf, sample_policy_pdf, sample_policy_metadata,
            prior_claim_dates="",
        )
        assert resp.status_code == 200
