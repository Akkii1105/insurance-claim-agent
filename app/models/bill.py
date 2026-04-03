"""Bill-related schemas — output of the Bill Processor (Step 3)."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import BillItemCategory, PDFType


class BillLineItem(BaseModel):
    """A single line item extracted from a hospital bill.

    Each line item represents one charge — e.g. "Room Rent (General Ward) - 3 days @ ₹2000/day".
    The rule engine evaluates policy compliance per line item.
    """

    item_id: int = Field(
        ..., description="1-based sequential ID within the bill"
    )
    description: str = Field(
        ..., description="Raw description text as extracted from the bill"
    )
    category: BillItemCategory = Field(
        default=BillItemCategory.OTHER,
        description="Normalized category for rule engine lookup",
    )
    amount: float = Field(
        ..., ge=0, description="Charged amount for this line item"
    )
    quantity: Optional[int] = Field(
        default=None, ge=1, description="Number of units (days, sessions, etc.)"
    )
    unit_price: Optional[float] = Field(
        default=None, ge=0, description="Per-unit price if available"
    )


class Bill(BaseModel):
    """A fully parsed hospital bill.

    Produced by the Bill Processor from a raw PDF.
    Consumed by the Semantic Matcher and Rule Engine.
    """

    bill_id: str = Field(
        ..., description="Unique identifier for this bill (generated or extracted)"
    )
    patient_name: Optional[str] = Field(
        default=None, description="Patient name as it appears on the bill"
    )
    hospital_name: Optional[str] = Field(
        default=None, description="Name of the hospital that issued the bill"
    )
    admission_date: Optional[date] = Field(
        default=None, description="Date of hospital admission"
    )
    discharge_date: Optional[date] = Field(
        default=None, description="Date of hospital discharge"
    )
    diagnosis: Optional[str] = Field(
        default=None, description="Primary diagnosis or reason for admission"
    )
    line_items: list[BillLineItem] = Field(
        default_factory=list, description="Individual charges on the bill"
    )
    total_amount: float = Field(
        ..., ge=0, description="Total billed amount"
    )
    pdf_type: PDFType = Field(
        default=PDFType.TEXT_BASED,
        description="Whether text was extracted directly or via OCR",
    )
    raw_text: Optional[str] = Field(
        default=None, description="Full raw text extracted from the PDF (for debugging)"
    )
    source_file: Optional[str] = Field(
        default=None, description="Original PDF filename"
    )

    @property
    def computed_total(self) -> float:
        """Sum of all line item amounts — useful for cross-validation."""
        return sum(item.amount for item in self.line_items)

    @property
    def length_of_stay(self) -> Optional[int]:
        """Number of days between admission and discharge."""
        if self.admission_date and self.discharge_date:
            return (self.discharge_date - self.admission_date).days
        return None
