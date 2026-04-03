"""Bill Processor — converts hospital bill PDFs into structured Bill models.

Pipeline:
    PDF file → detect type → extract text → clean text → parse structure → Bill

This module is the first AI-enabled ingestion layer. Its output feeds:
    - Semantic Matcher (bill line items → matched policy clauses)
    - Rule Engine (line items evaluated against policy rules)
"""

import re
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from app.models import Bill, BillLineItem, BillItemCategory, PDFType
from app.utils.pdf_utils import extract_text


# ── Category Classification ─────────────────────────────────────────
# Keyword-based classifier. Fast, deterministic, easily extended.
# Keys are BillItemCategory values, values are keyword lists.

_CATEGORY_KEYWORDS: dict[BillItemCategory, list[str]] = {
    BillItemCategory.ROOM_RENT: [
        "room", "room rent", "ward", "bed charge", "accommodation",
        "general ward", "semi private", "private room", "deluxe room",
    ],
    BillItemCategory.ICU: [
        "icu", "intensive care", "critical care", "ccu", "nicu", "picu",
        "high dependency", "hdu",
    ],
    BillItemCategory.SURGERY: [
        "surgery", "surgical", "operation", "operative", "ot charge",
        "theatre", "anesthesia", "anaesthesia", "procedure charge",
    ],
    BillItemCategory.CONSULTATION: [
        "consultation", "doctor visit", "physician", "specialist fee",
        "professional fee", "visiting charge", "doctor fee",
    ],
    BillItemCategory.DIAGNOSTICS: [
        "lab", "laboratory", "pathology", "radiology", "x-ray", "xray",
        "mri", "ct scan", "ultrasound", "usg", "ecg", "eeg",
        "blood test", "diagnostic", "imaging", "scan",
    ],
    BillItemCategory.MEDICATION: [
        "medicine", "medication", "pharmacy", "drug", "injection",
        "iv fluid", "antibiotic", "tablet", "capsule", "syrup",
    ],
    BillItemCategory.CONSUMABLES: [
        "consumable", "disposable", "ppe", "glove", "syringe", "bandage",
        "surgical supply", "implant", "stent", "catheter", "mask",
    ],
    BillItemCategory.AMBULANCE: [
        "ambulance", "transport", "emergency vehicle",
    ],
    BillItemCategory.PHYSIOTHERAPY: [
        "physiotherapy", "physio", "rehabilitation", "rehab",
    ],
}


def classify_category(description: str) -> BillItemCategory:
    """Classify a bill line item description into a BillItemCategory.

    Uses keyword matching against the item description. Returns OTHER
    if no keywords match.

    Args:
        description: Raw line item description text.

    Returns:
        The best-matching BillItemCategory.
    """
    desc_lower = description.lower()

    # Score each category by keyword matches, weighted by keyword length.
    # Longer (more specific) keywords score higher, so "room rent" beats "room".
    best_category = BillItemCategory.OTHER
    best_score = 0

    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(len(kw) for kw in keywords if kw in desc_lower)
        if score > best_score:
            best_score = score
            best_category = category

    return best_category


# ── Text Cleaning ────────────────────────────────────────────────────


def clean_extracted_text(raw_text: str) -> str:
    """Clean raw extracted text for easier parsing.

    - Normalize whitespace (collapse multiple spaces/tabs)
    - Remove null bytes and control characters
    - Normalize line endings
    - Strip leading/trailing whitespace per line

    Args:
        raw_text: Raw text from PDF extraction.

    Returns:
        Cleaned text.
    """
    # Remove null bytes and control chars (except newline, tab)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw_text)
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse multiple spaces/tabs within lines (preserve newlines)
    text = re.sub(r"[^\S\n]+", " ", text)
    # Strip each line
    lines = [line.strip() for line in text.split("\n")]
    # Remove consecutive blank lines (keep at most one)
    cleaned_lines: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned_lines.append("")
            prev_blank = True
        else:
            cleaned_lines.append(line)
            prev_blank = False

    return "\n".join(cleaned_lines).strip()


# ── Structured Parsing ───────────────────────────────────────────────


# Regex patterns for extracting amounts from bill text
# Matches patterns like: "Room Rent ... 5,000.00" or "Room Rent ₹5000"
_AMOUNT_PATTERN = re.compile(
    r"[₹Rs\.INR\s]*?([\d,]+(?:\.\d{1,2})?)\s*$"
)

# Matches lines that look like bill line items:
# "1. Room Rent (General Ward) ... 5,000.00"
# "Room Rent - 3 days           6000.00"
_LINE_ITEM_PATTERN = re.compile(
    r"^"
    r"(?:(\d+)[.\)\-\s]+)?"          # Optional item number
    r"(.+?)"                          # Description (non-greedy)
    r"\s+"                            # Separator whitespace
    r"[₹Rs\.INR\s]*?"                # Optional currency prefix
    r"([\d,]+(?:\.\d{1,2})?)"        # Amount
    r"\s*$",                          # End of line
    re.MULTILINE,
)

# Date patterns commonly found in Indian hospital bills
_DATE_PATTERNS = [
    re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})"),  # DD/MM/YYYY
    re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})"),  # YYYY/MM/DD
]


def _parse_amount(amount_str: str) -> float:
    """Parse an amount string like '5,000.00' or '5000' into a float."""
    cleaned = amount_str.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_dates(text: str) -> list[date]:
    """Extract dates from text, returning them in order of appearance."""
    dates: list[date] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()
            try:
                if len(groups[0]) == 4:  # YYYY/MM/DD
                    d = date(int(groups[0]), int(groups[1]), int(groups[2]))
                else:  # DD/MM/YYYY
                    d = date(int(groups[2]), int(groups[1]), int(groups[0]))
                # Basic sanity check
                if 2000 <= d.year <= 2030:
                    dates.append(d)
            except ValueError:
                continue
    return dates


