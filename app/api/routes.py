"""API routes for the Insurance Claim Settlement Agent.

All route handlers are async. Pipeline logic lives in services —
routes only call services and handle HTTP concerns.
"""

import json
import logging
import shutil
import tempfile
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.models import ClaimDecision, PolicyChunk
from app.services.bill_processor import process_bill
from app.services.decision_engine import process_claim
from app.services.embedder import encode_chunks
from app.services.index_builder import build_index
from app.services.policy_processor import process_policy
from app.services.rule_engine import PolicyRuleConfig
from app.services.semantic_matcher import match_line_item

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Claims"])


# ── Helper: Claims storage path ─────────────────────────────────────


def _claims_dir() -> Path:
    """Return the claims storage directory, creating it if needed."""
    p = Path(settings.storage_dir) / "claims"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Helper: Save uploaded file to disk ──────────────────────────────


async def _save_upload(upload: UploadFile, dest: Path) -> None:
    """Save an UploadFile to a local path."""
    content = await upload.read()
    dest.write_bytes(content)


# ── Helper: Parse comma-separated optional fields ───────────────────


def _parse_dates(raw: str) -> list[date]:
    """Parse comma-separated ISO dates, skipping empty/invalid entries."""
    if not raw or not raw.strip():
        return []
    dates: list[date] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            dates.append(date.fromisoformat(part))
        except ValueError:
            continue
    return dates


def _parse_csv(raw: str) -> list[str]:
    """Parse comma-separated strings, filtering empty entries."""
    if not raw or not raw.strip():
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


# ════════════════════════════════════════════════════════════════════
# ENDPOINT 1: Process a claim
# ════════════════════════════════════════════════════════════════════


@router.post("/claims/process")
async def process_claim_endpoint(
    bill_pdf: UploadFile = File(...),
    policy_pdf: UploadFile = File(...),
    policy_metadata: UploadFile = File(...),
    prior_claim_dates: str = Form(default=""),
    required_docs: str = Form(default=""),
    submitted_docs: str = Form(default=""),
):
    """Process an insurance claim from uploaded bill and policy PDFs.

    Accepts multipart/form-data with the bill PDF, policy PDF, and
    policy metadata JSON. Returns a full ClaimDecision.
    """
    claim_id = str(uuid4())
    tmp_dir = tempfile.mkdtemp()

    try:
        # Save uploaded files to temp directory
        tmp_path = Path(tmp_dir)
        bill_path = tmp_path / "bill.pdf"
        policy_path = tmp_path / "policy.pdf"
        meta_path = tmp_path / "policy_metadata.json"

        await _save_upload(bill_pdf, bill_path)
        await _save_upload(policy_pdf, policy_path)
        await _save_upload(policy_metadata, meta_path)

        # Step 3: Process bill
        bill = process_bill(bill_path)

        # Step 4: Process policy
        chunks, policy_meta = process_policy(policy_path, meta_path)

        # Step 5: Encode chunks
        chunks = encode_chunks(chunks)

        # Step 6: Build FAISS index
        if chunks:
            faiss_index, indexed_chunks = build_index(chunks)
        else:
            faiss_index, indexed_chunks = None, []

        # Step 7: Match each line item
        matched_chunks_per_item: dict[int, list[PolicyChunk]] = {}
        if faiss_index is not None:
            for item in bill.line_items:
                matched_chunks_per_item[item.item_id] = match_line_item(
                    item.description, faiss_index, indexed_chunks,
                )

        # Step 8: Parse optional fields
        parsed_dates = _parse_dates(prior_claim_dates)
        parsed_required = _parse_csv(required_docs)
        parsed_submitted = _parse_csv(submitted_docs)

        # Build PolicyRuleConfig from the metadata JSON
        meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
        rule_config = PolicyRuleConfig(
            policy_id=meta_raw.get("policy_id", policy_meta.policy_id),
            **{k: v for k, v in meta_raw.items() if k != "policy_id" and k in PolicyRuleConfig.model_fields},
        )

        # Step 9: Process claim
        decision = process_claim(
            claim_id=claim_id,
            bill=bill,
            meta=rule_config,
            matched_chunks_per_item=matched_chunks_per_item,
            prior_claim_dates=parsed_dates or None,
            required_docs=parsed_required or None,
            submitted_docs=parsed_submitted or None,
        )

        # Step 10: Save decision
        claims_dir = _claims_dir()
        decision_path = claims_dir / f"{claim_id}.json"
        decision_path.write_text(
            decision.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return decision.model_dump(mode="json")

    except Exception as e:
        logger.exception("Claim processing failed for %s", claim_id)
        raise HTTPException(
            status_code=422,
            detail={"detail": "Claim processing failed", "error": str(e)},
        )

    finally:
        # Always clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════
# ENDPOINT 2: Get a claim by ID
# ════════════════════════════════════════════════════════════════════


@router.get("/claims/{claim_id}")
async def get_claim(claim_id: str):
    """Retrieve a previously processed claim by its ID."""
    claim_path = _claims_dir() / f"{claim_id}.json"

    if not claim_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Claim '{claim_id}' not found",
        )

    try:
        raw = claim_path.read_text(encoding="utf-8")
        decision = ClaimDecision.model_validate_json(raw)
        return decision.model_dump(mode="json")
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Claim record is corrupted",
        )


# ════════════════════════════════════════════════════════════════════
# ENDPOINT 3: List all claims
# ════════════════════════════════════════════════════════════════════


@router.get("/claims/")
async def list_claims():
    """List all processed claim IDs."""
    claims_dir = _claims_dir()

    if not claims_dir.exists():
        return {"claims": [], "total": 0}

    claim_ids = sorted(
        f.stem for f in claims_dir.glob("*.json")
    )
    return {"claims": claim_ids, "total": len(claim_ids)}


# ════════════════════════════════════════════════════════════════════
# ENDPOINT 4: Get claim report (stub)
# ════════════════════════════════════════════════════════════════════


@router.get("/claims/{claim_id}/report")
async def get_claim_report(claim_id: str):
    """Generate a PDF report for a processed claim."""
    claim_path = _claims_dir() / f"{claim_id}.json"

    if not claim_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Claim '{claim_id}' not found",
        )

    try:
        raw = claim_path.read_text(encoding="utf-8")
        decision = ClaimDecision.model_validate_json(raw)
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Claim record is corrupted",
        )

    # Generate PDF report (bill=None — patient fields show N/A)
    from app.services.report_generator import generate_report

    report_bytes = generate_report(decision, bill=None)

    # Save report to reports directory
    reports_dir = Path(settings.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{claim_id}.pdf"
    report_path.write_bytes(report_bytes)

    from fastapi.responses import FileResponse

    return FileResponse(
        path=str(report_path),
        media_type="application/pdf",
        filename=f"claim_{claim_id}.pdf",
    )

