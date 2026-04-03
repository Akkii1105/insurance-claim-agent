"""PDF Report Generator — produces human-readable claim settlement reports.

Uses fpdf2 with built-in fonts only. Returns raw PDF bytes.
No external service calls or LLM usage.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from fpdf import FPDF

if TYPE_CHECKING:
    from app.models import Bill, ClaimDecision


def _fmt_inr(amount: float) -> str:
    """Format amount with Rs. prefix and commas."""
    return f"Rs.{amount:,.2f}"


def _safe(text: str) -> str:
    """Replace Unicode chars that built-in fonts cannot encode."""
    return (
        text
        .replace("\u20b9", "Rs.")
        .replace("\u2713", "[OK]")
        .replace("\u2717", "[X]")
        .replace("\u26a0", "[!]")
        .replace("\u23f3", "[?]")
        .replace("\u2014", "--")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .encode("latin-1", errors="replace")
        .decode("latin-1")
    )


def _status_badge(status_value: str) -> str:
    """Return a status badge string."""
    mapping = {
        "approved": "APPROVED",
        "rejected": "REJECTED",
        "partially_approved": "PARTIAL APPROVAL",
        "pending": "PENDING",
    }
    return mapping.get(status_value, status_value.upper())


def _status_prefix(status_value: str) -> str:
    """Return a symbol prefix for the status."""
    mapping = {
        "approved": "[OK]",
        "rejected": "[X]",
        "partially_approved": "[!]",
        "pending": "[?]",
    }
    return mapping.get(status_value, "")


class _ReportPDF(FPDF):
    """Custom FPDF subclass with header/footer for the report."""

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(
            0, 10,
            f"Automated deterministic rule engine decision. | Page {self.page_no()}",
            align="C",
        )


def generate_report(
    decision: "ClaimDecision",
    bill: "Bill | None" = None,
) -> bytes:
    """Generate a PDF report for a claim decision.

    Args:
        decision: The ClaimDecision to render.
        bill: Optional Bill for patient/hospital info.
              If None, those fields show "N/A".

    Returns:
        Raw PDF bytes.
    """
    pdf = _ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ── SECTION 1: Header ──────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _safe("Insurance Claim Settlement Report"), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe(f"Claim ID: {decision.claim_id}"), align="C", new_x="LMARGIN", new_y="NEXT")

    ts = decision.processed_at
    if ts:
        ts_str = ts.strftime("%d %b %Y, %H:%M UTC")
    else:
        ts_str = "N/A"
    pdf.cell(0, 6, _safe(f"Generated: {ts_str}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Status badge
    status_val = decision.status.value if hasattr(decision.status, "value") else str(decision.status)
    prefix = _status_prefix(status_val)
    badge = _status_badge(status_val)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _safe(f"{prefix} {badge}"), align="C", new_x="LMARGIN", new_y="NEXT")

    # Horizontal rule
    pdf.ln(2)
    pdf.set_draw_color(0, 0, 0)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ── SECTION 2: Claim Summary Table ─────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Claim Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    def _summary_row(label: str, value: str):
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(60, 7, _safe(label), border=0)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, _safe(value), border=0, new_x="LMARGIN", new_y="NEXT")

    _summary_row("Patient Name", bill.patient_name if bill and bill.patient_name else "N/A")
    _summary_row("Hospital", bill.hospital_name if bill and bill.hospital_name else "N/A")
    _summary_row("Admission Date", str(bill.admission_date) if bill and bill.admission_date else "N/A")
    _summary_row("Discharge Date", str(bill.discharge_date) if bill and bill.discharge_date else "N/A")
    _summary_row("Diagnosis", bill.diagnosis if bill and bill.diagnosis else "N/A")
    _summary_row("Total Billed", _fmt_inr(decision.total_billed))
    _summary_row("Total Approved", _fmt_inr(decision.total_approved))
    _summary_row("Total Rejected", _fmt_inr(decision.total_rejected))

    pdf.ln(5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ── SECTION 3: Line Item Decisions ─────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Line Item Decisions", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    for item in decision.line_item_results:
        # Verdict label
        if item.approved_amount >= item.original_amount:
            verdict_label = "[OK] COVERED"
        elif item.approved_amount == 0:
            verdict_label = "[X] NOT COVERED"
        else:
            verdict_label = "[!] PARTIAL"

        # Item header with gray background
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 10)
        header_text = (
            f"{item.item_description}  |  "
            f"Original: {_fmt_inr(item.original_amount)}  |  "
            f"Approved: {_fmt_inr(item.approved_amount)}  |  "
            f"{verdict_label}"
        )
        pdf.cell(0, 8, _safe(header_text), fill=True, new_x="LMARGIN", new_y="NEXT")

        # Fail rules
        for rr in item.rule_results:
            if rr.verdict.value == "fail":
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_x(20)
                reason_text = f"  [X] [{rr.rule_name}] {rr.reason}"
                pdf.multi_cell(170, 5, _safe(reason_text))

            # Show co-payment info even on pass
            if rr.rule_name == "R09_co_payment" and rr.verdict.value == "pass" and "Co-payment" in rr.reason:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_x(20)
                pdf.multi_cell(170, 5, _safe(f"  [i] {rr.reason}"))

        pdf.ln(3)

    pdf.ln(3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ── SECTION 4: Policy Citations ────────────────────────────────
    # Only render if any citation exists
    has_citations = False
    for item in decision.line_item_results:
        for rr in item.rule_results:
            if rr.citations:
                has_citations = True
                break
        if has_citations:
            break

    if has_citations:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Policy Basis for Rejection", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, "The following policy clauses were cited in this decision.", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        for item in decision.line_item_results:
            for rr in item.rule_results:
                if not rr.citations:
                    continue

                # Item header
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(
                    0, 7,
                    _safe(f"Line Item: {item.item_description} -- Rule {rr.rule_name}"),
                    new_x="LMARGIN", new_y="NEXT",
                )

                for cit in rr.citations:
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_x(15)
                    pdf.cell(
                        0, 5,
                        _safe(
                            f"Page: {cit.page_number}  |  "
                            f"Section: {cit.section_title or 'N/A'}  |  "
                            f"Paragraph: {cit.paragraph_number}"
                        ),
                        new_x="LMARGIN", new_y="NEXT",
                    )

                    pdf.set_x(15)
                    pdf.set_font("Helvetica", "I", 9)
                    clause = cit.clause_text or ""
                    pdf.multi_cell(175, 5, _safe(f'Clause: "{clause}"'))
                    pdf.ln(2)

        pdf.ln(3)

    # ── SECTION 5: Summary ─────────────────────────────────────────
    if decision.summary:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Decision Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _safe(decision.summary))

    return bytes(pdf.output())