def _extract_field(text: str, pattern: re.Pattern, group: int = 1) -> Optional[str]:
    """Extract a single field from text using a regex pattern."""
    match = pattern.search(text)
    if match:
        return match.group(group).strip()
    return None


# Patterns for extracting metadata fields
_PATIENT_NAME_PATTERN = re.compile(
    r"(?:patient\s*(?:name)?|name\s*of\s*patient|mr\.|mrs\.|ms\.)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_HOSPITAL_NAME_PATTERN = re.compile(
    r"(?:hospital|clinic|medical\s*cent(?:er|re)|nursing\s*home)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_DIAGNOSIS_PATTERN = re.compile(
    r"(?:diagnosis|condition|ailment|disease)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_TOTAL_PATTERN = re.compile(
    r"(?:total|grand\s*total|net\s*amount|amount\s*payable|bill\s*amount)"
    r"\s*[:\-]?\s*[₹Rs\.INR\s]*?([\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def parse_line_items(text: str) -> list[BillLineItem]:
    """Parse line items from cleaned bill text.

    Uses regex to find lines that look like:
        [optional number] description ... amount

    Args:
        text: Cleaned bill text.

    Returns:
        List of BillLineItem objects.
    """
    items: list[BillLineItem] = []
    seen_amounts: set[str] = set()

    for match in _LINE_ITEM_PATTERN.finditer(text):
        raw_number = match.group(1)
        description = match.group(2).strip()
        amount_str = match.group(3)

        # Skip if description is too short (likely noise) or is a header/total
        if len(description) < 3:
            continue
        desc_lower = description.lower()
        if any(kw in desc_lower for kw in ["total", "grand total", "net amount", "payable", "balance"]):
            continue

        amount = _parse_amount(amount_str)
        if amount <= 0:
            continue

        # De-duplicate by description + amount (OCR can produce duplicates)
        dedup_key = f"{desc_lower}|{amount_str}"
        if dedup_key in seen_amounts:
            continue
        seen_amounts.add(dedup_key)

        item_id = len(items) + 1
        category = classify_category(description)

        items.append(
            BillLineItem(
                item_id=item_id,
                description=description,
                category=category,
                amount=amount,
            )
        )

    return items


def parse_bill_text(
    text: str,
    pdf_type: PDFType,
    source_file: Optional[str] = None,
) -> Bill:
    """Parse cleaned bill text into a structured Bill model.

    Extracts:
        - Patient name, hospital name, diagnosis (regex-based)
        - Admission and discharge dates
        - Line items with amounts and categories
        - Total billed amount

    Args:
        text: Cleaned, concatenated bill text.
        pdf_type: How the text was extracted.
        source_file: Original PDF filename.

    Returns:
        A validated Bill model.
    """
    # Extract metadata
    patient_name = _extract_field(text, _PATIENT_NAME_PATTERN)
    hospital_name = _extract_field(text, _HOSPITAL_NAME_PATTERN)
    diagnosis = _extract_field(text, _DIAGNOSIS_PATTERN)

    # Extract dates
    dates = _extract_dates(text)
    admission_date = dates[0] if len(dates) >= 1 else None
    discharge_date = dates[1] if len(dates) >= 2 else None

    # Extract line items
    line_items = parse_line_items(text)

    # Extract total amount (try explicit total first, fall back to sum of items)
    total_match = _TOTAL_PATTERN.search(text)
    if total_match:
        total_amount = _parse_amount(total_match.group(1))
    elif line_items:
        total_amount = sum(item.amount for item in line_items)
    else:
        total_amount = 0.0

    return Bill(
        bill_id=f"BILL-{uuid.uuid4().hex[:8].upper()}",
        patient_name=patient_name,
        hospital_name=hospital_name,
        admission_date=admission_date,
        discharge_date=discharge_date,
        diagnosis=diagnosis,
        line_items=line_items,
        total_amount=total_amount,
        pdf_type=pdf_type,
        raw_text=text,
        source_file=source_file,
    )


# ── Main Entry Point ────────────────────────────────────────────────


def process_bill(pdf_path: str | Path) -> Bill:
    """Process a hospital bill PDF end-to-end.

    This is the main entry point for the Bill Processor.

    Pipeline:
        1. Detect PDF type (text-based vs scanned)
        2. Extract raw text (pdfplumber or OCR)
        3. Clean the text
        4. Parse into structured Bill model

    Args:
        pdf_path: Path to the hospital bill PDF.

    Returns:
        A validated Bill model ready for the Semantic Matcher and Rule Engine.

    Raises:
        FileNotFoundError: If the PDF doesn't exist.
        ValueError: If the PDF has no pages or no extractable content.
    """
    pdf_path = Path(pdf_path)

    # Step 1 + 2: Auto-detect and extract
    pages, pdf_type = extract_text(pdf_path)

    # Concatenate all pages with page markers
    raw_text = "\n\n".join(pages)

    if not raw_text.strip():
        raise ValueError(
            f"No text could be extracted from {pdf_path}. "
            "The PDF may be empty or contain only images without OCR."
        )

    # Step 3: Clean
    cleaned_text = clean_extracted_text(raw_text)

    # Step 4: Parse into structured Bill
    bill = parse_bill_text(
        text=cleaned_text,
        pdf_type=pdf_type,
        source_file=pdf_path.name,
    )

    return bill
