"""Low-level PDF utilities: type detection, text extraction, OCR fallback.

This module handles the "raw" layer — getting text out of PDFs.
The higher-level parsing (structuring text into Bill models) lives in
``app.services.bill_processor``.
"""

from pathlib import Path

import pdfplumber

from app.config import settings
from app.models.enums import PDFType


# ── Minimum characters per page to consider it "text-based" ──────────
# A scanned page typically yields 0-10 chars from pdfplumber (stray OCR
# artifacts). A real text-based page has hundreds. 50 is a safe threshold.
_MIN_CHARS_PER_PAGE = 50


def detect_pdf_type(pdf_path: str | Path) -> PDFType:
    """Determine whether a PDF contains extractable text or is scanned.

    Strategy: open the file with pdfplumber and check the first few pages.
    If the average character count per page is below a threshold, treat it
    as scanned.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        PDFType.TEXT_BASED or PDFType.SCANNED_OCR
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            raise ValueError(f"PDF has no pages: {pdf_path}")

        # Sample up to 3 pages for speed
        sample_pages = pdf.pages[:3]
        total_chars = sum(
            len(page.extract_text() or "") for page in sample_pages
        )
        avg_chars = total_chars / len(sample_pages)

    if avg_chars >= _MIN_CHARS_PER_PAGE:
        return PDFType.TEXT_BASED
    return PDFType.SCANNED_OCR


def extract_text_pdfplumber(pdf_path: str | Path) -> list[str]:
    """Extract text from a text-based PDF using pdfplumber.

    Returns a list of strings, one per page, preserving page order.
    Empty pages return empty strings.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        List of page texts (0-indexed by page).
    """
    pdf_path = Path(pdf_path)
    pages_text: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    return pages_text


def extract_text_ocr(pdf_path: str | Path) -> list[str]:
    """Extract text from a scanned PDF using OCR (pdf2image + pytesseract).

    Converts each page to an image, then runs Tesseract OCR. This is the
    fallback path for scanned documents.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        List of page texts (0-indexed by page).

    Raises:
        ImportError: If pdf2image or pytesseract are not available.
        RuntimeError: If Tesseract is not installed or configured.
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as e:
        raise ImportError(
            f"OCR dependencies not installed: {e}. "
            "Install pdf2image and pytesseract: pip install pdf2image pytesseract"
        ) from e

    # Configure tesseract path if set
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    # Convert PDF pages to images
    poppler_kwargs = {}
    if settings.poppler_path:
        poppler_kwargs["poppler_path"] = settings.poppler_path

    try:
        images = convert_from_path(pdf_path, dpi=300, **poppler_kwargs)
    except Exception as e:
        raise RuntimeError(
            f"Failed to convert PDF to images: {e}. "
            "Ensure poppler is installed. On Windows, set POPPLER_PATH in .env."
        ) from e

    pages_text: list[str] = []
    for img in images:
        text = pytesseract.image_to_string(img, lang="eng")
        pages_text.append(text.strip())

    return pages_text


def extract_text(pdf_path: str | Path) -> tuple[list[str], PDFType]:
    """Auto-detect PDF type and extract text using the appropriate method.

    This is the main entry point for text extraction.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Tuple of (list of page texts, PDFType used).
    """
    pdf_type = detect_pdf_type(pdf_path)

    if pdf_type == PDFType.TEXT_BASED:
        pages = extract_text_pdfplumber(pdf_path)
    else:
        pages = extract_text_ocr(pdf_path)

    return pages, pdf_type
