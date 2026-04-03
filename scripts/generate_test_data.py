"""Generate synthetic test data for the Insurance Claim Settlement Agent.

Creates:
  - 3 policy PDFs (12-16 pages each) with metadata JSON
  - 25 hospital bill PDFs
  - ground_truth.json with expected outcomes

Usage: python scripts/generate_test_data.py
"""

import json
import sys
from pathlib import Path

from fpdf import FPDF

# ── Output directories ──────────────────────────────────────────────

BASE = Path("data/synthetic")
POLICIES_DIR = BASE / "policies"
BILLS_DIR = BASE / "bills"


def _ensure_dirs():
    POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    BILLS_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════
# POLICY PDF GENERATION
# ════════════════════════════════════════════════════════════════════


_POLICY_SECTIONS = {
    "policy_a": {
        "covered_procedures": (
            "The following surgical procedures are covered under this policy: "
            "appendectomy, bypass surgery, angioplasty, and knee replacement. "
            "All covered procedures must be performed at a network hospital with "
            "valid pre-authorization. The insurer covers the cost of surgery, "
            "anaesthesia, and related consumables used during the procedure. "
            "Emergency procedures may be approved post-facto subject to review."
        ),
        "general_exclusions": (
            "The insurer shall not be liable for any expenses related to "
            "cosmetic surgery, plastic surgery, or any elective procedures "
            "not medically necessary. Cataract surgery is excluded during "
            "the first two years of the policy. Dental treatments including "
            "dental implants, root canal, and orthodontics are not covered "
            "under any circumstances. Self-inflicted injuries are excluded."
        ),
        "waiting_period": (
            "A waiting period of 30 days applies from the policy start date. "
            "No claims are admissible during this initial waiting period. "
            "Pre-existing conditions have a waiting period of 48 months from "
            "the policy start date. The policy start date for this plan is "
            "1st January 2025."
        ),
        "room_rent": (
            "Room rent for general ward is limited to Rs.5000 per day. "
            "ICU charges are limited to Rs.10000 per day. Any charges "
            "exceeding these limits shall be borne by the insured. "
            "Deluxe and suite rooms are not covered unless medically necessary."
        ),
        "pre_existing": (
            "The following pre-existing conditions are not covered under "
            "this policy during the initial 48-month waiting period: "
            "diabetes mellitus (Type 1 and Type 2), hypertension, and "
            "related complications. If the insured has a known history of "
            "these conditions, claims related to them will be rejected."
        ),
        "network_hospitals": (
            "The following hospitals are empanelled under this policy: "
            "Apollo Hospital Delhi, Fortis Hospital Mumbai. Treatment at "
            "non-empanelled hospitals will result in claim rejection. "
            "The insured must verify hospital empanelment before admission."
        ),
        "day_care": (
            "The following procedures are covered only as day-care procedures "
            "and must not be billed as inpatient stays exceeding 24 hours: "
            "chemotherapy, dialysis, and minor arthroscopy. If these procedures "
            "are billed as multi-day inpatient stays, the claim will be rejected."
        ),
        "consumables": (
            "Consumables and disposables used during treatment are covered "
            "under this policy. This includes surgical gloves, syringes, "
            "catheters, and other single-use items. The insurer will reimburse "
            "reasonable and customary charges for consumables."
        ),
        "co_payment": (
            "A co-payment of 10 percent applies to all claims under this "
            "policy. The insured is responsible for paying 10 percent of the "
            "total approved amount. The co-payment is deducted from the final "
            "settlement amount before disbursement."
        ),
        "sum_insured": (
            "The maximum sum insured under this policy is Rs.500000 "
            "(Five Lakhs) per policy year. Claims exceeding the sum insured "
            "will be proportionally reduced. The sum insured is inclusive of "
            "all benefits and sub-limits specified in this policy."
        ),
    },
    "policy_b": {
        "covered_procedures": (
            "The following surgical procedures are covered under this policy: "
            "knee replacement, dialysis, appendectomy, and radiation therapy. "
            "All procedures require pre-authorization from the insurer. "
            "The insurer reserves the right to request a second medical opinion "
            "before approving high-value procedures. Organ transplant surgery "
            "may be covered subject to specific terms and conditions."
        ),
        "general_exclusions": (
            "The insurer shall not be liable for expenses related to: "
            "cosmetic surgery and related procedures, hernia repair surgery "
            "during the first year, infertility treatment including IVF, "
            "and weight loss surgery. Adventure sports injuries and "
            "self-inflicted injuries are permanently excluded from coverage."
        ),
        "waiting_period": (
            "A waiting period of 60 days applies from the date of policy "
            "commencement on 1st March 2025. No claims are admissible during "
            "this initial waiting period of sixty days. Coverage begins on "
            "30th April 2025 for standard conditions. Pre-existing conditions "
            "carry an additional waiting period of 36 months."
        ),
        "room_rent": (
            "Room rent for general ward accommodation is limited to Rs.3000 "
            "per day. ICU and critical care unit charges are capped at Rs.7000 "
            "per day. Any excess charges shall be the responsibility of the "
            "policyholder. Semi-private rooms are treated as general ward."
        ),
        "pre_existing": (
            "Pre-existing conditions not covered during the waiting period: "
            "asthma and chronic obstructive pulmonary disease, diabetes "
            "mellitus and diabetic complications including diabetic nephropathy. "
            "These conditions will be covered after the completion of the "
            "36-month waiting period from the policy start date."
        ),
        "network_hospitals": (
            "Empanelled hospitals under this policy include: Max Hospital "
            "Noida, AIIMS Delhi. Claims from non-empanelled hospitals will "
            "not be processed. The insured must verify the hospital's network "
            "status before seeking treatment."
        ),
        "day_care": (
            "Day-care procedures covered under this policy include: "
            "cataract surgery, chemotherapy sessions, and minor diagnostic "
            "procedures. These must be completed within 24 hours and cannot "
            "be billed as multi-day inpatient admissions."
        ),
        "consumables": (
            "Consumables and disposable medical items are NOT covered under "
            "this policy. The policyholder is responsible for all charges "
            "related to consumables, disposables, and non-reusable medical "
            "supplies. This includes but is not limited to gloves, syringes, "
            "and surgical dressings."
        ),
        "co_payment": (
            "A co-payment of 20 percent applies to all claims. The insured "
            "must bear 20 percent of the total approved claim amount. This "
            "co-payment is applied after all sub-limits and deductions have "
            "been computed."
        ),
        "sum_insured": (
            "The maximum sum insured under this policy is Rs.300000 "
            "(Three Lakhs) per policy year. Any claims that cause the total "
            "to exceed the sum insured will be proportionally reduced or "
            "rejected beyond the coverage limit."
        ),
    },
    "policy_c": {
        "covered_procedures": (
            "This comprehensive policy covers all medically necessary "
            "surgical and non-surgical procedures without restriction. "
            "This includes but is not limited to: appendectomy, bypass "
            "surgery, angioplasty, knee replacement, dialysis, organ "
            "transplants, and cancer treatments. No pre-authorization is "
            "required for emergency procedures."
        ),
        "general_exclusions": (
            "The following are excluded from coverage: dental treatments "
            "including dental implants and orthodontics, infertility "
            "treatment including IVF and surrogacy. All other medically "
            "necessary treatments are covered under this comprehensive plan."
        ),
        "waiting_period": (
            "This policy has no waiting period. Coverage begins immediately "
            "from the policy start date of 1st January 2024. All conditions "
            "including pre-existing conditions are covered from day one. "
            "There is no initial waiting period for any category of illness."
        ),
        "room_rent": (
            "Room rent for general ward is limited to Rs.10000 per day. "
            "ICU charges are limited to Rs.20000 per day. These generous "
            "limits ensure that policyholders have access to quality "
            "accommodation during their hospital stay."
        ),
        "pre_existing": (
            "This comprehensive policy covers all pre-existing conditions "
            "from the policy start date. There is no exclusion or waiting "
            "period for pre-existing conditions. The insured is covered for "
            "all medical conditions regardless of prior history."
        ),
        "network_hospitals": (
            "This policy operates on an open network basis. All hospitals "
            "across India are accepted. There is no restriction on hospital "
            "choice. The insured may seek treatment at any registered "
            "hospital without network limitations."
        ),
        "day_care": (
            "All day-care procedures are covered without any restrictions "
            "on billing format. The insured may bill day-care or inpatient "
            "stays as appropriate for the medical condition."
        ),
        "consumables": (
            "All consumables and disposables used during treatment are "
            "fully covered under this policy. This includes all surgical "
            "supplies, medical devices, and single-use items."
        ),
        "co_payment": (
            "There is no co-payment under this policy. The insurer bears "
            "100 percent of the approved claim amount. The insured is not "
            "required to pay any portion of the claim."
        ),
        "sum_insured": (
            "The maximum sum insured under this policy is Rs.1000000 "
            "(Ten Lakhs) per policy year. This high coverage limit ensures "
            "comprehensive financial protection for major medical events."
        ),
    },
}

