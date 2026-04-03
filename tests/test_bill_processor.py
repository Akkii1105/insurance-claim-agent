"""Tests for the Bill Processor pipeline.

Uses fpdf2 to generate synthetic bill PDFs at test time — no external
fixtures needed. Tests cover:
    - PDF type detection
    - Text extraction
    - Text cleaning
    - Line item parsing and category classification
    - Full pipeline (process_bill)
    - Schema validation of output
"""

import os
import tempfile
from pathlib import Path

import pytest

from app.models import Bill, BillItemCategory, PDFType
from app.services.bill_processor import (
    classify_category,
    clean_extracted_text,
    parse_bill_text,
    parse_line_items,
    process_bill,
)
from app.utils.pdf_utils import detect_pdf_type, extract_text_pdfplumber


# ─── Helpers ────────────────────────────────────────────────────────


def _create_sample_bill_pdf(path: str) -> None:
    """Create a synthetic text-based hospital bill PDF using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Apollo Hospital", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, "123 Medical Street, Mumbai", ln=True, align="C")
    pdf.ln(5)

    # Patient info
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "Patient Name: Rajesh Kumar", ln=True)
    pdf.cell(0, 7, "Diagnosis: Acute Appendicitis", ln=True)
    pdf.cell(0, 7, "Date of Admission: 15/01/2025", ln=True)
    pdf.cell(0, 7, "Date of Discharge: 20/01/2025", ln=True)
    pdf.ln(5)

    # Bill header
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(100, 8, "Description", border=1)
    pdf.cell(40, 8, "Amount (INR)", border=1, ln=True, align="R")

    # Line items
    pdf.set_font("Helvetica", "", 11)
    items = [
        ("Room Rent - General Ward (5 days)", "25,000.00"),
        ("ICU Charges (2 days)", "40,000.00"),
        ("Surgery - Appendectomy", "80,000.00"),
        ("Consultation - Surgeon Fee", "15,000.00"),
        ("Laboratory Tests - Blood Work", "8,500.00"),
        ("Pharmacy - Medications", "12,000.00"),
        ("Consumables and Disposables", "5,500.00"),
        ("Ambulance Charges", "3,000.00"),
    ]
    for desc, amount in items:
        pdf.cell(100, 7, desc, border=1)
        pdf.cell(40, 7, amount, border=1, ln=True, align="R")

    # Total
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(100, 8, "Grand Total", border=1)
    pdf.cell(40, 8, "1,89,000.00", border=1, ln=True, align="R")

    pdf.output(path)


@pytest.fixture
def sample_bill_pdf(tmp_path: Path) -> Path:
    """Create a temporary sample bill PDF and return its path."""
    pdf_path = tmp_path / "sample_bill.pdf"
    _create_sample_bill_pdf(str(pdf_path))
    return pdf_path


@pytest.fixture
def sample_bill_text() -> str:
    """Return realistic bill text for testing parsing functions."""
    return """Apollo Hospital
123 Medical Street, Mumbai

Patient Name: Rajesh Kumar
Diagnosis: Acute Appendicitis
Date of Admission: 15/01/2025
Date of Discharge: 20/01/2025

Description                                    Amount (INR)
Room Rent - General Ward (5 days)              25,000.00
ICU Charges (2 days)                           40,000.00
Surgery - Appendectomy                         80,000.00
Consultation - Surgeon Fee                     15,000.00
Laboratory Tests - Blood Work                  8,500.00
Pharmacy - Medications                         12,000.00
Consumables and Disposables                    5,500.00
Ambulance Charges                              3,000.00

