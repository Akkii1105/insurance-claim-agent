"""Shared enumerations used across all models."""

from enum import Enum


class ClaimStatus(str, Enum):
    """Final outcome of a claim adjudication."""

    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIALLY_APPROVED = "partially_approved"
    PENDING = "pending"


class RuleVerdict(str, Enum):
    """Outcome of a single rule evaluation.

    PASS  = the line item satisfies this rule (no issue found).
    FAIL  = the line item violates this rule (should be rejected/reduced).
    SKIP  = the rule is not applicable to this line item.
    """

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class BillItemCategory(str, Enum):
    """Normalized categories for hospital bill line items.

    Used by the rule engine to look up category-specific policy limits
    (e.g., room rent sub-limit, ICU cap, surgery coverage).
    """

    ROOM_RENT = "room_rent"
    ICU = "icu"
    SURGERY = "surgery"
    CONSULTATION = "consultation"
    DIAGNOSTICS = "diagnostics"
    MEDICATION = "medication"
    CONSUMABLES = "consumables"
    AMBULANCE = "ambulance"
    PHYSIOTHERAPY = "physiotherapy"
    OTHER = "other"


class PDFType(str, Enum):
    """How text was obtained from a PDF."""

    TEXT_BASED = "text_based"
    SCANNED_OCR = "scanned_ocr"