_FILLER_CLAIM_PROCESS = (
    "To file a claim, the insured or their representative must submit the "
    "claim form along with all supporting documents within 30 days of "
    "discharge from the hospital. Required documents include the original "
    "hospital bill, discharge summary, investigation reports, and a valid "
    "photo ID. The insurer will process the claim within 30 days of receipt "
    "of all required documents. Incomplete submissions will be returned to "
    "the insured with a list of missing documents. Appeals against rejected "
    "claims must be filed within 60 days of the rejection notification."
)

_FILLER_TERMS = (
    "This policy is governed by the laws of India and subject to the "
    "jurisdiction of courts in New Delhi. The insurer reserves the right "
    "to investigate any claim before settlement. Fraudulent claims will "
    "result in immediate policy cancellation and legal action. The terms "
    "and conditions of this policy are subject to change with prior notice "
    "of 30 days to the policyholder. Premium payments must be made on time "
    "to ensure continuous coverage. Lapsed policies may be reinstated "
    "subject to underwriting review and additional premium payment. "
    "All disputes shall be resolved through arbitration as per the "
    "Insurance Regulatory and Development Authority of India guidelines. "
    "The policyholder must disclose all material facts at the time of "
    "policy inception and renewal. Non-disclosure may void the policy."
)


def _gen_policy_pdf(name: str, sections: dict, output_path: Path):
    """Generate a 12-16 page policy PDF."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", size=10)

    section_map = {
        "COVERED PROCEDURES": sections["covered_procedures"],
        "GENERAL EXCLUSIONS": sections["general_exclusions"],
        "WAITING PERIOD": sections["waiting_period"],
        "ROOM RENT SUB-LIMITS": sections["room_rent"],
        "PRE-EXISTING CONDITIONS": sections["pre_existing"],
        "NETWORK HOSPITALS": sections["network_hospitals"],
        "DAY CARE PROCEDURES": sections["day_care"],
        "CONSUMABLES AND DISPOSABLES": sections["consumables"],
        "CO-PAYMENT TERMS": sections["co_payment"],
        "SUM INSURED": sections["sum_insured"],
        "CLAIM SETTLEMENT PROCESS": _FILLER_CLAIM_PROCESS,
        "GENERAL TERMS AND CONDITIONS": _FILLER_TERMS,
    }

    # Title page
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.ln(40)
    pdf.cell(0, 15, f"{name.upper()} INSURANCE POLICY", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, "Health Insurance Policy Document", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.cell(0, 8, "Issued by: Synthetic Insurance Ltd.", align="C", new_x="LMARGIN", new_y="NEXT")

    for heading, content in section_map.items():
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, content)
        pdf.ln(5)
        # Add padding content to fill pages
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, f"[End of {heading} section. Refer to schedule for details.]")

    # Add 2 more filler pages
    for i in range(2):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, f"ANNEXURE {i+1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, (
            f"This annexure provides additional details regarding the policy terms. "
            f"All conditions specified in the main policy document apply. The insurer "
            f"reserves the right to modify these terms with reasonable notice. "
            f"For queries, contact the customer helpline at 1800-XXX-XXXX."
        ))

    pdf.output(str(output_path))


_METADATA = {
    "policy_a": {
        "policy_id": "POL-A-001",
        "policy_name": "Health Shield Gold",
        "insurer": "Synthetic Insurance Ltd",
        "sum_insured": 500000,
        "waiting_period_days": 30,
        "policy_start_date": "2025-01-01",
        "room_rent_limit_per_day": 5000,
        "icu_limit_per_day": 10000,
        "co_payment_percent": 10,
        "empanelled_hospitals": ["Apollo Hospital Delhi", "Fortis Hospital Mumbai"],
        "exclusions_list": ["cosmetic", "cataract", "dental"],
        "covered_procedures": ["appendectomy", "bypass surgery", "angioplasty"],
        "pre_existing_conditions": ["diabetes", "hypertension"],
        "day_care_procedures": ["chemotherapy", "dialysis"],
        "consumables_excluded": False,
    },
    "policy_b": {
        "policy_id": "POL-B-001",
        "policy_name": "Health Basic Plan",
        "insurer": "Synthetic Insurance Ltd",
        "sum_insured": 300000,
        "waiting_period_days": 60,
        "policy_start_date": "2025-03-01",
        "room_rent_limit_per_day": 3000,
        "icu_limit_per_day": 7000,
        "co_payment_percent": 20,
        "empanelled_hospitals": ["Max Hospital Noida", "AIIMS Delhi"],
        "exclusions_list": ["cosmetic", "hernia repair", "infertility treatment"],
        "covered_procedures": ["knee replacement", "dialysis", "appendectomy"],
        "pre_existing_conditions": ["asthma", "diabetes"],
        "day_care_procedures": ["cataract surgery", "chemotherapy"],
        "consumables_excluded": True,
    },
    "policy_c": {
        "policy_id": "POL-C-001",
        "policy_name": "Comprehensive Premium",
        "insurer": "Synthetic Insurance Ltd",
        "sum_insured": 1000000,
        "waiting_period_days": 0,
        "policy_start_date": "2024-01-01",
        "room_rent_limit_per_day": 10000,
        "icu_limit_per_day": 20000,
        "co_payment_percent": 0,
        "empanelled_hospitals": [],
        "exclusions_list": ["dental", "infertility treatment"],
        "covered_procedures": [],
        "pre_existing_conditions": [],
        "day_care_procedures": [],
        "consumables_excluded": False,
    },
}


def generate_policies():
    """Generate all 3 policy PDFs and metadata files."""
    for name, sections in _POLICY_SECTIONS.items():
        pdf_path = POLICIES_DIR / f"{name}.pdf"
        _gen_policy_pdf(name, sections, pdf_path)
        print(f"  [OK] {pdf_path}")

        meta_path = BASE / f"{name}_metadata.json"
        meta_path.write_text(json.dumps(_METADATA[name], indent=2), encoding="utf-8")
        print(f"  [OK] {meta_path}")


# ════════════════════════════════════════════════════════════════════
# BILL PDF GENERATION
# ════════════════════════════════════════════════════════════════════


def _gen_bill_pdf(
    output_path: Path,
    patient_name: str,
    hospital_name: str,
    diagnosis: str,
    admission_date: str,
    discharge_date: str,
    line_items: list[tuple[str, float]],
    total_amount: float,
):
    """Generate a single hospital bill PDF."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Hospital Name: {hospital_name}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 7, f"Patient Name: {patient_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Diagnosis: {diagnosis}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Date of Admission: {admission_date}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Date of Discharge: {discharge_date}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Table header
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(120, 8, "Description", border=1)
    pdf.cell(40, 8, "Amount (INR)", border=1, new_x="LMARGIN", new_y="NEXT", align="R")

    pdf.set_font("Helvetica", size=10)
    for desc, amount in line_items:
        pdf.cell(120, 7, desc, border=1)
        pdf.cell(40, 7, f"Rs. {int(amount)}", border=1, new_x="LMARGIN", new_y="NEXT", align="R")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(120, 8, "Total Amount")
    pdf.cell(40, 8, f"Rs. {int(total_amount)}", border=1, new_x="LMARGIN", new_y="NEXT", align="R")

    pdf.output(str(output_path))


# ── Bill scenarios ──────────────────────────────────────────────────

_PATIENTS = ["Arun Sharma", "Priya Singh", "Vikram Patel", "Neha Gupta", "Rohan Mehta"]
_HOSPITALS_OPEN = ["City Hospital Mumbai", "Medanta Gurugram", "Lilavati Hospital Mumbai",
                   "Narayana Health Bangalore", "Manipal Hospital Delhi"]

_BILLS: list[dict] = []


def _add_bills():
    global _BILLS

    # TC_001-TC_005: Clean claims (policy_c, approved)
    for i in range(5):
        _BILLS.append({
            "test_id": f"TC_{i+1:03d}",
            "bill_file": f"bill_{i+1:03d}.pdf",
            "policy_file": "policy_c.pdf",
            "metadata_file": "policy_c_metadata.json",
            "patient_name": _PATIENTS[i],
            "hospital_name": _HOSPITALS_OPEN[i],
            "diagnosis": "Acute Appendicitis",
            "admission": "01/06/2025",
            "discharge": "05/06/2025",
            "items": [
                ("Appendectomy Surgery", 50000),
                ("Room Rent General Ward 4 days", 20000),
                ("Medicines and Drugs", 5000),
                ("Diagnostic Tests Blood Urine", 3000),
            ],
            "total": 78000,
            "expected_status": "approved",
            "expected_rules_fired": [],
            "expected_citation_pages": [],
            "scenario": "Clean claim - fully covered",
        })

    # TC_006-TC_010: Excluded procedure (policy_a, rejected R01)
    excluded = [
        ("cosmetic rhinoplasty surgery", "cosmetic deformity"),
        ("cataract lens replacement", "bilateral cataract"),
        ("dental implant procedure", "dental caries"),
        ("cosmetic liposuction", "body contouring"),
        ("dental root canal treatment", "dental abscess"),
    ]
    for i, (proc, diag) in enumerate(excluded):
        idx = i + 6
        _BILLS.append({
            "test_id": f"TC_{idx:03d}",
            "bill_file": f"bill_{idx:03d}.pdf",
            "policy_file": "policy_a.pdf",
            "metadata_file": "policy_a_metadata.json",
            "patient_name": f"Patient {idx}",
            "hospital_name": "Apollo Hospital Delhi",
            "diagnosis": diag,
            "admission": "01/08/2025",
            "discharge": "02/08/2025",
            "items": [
                (proc, 50000),
                ("Consultation charges", 2000),
            ],
            "total": 52000,
            "expected_status": "partially_approved",
            "expected_rules_fired": ["R01"],
            "expected_citation_pages": [],
            "scenario": f"Excluded procedure - {proc.split()[0]}",
        })

    # TC_011-TC_013: Exceeds sum insured (policy_b, R05)
    for i in range(3):
        idx = i + 11
        _BILLS.append({
            "test_id": f"TC_{idx:03d}",
            "bill_file": f"bill_{idx:03d}.pdf",
            "policy_file": "policy_b.pdf",
            "metadata_file": "policy_b_metadata.json",
            "patient_name": f"Patient {idx}",
            "hospital_name": "Max Hospital Noida",
            "diagnosis": "Multiple organ failure",
            "admission": "01/07/2025",
            "discharge": "10/07/2025",
            "items": [
                ("ICU charges 9 days", 180000),
                ("Emergency surgery", 150000),
                ("Medicines IV fluids", 50000),
                ("Diagnostic imaging MRI CT", 30000),
            ],
            "total": 410000,
            "expected_status": "partially_approved",
            "expected_rules_fired": ["R05"],
            "expected_citation_pages": [],
            "scenario": "Exceeds sum insured",
        })

    # TC_014-TC_016: Within waiting period (policy_b, R02)
    for i in range(3):
        idx = i + 14
        _BILLS.append({
            "test_id": f"TC_{idx:03d}",
            "bill_file": f"bill_{idx:03d}.pdf",
            "policy_file": "policy_b.pdf",
            "metadata_file": "policy_b_metadata.json",
            "patient_name": f"Patient {idx}",
            "hospital_name": "AIIMS Delhi",
            "diagnosis": "Acute Appendicitis",
            "admission": "20/03/2025",
            "discharge": "25/03/2025",
            "items": [
                ("Appendectomy surgery", 60000),
                ("Room Rent General Ward 5 days", 15000),
            ],
            "total": 75000,
            "expected_status": "rejected",
            "expected_rules_fired": ["R02"],
            "expected_citation_pages": [],
            "scenario": "Within waiting period",
        })

    # TC_017-TC_019: Room rent over sub-limit (policy_a, R03 partial)
    for i in range(3):
        idx = i + 17
        _BILLS.append({
            "test_id": f"TC_{idx:03d}",
            "bill_file": f"bill_{idx:03d}.pdf",
            "policy_file": "policy_a.pdf",
            "metadata_file": "policy_a_metadata.json",
            "patient_name": f"Patient {idx}",
            "hospital_name": "Apollo Hospital Delhi",
            "diagnosis": "Pneumonia",
            "admission": "01/09/2025",
            "discharge": "05/09/2025",
            "items": [
                ("Room Rent General Ward 4 days", 30000),
                ("Medicines antibiotics", 8000),
                ("Diagnostic tests Xray blood", 5000),
            ],
            "total": 43000,
            "expected_status": "partially_approved",
            "expected_rules_fired": ["R03"],
            "expected_citation_pages": [],
            "scenario": "Room rent exceeds sub-limit",
        })

    # TC_020-TC_021: Non-network hospital (policy_a, R10)
    for i in range(2):
        idx = i + 20
        _BILLS.append({
            "test_id": f"TC_{idx:03d}",
            "bill_file": f"bill_{idx:03d}.pdf",
            "policy_file": "policy_a.pdf",
            "metadata_file": "policy_a_metadata.json",
            "patient_name": f"Patient {idx}",
            "hospital_name": "City Care Hospital Jaipur",
            "diagnosis": "Acute Appendicitis",
            "admission": "10/08/2025",
            "discharge": "14/08/2025",
            "items": [
                ("Appendectomy surgery", 55000),
                ("Room Rent General Ward 4 days", 16000),
                ("Medicines and drugs", 7000),
            ],
            "total": 78000,
            "expected_status": "rejected",
            "expected_rules_fired": ["R10"],
            "expected_citation_pages": [],
            "scenario": "Non-network hospital",
        })

    # TC_022-TC_023: Pre-existing condition (policy_a, R04)
    pre_existing_cases = [
        ("diabetic nephropathy", "Diabetic nephropathy complications"),
        ("hypertensive crisis", "Hypertensive emergency"),
    ]
    for i, (diag, desc) in enumerate(pre_existing_cases):
        idx = i + 22
        _BILLS.append({
            "test_id": f"TC_{idx:03d}",
            "bill_file": f"bill_{idx:03d}.pdf",
            "policy_file": "policy_a.pdf",
            "metadata_file": "policy_a_metadata.json",
            "patient_name": f"Patient {idx}",
            "hospital_name": "Apollo Hospital Delhi",
            "diagnosis": diag,
            "admission": "15/07/2025",
            "discharge": "20/07/2025",
            "items": [
                ("Dialysis treatment", 40000),
                ("Medicines and IV fluids", 15000),
                ("ICU charges 3 days", 45000),
            ],
            "total": 100000,
            "expected_status": "partially_approved",
            "expected_rules_fired": ["R07"],
            "expected_citation_pages": [],
            "scenario": f"Pre-existing condition - {desc}",
        })

    # TC_024: Multiple rules - excluded + non-network + consumables
    _BILLS.append({
        "test_id": "TC_024",
        "bill_file": "bill_024.pdf",
        "policy_file": "policy_b.pdf",
        "metadata_file": "policy_b_metadata.json",
        "patient_name": "Patient 24",
        "hospital_name": "Random Clinic Mumbai",
        "diagnosis": "cosmetic burns treatment",
        "admission": "01/08/2025",
        "discharge": "05/08/2025",
        "items": [
            ("cosmetic surgery reconstruction", 80000),
            ("Consumable surgical supplies", 10000),
        ],
        "total": 90000,
        "expected_status": "rejected",
        "expected_rules_fired": ["R01", "R10"],
        "expected_citation_pages": [],
        "scenario": "Multiple rules - exclusion + non-network + consumables",
    })

    # TC_025: Within waiting period + exceeds sum insured
    _BILLS.append({
        "test_id": "TC_025",
        "bill_file": "bill_025.pdf",
        "policy_file": "policy_b.pdf",
        "metadata_file": "policy_b_metadata.json",
        "patient_name": "Patient 25",
        "hospital_name": "AIIMS Delhi",
        "diagnosis": "Major cardiac event",
        "admission": "15/03/2025",
        "discharge": "25/03/2025",
        "items": [
            ("Cardiac bypass surgery", 200000),
            ("ICU charges 10 days", 150000),
            ("Medicines cardiac drugs", 50000),
        ],
        "total": 400000,
        "expected_status": "rejected",
        "expected_rules_fired": ["R02", "R05"],
        "expected_citation_pages": [],
        "scenario": "Multiple rules - waiting period + exceeds sum insured",
    })


def generate_bills():
    """Generate all 25 bill PDFs."""
    _add_bills()
    for bill in _BILLS:
        _gen_bill_pdf(
            output_path=BILLS_DIR / bill["bill_file"],
            patient_name=bill["patient_name"],
            hospital_name=bill["hospital_name"],
            diagnosis=bill["diagnosis"],
            admission_date=bill["admission"],
            discharge_date=bill["discharge"],
            line_items=bill["items"],
            total_amount=bill["total"],
        )
        print(f"  [OK] {bill['bill_file']} - {bill['scenario']}")


def generate_ground_truth():
    """Generate ground_truth.json."""
    if not _BILLS:
        _add_bills()

    entries = []
    for b in _BILLS:
        entries.append({
            "test_id": b["test_id"],
            "bill_file": b["bill_file"],
            "policy_file": b["policy_file"],
            "metadata_file": b["metadata_file"],
            "expected_status": b["expected_status"],
            "expected_rules_fired": b["expected_rules_fired"],
            "expected_citation_pages": b["expected_citation_pages"],
            "scenario": b["scenario"],
        })

    gt_path = BASE / "ground_truth.json"
    gt_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"  [OK] {gt_path} ({len(entries)} entries)")


# ════════════════════════════════════════════════════════════════════


def main():
    print("=" * 60)
    print(" Generating Synthetic Test Data")
    print("=" * 60)

    _ensure_dirs()

    print("\n[1/3] Generating policy PDFs...")
    generate_policies()

    print("\n[2/3] Generating bill PDFs...")
    generate_bills()

    print("\n[3/3] Generating ground truth...")
    generate_ground_truth()

    print("\n" + "=" * 60)
    print(" SUMMARY")
    print("=" * 60)
    print(f"  Policies:    3 PDFs + 3 metadata JSONs")
    print(f"  Bills:       {len(_BILLS)} PDFs")
    print(f"  Ground Truth: data/synthetic/ground_truth.json")
    print(f"  Total files: {3*2 + len(_BILLS) + 1}")
    print("=" * 60)


if __name__ == "__main__":
    main()