Grand Total                                    1,89,000.00"""


# ─── PDF Type Detection ────────────────────────────────────────────


class TestPDFTypeDetection:
    def test_text_based_pdf_detected(self, sample_bill_pdf: Path):
        pdf_type = detect_pdf_type(sample_bill_pdf)
        assert pdf_type == PDFType.TEXT_BASED

    def test_nonexistent_pdf_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            detect_pdf_type(tmp_path / "nonexistent.pdf")

    def test_invalid_pdf_raises(self, tmp_path: Path):
        """A non-PDF file should raise an error."""
        path = tmp_path / "not_a_pdf.pdf"
        path.write_text("This is not a PDF file.", encoding="utf-8")
        with pytest.raises(Exception):
            detect_pdf_type(path)


# ─── Text Extraction ───────────────────────────────────────────────


class TestTextExtraction:
    def test_pdfplumber_extracts_text(self, sample_bill_pdf: Path):
        pages = extract_text_pdfplumber(sample_bill_pdf)
        assert len(pages) >= 1
        full_text = "\n".join(pages)
        assert "Apollo Hospital" in full_text
        assert "Rajesh Kumar" in full_text

    def test_pdfplumber_extracts_amounts(self, sample_bill_pdf: Path):
        pages = extract_text_pdfplumber(sample_bill_pdf)
        full_text = "\n".join(pages)
        # Check that amounts appear in the extracted text
        assert "25,000" in full_text or "25000" in full_text


# ─── Text Cleaning ──────────────────────────────────────────────────


class TestTextCleaning:
    def test_collapses_whitespace(self):
        text = "Room   Rent    General   Ward"
        cleaned = clean_extracted_text(text)
        assert cleaned == "Room Rent General Ward"

    def test_removes_control_characters(self):
        text = "Hello\x00World\x01Test"
        cleaned = clean_extracted_text(text)
        assert cleaned == "HelloWorldTest"

    def test_normalizes_line_endings(self):
        text = "line1\r\nline2\rline3\nline4"
        cleaned = clean_extracted_text(text)
        assert "\r" not in cleaned
        assert "line1\nline2\nline3\nline4" == cleaned

    def test_collapses_blank_lines(self):
        text = "line1\n\n\n\nline2"
        cleaned = clean_extracted_text(text)
        assert cleaned == "line1\n\nline2"

    def test_strips_lines(self):
        text = "  hello  \n  world  "
        cleaned = clean_extracted_text(text)
        assert cleaned == "hello\nworld"


# ─── Category Classification ───────────────────────────────────────


class TestCategoryClassification:
    def test_room_rent(self):
        assert classify_category("Room Rent - General Ward") == BillItemCategory.ROOM_RENT

    def test_icu(self):
        assert classify_category("ICU Charges (2 days)") == BillItemCategory.ICU

    def test_surgery(self):
        assert classify_category("Surgery - Appendectomy") == BillItemCategory.SURGERY

    def test_consultation(self):
        assert classify_category("Consultation - Surgeon Fee") == BillItemCategory.CONSULTATION

    def test_diagnostics(self):
        assert classify_category("Laboratory Tests - Blood Work") == BillItemCategory.DIAGNOSTICS

    def test_medication(self):
        assert classify_category("Pharmacy - Medications") == BillItemCategory.MEDICATION

    def test_consumables(self):
        assert classify_category("Consumables and Disposables") == BillItemCategory.CONSUMABLES

    def test_ambulance(self):
        assert classify_category("Ambulance Charges") == BillItemCategory.AMBULANCE

    def test_unknown_defaults_to_other(self):
        assert classify_category("Miscellaneous fee") == BillItemCategory.OTHER


# ─── Line Item Parsing ──────────────────────────────────────────────


class TestLineItemParsing:
    def test_parses_items_from_bill_text(self, sample_bill_text: str):
        items = parse_line_items(sample_bill_text)
        assert len(items) >= 5  # Should find most line items
        # Check that items have sequential IDs
        for i, item in enumerate(items):
            assert item.item_id == i + 1

    def test_skips_total_lines(self, sample_bill_text: str):
        items = parse_line_items(sample_bill_text)
        descriptions = [item.description.lower() for item in items]
        assert not any("grand total" in d for d in descriptions)
        assert not any("total" == d for d in descriptions)

    def test_amounts_are_positive(self, sample_bill_text: str):
        items = parse_line_items(sample_bill_text)
        for item in items:
            assert item.amount > 0

    def test_categories_assigned(self, sample_bill_text: str):
        items = parse_line_items(sample_bill_text)
        categories = {item.category for item in items}
        # Should have at least a couple different categories
        assert len(categories) >= 2

    def test_deduplicates(self):
        text = """Room Rent General Ward 5000.00
Room Rent General Ward 5000.00
ICU Charges 10000.00"""
        items = parse_line_items(text)
        # Should have 2 unique items, not 3
        assert len(items) == 2


# ─── Full Bill Parsing ──────────────────────────────────────────────


class TestBillParsing:
    def test_parses_patient_name(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert bill.patient_name is not None
        assert "Rajesh Kumar" in bill.patient_name

    def test_parses_diagnosis(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert bill.diagnosis is not None
        assert "Appendicitis" in bill.diagnosis

    def test_parses_dates(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert bill.admission_date is not None
        assert bill.discharge_date is not None
        assert bill.admission_date.year == 2025
        assert bill.admission_date.month == 1
        assert bill.admission_date.day == 15

    def test_length_of_stay(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert bill.length_of_stay == 5

    def test_has_line_items(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert len(bill.line_items) >= 5

    def test_total_amount_extracted(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert bill.total_amount > 0

    def test_bill_id_generated(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert bill.bill_id.startswith("BILL-")

    def test_raw_text_preserved(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        assert bill.raw_text == sample_bill_text

    def test_json_serializable(self, sample_bill_text: str):
        bill = parse_bill_text(sample_bill_text, PDFType.TEXT_BASED)
        json_str = bill.model_dump_json()
        restored = Bill.model_validate_json(json_str)
        assert restored.bill_id == bill.bill_id
        assert len(restored.line_items) == len(bill.line_items)


# ─── End-to-End Pipeline ───────────────────────────────────────────


class TestProcessBill:
    def test_end_to_end_text_pdf(self, sample_bill_pdf: Path):
        bill = process_bill(sample_bill_pdf)

        # Verify it returns a valid Bill
        assert isinstance(bill, Bill)
        assert bill.pdf_type == PDFType.TEXT_BASED
        assert bill.source_file == "sample_bill.pdf"

        # Verify structure
        assert bill.bill_id.startswith("BILL-")
        assert bill.total_amount > 0
        assert len(bill.line_items) >= 1
        assert bill.raw_text is not None

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            process_bill("/nonexistent/path/bill.pdf")

    def test_output_validates_against_schema(self, sample_bill_pdf: Path):
        bill = process_bill(sample_bill_pdf)
        # Pydantic validates on construction — if we got here, it's valid.
        # Double-check with explicit validation:
        data = bill.model_dump()
        validated = Bill.model_validate(data)
        assert validated.bill_id == bill.bill_id

    def test_line_items_have_categories(self, sample_bill_pdf: Path):
        bill = process_bill(sample_bill_pdf)
        for item in bill.line_items:
            assert item.category is not None
            assert isinstance(item.category, BillItemCategory)
